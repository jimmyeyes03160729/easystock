"""B1/B2/B3 independent PAPER lanes. No broker orders or legacy B ledger reuse.

Thresholds are an explicit research specification, not the authors' undisclosed SOP.
Callbacks only collect bounded observations; advance() runs on the runtime loop.
"""
from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import threading

from .config import DB_DIR, FEE_RATE, TAX_RATE
from .orderbook import get_tick_size

TPE = timezone(timedelta(hours=8))
SPECS = {
    "B1": {"label": "五檔順勢拉回", "start": "09:00:00", "cutoff": "09:10:00", "end": "09:10:00"},
    "B2": {"label": "布林轉折", "start": "09:05:00", "cutoff": "12:30:00", "end": "12:55:00"},
    "B3": {"label": "五分K趨勢突破", "start": "09:05:00", "cutoff": "12:30:00", "end": "12:55:00"},
}


@contextmanager
def database(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def taiwan(dt):
    return dt.replace(tzinfo=TPE) if dt.tzinfo is None else dt.astimezone(TPE)


def stamp(value):
    try:
        return taiwan(value if isinstance(value, datetime) else datetime.fromisoformat(str(value)))
    except (ValueError, TypeError):
        return None


def finite(value, default=0.0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def completed_bars(rows, now):
    """Never use a future or forming bar, including yesterday's bars."""
    out = []
    for row in rows:
        dt = stamp(row.get("date") or row.get("start"))
        if dt and dt.date() == now.date() and dt + timedelta(minutes=5) <= now:
            if all(finite(row.get(k)) > 0 for k in ("open", "high", "low", "close")):
                out.append({**row, "date": dt.isoformat()})
    return sorted(out, key=lambda r: r["date"])


def default_sender(text, event_key):
    # Uses existing owner-only destination validation, notification switches and
    # durable per-channel receipts. No test messages and no duplicate legacy B pushes.
    from trade_notifications import _send
    return _send(text, "summary", event_key)


class LaneSuite:
    def __init__(self, db_path=None, sender=None, publisher=None, recorder=None, offline=False):
        self.path = Path(db_path or os.environ.get("RUNWAY_B_LANES_DB", str(DB_DIR / "lanes.sqlite")))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with database(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions(day TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS reports(key TEXT PRIMARY KEY, text TEXT NOT NULL)")
        self.lock = threading.RLock()
        self.books, self.tapes = {}, {}
        self.rows, self.bars = {}, {}
        self.day, self.state = "", {}
        self.market = {"valid": False}
        self.subscribe = None
        self.subscribed = set()
        self.sender = sender or default_sender
        self.publisher = publisher
        self.recorder, self.offline = recorder, offline
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="b-lanes-report")
        self.jobs = set()
        self._last_save = self._last_publish = 0.0
        self.last_feed_at = None
        self.enabled = os.environ.get("RUNWAY_B_LANES_ENABLED", "1").lower() in ("1", "true", "yes")

    def _capture(self, kind, data):
        if self.recorder and not self.offline:
            try:
                self.recorder.record(kind, data)
            except Exception:
                # Recording failure cannot block the quote callback or change trades.
                self.recorder.errors += 1

    def close_recording(self):
        with self.lock:
            if self.recorder:
                self.recorder.close(self.state)

    def register_bidask_subscriber(self, fn):
        self.subscribe = fn

    def has_open(self, symbol):
        with self.lock:
            return any(symbol in lane["positions"] for lane in self.state.values())

    def release_symbol(self, symbol):
        with self.lock:
            if not self.has_open(symbol):
                self._capture('release', {'symbol':symbol})
                self.subscribed.discard(symbol)
                self.rows.pop(symbol, None)
                self.books.pop(symbol, None)
                self.tapes.pop(symbol, None)
                self.bars.pop(symbol, None)

    def _roll(self, now):
        day = now.date().isoformat()
        if day == self.day:
            return
        # Old open positions are retained in their own dated session, never silently
        # carried into today's P&L or marked closed with today's prices.
        with database(self.path) as db:
            row = db.execute("SELECT state FROM sessions WHERE day=?", (day,)).fetchone()
            old = db.execute("SELECT day,state FROM sessions WHERE day<? ORDER BY day DESC LIMIT 1", (day,)).fetchone()
        self.day = day
        self.state = json.loads(row[0]) if row else {
            k: {"positions": {}, "trades": [], "used": 0.0, "rejects": {}, "entries": 0} for k in SPECS
        }
        self.prior_unresolved = bool(old and any(v["positions"] for v in json.loads(old[1]).values()))
        self.books.clear()
        self.tapes.clear()
        self.rows.clear()
        self.bars.clear()
        self.last_feed_at = None
        self._capture('seed', {'day':self.day,'state':self.state,'prior_unresolved':self.prior_unresolved})

    def _save(self, now, force=False):
        if self.offline:
            return
        if force or now.timestamp() - self._last_save >= 5:
            with database(self.path) as db:
                db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", (self.day, json.dumps(self.state, ensure_ascii=False)))
            self._last_save = now.timestamp()

    def on_bidask(self, symbol, quote):
        if not self.enabled:
            return
        get = quote.get if isinstance(quote, dict) else lambda k: getattr(quote, k, None)
        dt = stamp(get("datetime"))
        if dt is None:
            return
        with self.lock:
            # Runtime clock opens the day. Do not let a delayed callback change it.
            if dt.date().isoformat() != self.day or get("simtrade") or get("suspend"):
                return
            try:
                bp, ap = list(get("bid_price")), list(get("ask_price"))
                bv, av = list(get("bid_volume")), list(get("ask_volume"))
            except TypeError:
                return
            if not all(len(x) == 5 for x in (bp, ap, bv, av)):
                return
            bp, ap, bv, av = [[finite(x, -1) for x in seq] for seq in (bp, ap, bv, av)]
            if min(bp + ap) <= 0 or min(bv + av) < 0 or bp[0] >= ap[0]:
                return
            if bp != sorted(bp, reverse=True) or ap != sorted(ap):
                return
            history = self.books.setdefault(symbol, deque(maxlen=300))
            if history and dt <= history[-1]["dt"]:
                return
            self._capture('bidask', {'symbol':symbol,'quote':{'datetime':dt.isoformat(),
                'bid_price':bp,'ask_price':ap,'bid_volume':bv,'ask_volume':av}})
            total = sum(bv + av)
            book = {"dt": dt, "bid": bp[0], "ask": ap[0], "bv": bv[0], "av": av[0],
                    "obi": (sum(bv) - sum(av)) / total if total else 0}
            # Keep the most recent quote in each 250ms bucket. A high-frequency
            # liquid stock must not exhaust the bounded deque before five seconds.
            if history and int(history[-1]["dt"].timestamp() * 4) == int(dt.timestamp() * 4):
                history[-1] = book
            else:
                history.append(book)

    def on_tick(self, symbol, price, dt, tick_type=0, volume=0):
        dt = taiwan(dt)
        price, volume = finite(price), finite(volume)
        if not self.enabled or price <= 0:
            return
        with self.lock:
            if dt.date().isoformat() != self.day:
                return
            tape = self.tapes.setdefault(symbol, deque(maxlen=4000))
            if tape and dt < tape[-1][0]:
                return
            tape.append((dt, price, int(tick_type or 0), volume))
            self._capture('tick', {'symbol':symbol,'price':price,'datetime':dt.isoformat(),
                                   'tick_type':int(tick_type or 0),'volume':volume})
            self.last_feed_at = dt if not self.last_feed_at or dt > self.last_feed_at else self.last_feed_at

    def on_radar_update(self, rows, cache, previous_closes, now, market=None):
        if not self.enabled:
            return
        now = taiwan(now)
        with self.lock:
            self._roll(now)
            self.market = dict(market or {"valid": False})
            self.market["observed_at"] = now.timestamp()
            for row in rows:
                symbol = str(row.get("symbol") or "")
                if not symbol:
                    continue
                self.rows[symbol] = {**row, "previous_close": finite(previous_closes.get(symbol)), "observed_at": now.timestamp()}
                self.bars[symbol] = completed_bars(cache.rows5(symbol) or [], now)
                if self.subscribe and symbol not in self.subscribed:
                    try:
                        self.subscribe(symbol)
                        self.subscribed.add(symbol)
                    except Exception:
                        pass
            self._capture('radar', {'now':now.isoformat(),'rows':rows,'market':self.market,
                'previous_closes':previous_closes,'bars':{str(r['symbol']):self.bars.get(str(r['symbol']),[]) for r in rows if r.get('symbol')}})

    def _book(self, symbol, now):
        h = self.books.get(symbol, [])
        if h and 0 <= (now - h[-1]["dt"]).total_seconds() <= 3:
            return h[-1]
        return None

    def _observations(self, symbol, now):
        tape = [x for x in self.tapes.get(symbol, []) if 0 <= (now - x[0]).total_seconds() <= 60]
        book = self._book(symbol, now)
        if not book or len(tape) < 6 or (now - tape[-1][0]).total_seconds() > 3:
            return None
        if (book["ask"] - book["bid"]) > get_tick_size(book["bid"]) * 1.01:
            return None
        books = [b for b in self.books.get(symbol, []) if 0 <= (now - b["dt"]).total_seconds() <= 15]
        if len(books) < 3 or (books[-1]["dt"] - books[0]["dt"]).total_seconds() < 5:
            return None
        recent = [x for x in tape if (now - x[0]).total_seconds() <= 10]
        classified = sum(x[3] for x in recent if x[2] in (1, 2))
        total = sum(x[3] for x in recent)
        if total <= 0 or classified / total < .8:
            return None
        buy = sum(x[3] for x in recent if x[2] == 1) / classified
        return tape, book, books, buy

    def _signal(self, lane, symbol, now):
        row = self.rows[symbol]
        obs = self._observations(symbol, now)
        if not obs:
            return None, "五檔／逐筆不足或延遲"
        tape, book, books, buy = obs
        price, prev = tape[-1][1], row["previous_close"]
        if price <= 0 or prev <= 0:
            return None, "價格或昨收資料不符"
        if abs(price / prev - 1) >= .07:
            return None, "接近漲跌停風險"
        direction = 1 if buy >= .65 and sum(b["obi"] >= .1 for b in books[-3:]) == 3 else (
            -1 if buy <= .35 and sum(b["obi"] <= -.1 for b in books[-3:]) == 3 else 0)
        if not direction:
            return None, "買賣力道尚未確認"
        tick = get_tick_size(price)
        entry = book["ask"] if direction == 1 else book["bid"]
        bars = completed_bars(self.bars.get(symbol, []), now)
        reason = ""
        if lane == "B1":
            sector = row.get("sector")
            peers = [r for sym, r in self.rows.items() if sym != symbol and sector and r.get("sector") == sector
                     and now.timestamp() - r["observed_at"] <= 30 and finite(r.get("previous_close")) > 0]
            aligned = sum(direction * (finite(r.get("price")) / r["previous_close"] - 1) > 0 for r in peers)
            if len(peers) < 2 or aligned / len(peers) < .6:
                return None, "族群資料不足或方向不同"
            # Require a past impulse, then pullback holding the old extreme, then
            # renewed tape direction. No completed 5m candle needed.
            earlier = [x[1] for x in tape if (now - x[0]).total_seconds() > 10]
            recent = [x[1] for x in tape if (now - x[0]).total_seconds() <= 10]
            if len(earlier) < 3 or len(recent) < 3:
                return None, "等待拉回結構"
            hi, lo = max(earlier), min(earlier)
            if hi - lo < 2 * tick:
                return None, "波動不足"
            if direction == 1:
                valid = price >= prev and min(recent) > lo and min(recent) <= hi - tick and price > min(recent)
            else:
                valid = price <= prev and max(recent) < hi and max(recent) >= lo + tick and price < max(recent)
            if not valid:
                return None, "拉回／反彈未確認"
            reason = "60秒結構＋10秒成交力道＋連續五檔"
            stop, target = entry - direction * 2 * tick, entry + direction * 3 * tick
        elif lane == "B2":
            if len(bars) < 20:
                return None, "等待20根完整五分K"
            closes = [finite(b["close"]) for b in bars[-20:]]
            mid = sum(closes) / 20
            sd = math.sqrt(sum((p - mid) ** 2 for p in closes) / 20)
            if sd <= 0:
                return None, "布林無波動"
            if not ((direction == 1 and min(x[1] for x in tape) < mid - 2 * sd and price > mid - 2 * sd)
                    or (direction == -1 and max(x[1] for x in tape) > mid + 2 * sd and price < mid + 2 * sd)):
                return None, "未出軌後返回"
            stop, target = entry - direction * 2 * tick, mid
            if direction * (target - entry) < 3 * tick:
                return None, "轉折空間不足"
            reason = "當日20根五分K布林返回＋五檔力道"
        else:
            if len(bars) < 3:
                return None, "等待完整五分K突破"
            last, prior = bars[-1], bars[-3:-1]
            if direction == 1:
                valid = last["close"] > max(b["high"] for b in prior) and last["close"] > last["open"]
                stop = finite(last["low"]) - tick
            else:
                valid = last["close"] < min(b["low"] for b in prior) and last["close"] < last["open"]
                stop = finite(last["high"]) + tick
            if not valid or direction * (entry - stop) <= 0 or abs(entry - stop) / entry > .015:
                return None, "突破或結構風險不符"
            if finite(last.get("volume")) <= sum(finite(b.get("volume")) for b in prior) / 2:
                return None, "突破量能不足"
            target = entry + direction * max(3 * tick, 1.5 * abs(entry - stop))
            target = (math.ceil(target / tick) if direction == 1 else math.floor(target / tick)) * tick
            reason = "完整五分K放量突破＋結構停損"
        if direction * (entry - stop) <= 0 or direction * (target - entry) <= 0:
            return None, "進出場價位不符"
        return {"direction": direction, "entry_price": entry, "stop_price": stop, "target": target,
                "signal_type": lane, "reasons": [reason], "score": 0}, ""

    def _net(self, pos, exit_price):
        buy, sell = (pos["entry_price"], exit_price) if pos["direction"] == 1 else (exit_price, pos["entry_price"])
        shares = pos["shares"]
        fee = math.floor(buy * shares * FEE_RATE) + math.floor(sell * shares * FEE_RATE)
        tax = math.floor(sell * shares * TAX_RATE)
        return (sell - buy) * shares - fee - tax

    def _report(self, now, phase):
        lines = [f"EasyStock B1／B2／B3｜{self.day}", "09:10 狀態" if phase == "0910" else "今日結束狀態",
                 f"資料時間：{now.strftime('%H:%M:%S')}（台灣）", "獨立模擬帳本，非實際成交；三條額度不相加為實盤資金。"]
        for lane, spec in SPECS.items():
            s = self.state[lane]
            pnl = sum(t["net_pnl"] for t in s["trades"])
            wins = sum(t["net_pnl"] > 0 for t in s["trades"])
            count = len(s["trades"])
            ongoing = now.strftime("%H:%M:%S") < spec["end"]
            status = "繼續觀察" if ongoing else ("待取得新鮮報價平倉" if s["positions"] else "已結束")
            rate = f"{wins/count*100:.1f}%" if count else "無交易"
            lines += [f"{lane} {spec['label']}：{status}", f"已平倉{count}筆／持倉{len(s['positions'])}筆；已實現淨損益{pnl:+,.0f}元；勝率{rate}"]
            if not count and not s["positions"]:
                rejects = Counter(s["rejects"]).most_common(1)
                lines.append("原因：" + (rejects[0][0] if rejects else "無有效行情／尚無訊號"))
        if phase == "0910":
            lines.append("B2／B3 尚未日結；未實現損益不列入已實現淨損益。")
        if self.prior_unresolved:
            lines.append("前日有未完成部位，今日新進場暫停，需核對資料。")
        return "\n".join(lines)

    def _queue_report(self, now, phase):
        if self.offline:
            return
        key = f"b-lanes:v1:{self.day}:{phase}"
        if key in self.jobs:
            return
        with database(self.path) as db:
            db.execute("INSERT OR IGNORE INTO reports VALUES(?,?)", (key, self._report(now, phase)))
            text = db.execute("SELECT text FROM reports WHERE key=?", (key,)).fetchone()[0]
        self.jobs.add(key)
        self._submit(self.sender, text, key)

    def _submit(self, fn, *args):
        def done(future):
            exc = future.exception()
            if exc:
                print(f"[B_LANES_BACKGROUND_WARN] {type(exc).__name__}")
        self.worker.submit(fn, *args).add_done_callback(done)

    def advance(self, now):
        if not self.enabled:
            return
        now = taiwan(now)
        with self.lock:
            self._roll(now)
            time_str = now.strftime("%H:%M:%S")
            changed = False
            for lane, spec in SPECS.items():
                state = self.state[lane]
                checks = state.setdefault('execution_checks', {})
                def count(key):
                    checks[key] = checks.get(key,0)+1
                for symbol, pos in list(state["positions"].items()):
                    book = self._book(symbol, now)
                    count('exit_quote_checks')
                    if not book:
                        count('stale_exit_checks')
                        continue
                    exit_price = book["bid"] if pos["direction"] == 1 else book["ask"]
                    stop = pos["direction"] * (exit_price - pos["stop_price"]) <= 0
                    profit = pos["direction"] * (exit_price - pos["target"]) >= 0
                    if time_str >= spec["end"] or stop or profit:
                        count('exit_fill_checks')
                        lots = int((book["bv"] if pos["direction"] == 1 else book["av"]))
                        # A thin quote cannot claim all shares filled. Keep pending until
                        # enough visible depth exists; final report honestly shows pending.
                        if lots * 1000 < pos["shares"]:
                            count('thin_exit_checks')
                            continue
                        net = self._net(pos, exit_price)
                        state["trades"].append({**pos, "exit_price": exit_price, "exit_time": now.isoformat(),
                            "net_pnl": net, "return_pct": net / (pos["entry_price"] * pos["shares"]) * 100,
                            "exit_reason": "時段結束" if time_str >= spec["end"] else ("停損" if stop else "停利")})
                        del state["positions"][symbol]
                        changed = True
                if not spec["start"] <= time_str < spec["cutoff"] or self.prior_unresolved:
                    continue
                if sum(t["net_pnl"] for t in state["trades"]) <= -6000 or len(state["positions"]) >= 3:
                    continue
                for symbol, row in self.rows.items():
                    if len(state["positions"]) >= 3:
                        break
                    if symbol in state["positions"] or now.timestamp() - row["observed_at"] > 30:
                        continue
                    # Losses never trigger immediate revenge entries. One entry per
                    # symbol/lane/day is the initial registered experiment.
                    if any(t["symbol"] == symbol for t in state["trades"]):
                        continue
                    if not self.market.get("valid") or now.timestamp() - self.market.get("observed_at", 0) > 30 or self.market.get("gate_action") == "BLOCK":
                        reason, signal = "大盤風險資料不符", None
                    else:
                        signal, reason = self._signal(lane, symbol, now)
                    if signal is None:
                        state["rejects"][reason] = state["rejects"].get(reason, 0) + 1
                        continue
                    if signal["direction"] == -1 and row.get("daytrade_short_allowed") is not True:
                        state["rejects"]["未確認先賣後買資格"] = state["rejects"].get("未確認先賣後買資格", 0) + 1
                        continue
                    price = signal["entry_price"]
                    count('entry_fill_checks')
                    shares = int(min(200000, 1000000 - state["used"]) // (price * 1000)) * 1000
                    book = self._book(symbol, now)
                    depth = (book["av"] if signal["direction"] == 1 else book["bv"]) if book else 0
                    if shares < 1000:
                        count('entry_limit_checks')
                        continue
                    if depth * 1000 < shares:
                        count('thin_entry_checks')
                        continue
                    state["positions"][symbol] = {**signal, "symbol": symbol, "name": row.get("name") or symbol,
                        "entry_time": now.isoformat(), "shares": shares, "current_price": price,
                        "trade_id": f"{lane}-{self.day}-{symbol}", "half_closed": False}
                    state["used"] += price * shares
                    state["entries"] += 1
                    changed = True
            self._save(now, force=changed)
            # Only an observed trading session can emit a report. Weekend/holiday
            # clocks or stale prior-day quotes never generate fabricated daily results.
            active = self.last_feed_at is not None or any(s["entries"] for s in self.state.values())
            if active and "09:10:00" <= time_str <= "13:30:00":
                self._queue_report(now, "0910")
            if active and "12:55:00" <= time_str <= "13:30:00":
                phase = "pending1255" if any(s["positions"] for s in self.state.values()) else "final"
                self._queue_report(now, phase)
            if self.publisher and now.timestamp() - self._last_publish >= 15:
                snapshot = self.export_snapshot(now)
                self._last_publish = now.timestamp()
                self._submit(self.publisher, snapshot)
            if self.recorder and not self.offline:
                import hashlib
                state_hash=hashlib.sha256(json.dumps(self.state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                self._capture('clock', {'now':now.isoformat(),'state_hash':state_hash})

    def export_snapshot(self, now=None):
        now = taiwan(now or datetime.now(TPE))
        lanes = {}
        for lane, spec in SPECS.items():
            s = self.state.get(lane, {"positions": {}, "trades": [], "used": 0, "rejects": {}})
            positions = {}
            for symbol, pos in s["positions"].items():
                book = self._book(symbol, now)
                positions[symbol] = {**pos, "current_price": (book["bid"] if pos["direction"] == 1 else book["ask"]) if book else None,
                                     "quote_stale": book is None}
            lanes[lane] = {"label": spec["label"], "open_positions": positions,
                "closed_trades": {t["trade_id"]: t for t in s["trades"]}, "used_amount": s["used"],
                "net_pnl": sum(t["net_pnl"] for t in s["trades"]), "rejects": s["rejects"],
                "session": "daytrade" if now.strftime("%H:%M:%S") < spec["end"] else ("pending_exit" if positions else "closed"),
                "last_update_at": now.isoformat(), "day": self.day, "mode": "paper", "rules_version": "b-lanes-v1"}
        return {"last_update_at": now.isoformat(), "day": self.day, "lanes": lanes}


def firebase_publish(snapshot):
    from firebase_admin import db
    db.reference("/market_data/intraday_live/runway_b_lanes").set(snapshot)
