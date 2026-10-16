"""Public chart projection only: no orders, ledger, signals, or broker requests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading

TPE = timezone(timedelta(hours=8))


def stamp(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return at.replace(tzinfo=TPE) if at.tzinfo is None else at.astimezone(TPE)


def records(live):
    """Only recorded A/B symbols/dates; never publish account or strategy metadata."""
    out = set()
    for scope in [live, *(((live.get('runway_b_lanes') or {}).get('lanes') or {}).values())]:
        for key in ('open_positions', 'closed_trades'):
            rows = scope.get(key) or {}
            for row in rows.values() if isinstance(rows, dict) else rows:
                try:
                    symbol = str(row['symbol'])
                    if re.fullmatch(r'\d{4,6}', symbol):
                        out.add((stamp(row['entry_time']).date().isoformat(), symbol))
                except (KeyError, ValueError, TypeError):
                    continue
    return sorted(out)


def payload(symbol, day, rows, *, now=None, previous_close=None):
    now = now or datetime.now(TPE)
    clean = {}
    for row in rows:
        try:
            at = stamp(row.get('time') or row.get('at'))
            if at.date().isoformat() != day or not '09:00' <= at.strftime('%H:%M') < '13:30' or at > now:
                continue
            if at.second or at.microsecond:
                continue
            values = {k: float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')}
            if any(isinstance(row[k], bool) for k in values) or not all(math.isfinite(v) for v in values.values()):
                continue
            if not 0 < values['low'] <= min(values['open'], values['close']) <= max(values['open'], values['close']) <= values['high'] or values['volume'] < 0:
                continue
            value = dict(time=at.isoformat(), **values, forming=bool(row.get('forming')))
            if at in clean and clean[at] != value:
                raise ValueError('conflicting_minute')
            clean[at] = value
        except (KeyError, TypeError, OverflowError):
            continue
        except ValueError as exc:
            if str(exc) == 'conflicting_minute':
                raise
    minutes = [clean[key] for key in sorted(clean)]
    if not minutes:
        return None
    grouped = {}
    for row in minutes:
        at = stamp(row['time']); bucket = at.replace(minute=at.minute // 5 * 5)
        grouped.setdefault(bucket, []).append(row)
    bars = []
    for at, group in grouped.items():
        bars.append(dict(time=at.isoformat(), open=group[0]['open'], high=max(r['high'] for r in group),
                         low=min(r['low'] for r in group), close=group[-1]['close'],
                         volume=sum(r['volume'] for r in group), minutes=len(group),
                         forming=any(r['forming'] for r in group) or at + timedelta(minutes=5) > now))
    complete = len(minutes) == 270 and minutes[-1]['time'][11:16] == '13:29'
    result = dict(symbol=symbol, date=day, source='sinotrade_shioaji', interval_minutes=5,
                  updated_at=now.isoformat(), quote_at=minutes[-1]['time'],
                  status='complete' if complete else 'partial',
                  session_closed=day < now.date().isoformat() or now.strftime('%H:%M') >= '13:30',
                  bars=bars, minute_bars=minutes)
    if isinstance(previous_close, dict) and previous_close.get('price', 0) > 0:
        result['previous_close'] = {'price': float(previous_close['price']), 'date': str(previous_close.get('date', ''))}
    result['content_hash'] = hashlib.sha256(json.dumps({k: v for k, v in result.items() if k != 'updated_at'}, sort_keys=True).encode()).hexdigest()
    return result


def publish(store, pack):
    store.root.child('intraday_charts').child(pack['date']).child(pack['symbol']).set(pack)


def publish_cached(store, data, *, now=None):
    """Reuse verified post-close minute bars. Never log in to a broker."""
    now = now or datetime.now(TPE)
    counts = {'published': 0, 'unchanged': 0, 'missing': 0}
    for day, symbol in records(store.live.get() or {}):
        path = Path(data) / 'bars' / day / (symbol + '.json')
        if not path.exists():
            counts['missing'] += 1; continue
        source = json.loads(path.read_text())
        if source.get('date') != day or source.get('symbol') != symbol:
            raise ValueError('cache_identity_mismatch')
        pack = payload(symbol, day, source.get('bars', []), now=now, previous_close=source.get('previous_close'))
        if not pack:
            counts['missing'] += 1; continue
        receipt = Path(data) / 'chart-feed-receipts' / day / (symbol + '.json')
        if receipt.exists() and json.loads(receipt.read_text()).get('content_hash') == pack['content_hash']:
            counts['unchanged'] += 1; continue
        publish(store, pack)
        receipt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = receipt.with_suffix('.tmp'); temp.write_text(json.dumps({'content_hash': pack['content_hash']})); temp.chmod(0o600); temp.replace(receipt)
        counts['published'] += 1
    return counts


class ChartPublisher:
    """A bounded background reader of the engine's existing minute-bar book."""
    def __init__(self, store, book, interval=15):
        self.store, self.book, self.interval = store, book, interval
        self.stopped = threading.Event(); self.hashes = {}
        self.thread = threading.Thread(target=self._run, name='public-trade-charts', daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()

    def once(self, now=None):
        now = now or datetime.now(TPE)
        wanted = records(self.store.live.get() or {})
        for day, symbol in wanted:
            if day != now.date().isoformat() or self.stopped.is_set():
                continue
            with self.book._lock:
                completed = list(self.book.completed_1m.get(symbol, []))
                forming = self.book.current_1m.get(symbol)
                rows = [dict(time=b.start.isoformat(), open=b.open, high=b.high, low=b.low, close=b.close,
                             volume=b.volume, forming=b is forming) for b in completed + ([forming] if forming else [])]
            pack = payload(symbol, day, rows, now=now)
            if pack and self.hashes.get((day, symbol)) != pack['content_hash']:
                publish(self.store, pack)
                self.hashes[day, symbol] = pack['content_hash']

    def _run(self):
        while not self.stopped.wait(self.interval):
            try:
                self.once()
            except Exception as exc:
                # Display-only failure must never stop the strategy or expose SDK errors.
                print('[CHART FEED]', type(exc).__name__, flush=True)
