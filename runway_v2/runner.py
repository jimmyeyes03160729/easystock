"""Runway V2: 跑道 B 即時運行控制器 (Tap / Sidecar)
負責在盤中行情事件觸發時，以非侵入方式平行評估高勝率動能訊號。
"""
from __future__ import annotations
import threading
from datetime import datetime
from typing import Any
from pathlib import Path
from .config import (
    RUNWAY_V2_ENABLED,
    ENTRY_START_TIME,
    ENTRY_CUTOFF_TIME,
    FORCE_EXIT_TIME,
    DB_PATH,
    MAX_CONCURRENT_POSITIONS,
    DEFAULT_POSITION_AMOUNT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_HALF_PCT,
    TRAILING_TRIGGER_PCT,
    TRAILING_PULLBACK_PCT,
    MAX_GAIN_PCT,
)
from .strategy import evaluate_signal
from .manager import PositionManagerV2
from .notifier import notify_entry, notify_exit
from .ledger import (
    delete_position_state,
    get_daily_trades,
    init_position_state,
    save_position_state,
)
from .restore import restore_positions
from .limits import DailyLimits, planned_shares
from .orderbook import OrderBookTracker

# 盤中部位狀態 sidecar：停損/最高價/旗標/股數一變就寫；只有現價變動時每檔最多每 N 秒寫一次
STATE_PRICE_PERSIST_SECONDS = 5.0


class RunwayV2Runner:
    def __init__(self, db_path: Path | str | None = None):
        self.enabled = RUNWAY_V2_ENABLED
        self.db_path = db_path or DB_PATH
        self.manager = PositionManagerV2(db_path=self.db_path)
        self.limits = DailyLimits(db_path=self.db_path)
        self.orderbook_tracker = OrderBookTracker()
        self.subscribe_bidask_fn: Any = None
        self.subscribed_bidask_symbols: set[str] = set()
        self.lock = threading.Lock()
        self.last_eval_time = ""
        init_position_state(self.db_path)
        self._restored_day: str | None = None
        self._persisted: dict[str, tuple[tuple, float, datetime]] = {}
        print(
            f"[RUNWAY_V2_INIT] buy_cap={self.limits.max_buy_amount:,.0f} "
            f"loss_limit={self.limits.max_loss:,.0f} "
            f"max_pos={MAX_CONCURRENT_POSITIONS} pos_amount={DEFAULT_POSITION_AMOUNT:,.0f} "
            f"tp_half=+{TAKE_PROFIT_HALF_PCT*100:.1f}% trailing=+{TRAILING_TRIGGER_PCT*100:.1f}% "
            f"pullback=-{TRAILING_PULLBACK_PCT*100:.1f}% sl=-{STOP_LOSS_PCT*100:.1f}% max_gain=+{MAX_GAIN_PCT:.1f}%"
        )

    def _ensure_restored(self, current_dt: datetime) -> None:
        """每個交易日第一次事件 (含重啟後第一次) 由 ledger 還原今日仍在手的部位；呼叫端須持有 lock。"""
        day = current_dt.strftime("%Y-%m-%d")
        if day == self._restored_day:
            return
        self._restored_day = day
        try:
            result = restore_positions(
                self.manager, day, current_dt.isoformat(), db_path=self.db_path
            )
        except Exception as exc:
            print(f"[RUNWAY_V2_RESTORE] failed day={day} error={type(exc).__name__}: {exc}")
            return
        self._persisted.clear()
        if result["restored"] or result["orphaned"]:
            self.sync_to_firebase()

    def _persist_state(self, symbol: str, current_dt: datetime, force: bool = False) -> None:
        pos = self.manager.positions.get(symbol)
        if pos is None:
            return
        key = (pos.shares, round(pos.stop_price, 4), pos.highest_price, pos.half_closed, pos.trailing_active)
        last = self._persisted.get(pos.trade_id)
        if not force and last is not None:
            last_key, last_price, last_dt = last
            if key == last_key:
                if pos.current_price == last_price:
                    return
                try:
                    if (current_dt - last_dt).total_seconds() < STATE_PRICE_PERSIST_SECONDS:
                        return
                except TypeError:
                    pass
        try:
            save_position_state(
                trade_id=pos.trade_id,
                symbol=pos.symbol,
                shares=pos.shares,
                stop_price=pos.stop_price,
                highest_price=pos.highest_price,
                current_price=pos.current_price,
                half_closed=pos.half_closed,
                trailing_active=pos.trailing_active,
                price_time=current_dt.isoformat(),
                db_path=self.db_path,
            )
            self._persisted[pos.trade_id] = (key, pos.current_price, current_dt)
        except Exception as exc:
            print(f"[RUNWAY_V2_STATE_WARN] {symbol} {type(exc).__name__}: {exc}")

    def _after_exit(self, exit_event: dict, current_dt: datetime) -> None:
        if exit_event.get("is_partial"):
            self._persist_state(exit_event["symbol"], current_dt, force=True)
            return
        self._persisted.pop(exit_event["trade_id"], None)
        try:
            delete_position_state(exit_event["trade_id"], self.db_path)
        except Exception as exc:
            print(f"[RUNWAY_V2_STATE_WARN] {exit_event['symbol']} {type(exc).__name__}: {exc}")

    def on_radar_update(
        self,
        qualified_rows: list[dict],
        kbars_cache: Any,  # 提供 rows5(symbol)
        previous_closes: dict[str, float],
        current_dt: datetime,
    ) -> None:
        """當雷達產出活躍清單時，進行跑道 B 進場評估。"""
        if not self.enabled:
            return

        time_str = current_dt.strftime("%H:%M:%S")

        with self.lock:
            self._ensure_restored(current_dt)

            # 1. 檢查是否在進場時間窗口內 (09:05:00 ~ 12:30:00)
            if not (ENTRY_START_TIME <= time_str <= ENTRY_CUTOFF_TIME):
                return

            if not self.manager.can_open_new():
                return

            # 每日額度與熔斷計數 (換日或重啟後由 ledger 重建)
            self.limits.roll_to(current_dt.strftime("%Y-%m-%d"))

            # 2. 依動能評估合格清單
            for row in qualified_rows:
                if not self.manager.can_open_new():
                    break

                symbol = str(row.get("symbol") or "").strip()
                if not symbol or symbol in self.manager.positions:
                    continue

                name = str(row.get("name") or symbol).strip()
                current_price = float(row.get("close") or row.get("price") or 0.0)
                prev_close = float(previous_closes.get(symbol) or 0.0)
                if current_price <= 0 or prev_close <= 0:
                    continue

                rows5 = []
                if hasattr(kbars_cache, "rows5"):
                    try:
                        rows5 = kbars_cache.rows5(symbol) or []
                    except Exception:
                        rows5 = []

                if self.subscribe_bidask_fn and symbol not in self.subscribed_bidask_symbols:
                    try:
                        self.subscribe_bidask_fn(symbol)
                        self.subscribed_bidask_symbols.add(symbol)
                    except Exception:
                        pass

                ob = self.orderbook_tracker.get(symbol)
                signal = evaluate_signal(
                    symbol=symbol,
                    name=name,
                    current_price=current_price,
                    previous_close=prev_close,
                    current_time_str=time_str,
                    kbars5=rows5,
                    radar_metrics=row,
                    orderbook=ob,
                )

                if signal:
                    # 每日買進額度 100 萬 (只計買進) 與已實現虧損 6,000 熔斷
                    notional = planned_shares(current_price) * current_price
                    block = self.limits.block_reason(notional)
                    if block:
                        if self.limits.first_block_today(symbol, block):
                            print(
                                f"[RUNWAY_V2_LIMIT] skip {symbol} {name} type={signal['signal_type']} "
                                f"reason={block} buy_used={self.limits.buy_amount:,.0f} "
                                f"new={notional:,.0f} buy_cap={self.limits.max_buy_amount:,.0f} "
                                f"realized_net={self.limits.realized_net_pnl:,.0f} "
                                f"loss_limit={-self.limits.max_loss:,.0f}"
                            )
                        continue

                    pos = self.manager.open_position(
                        symbol=symbol,
                        name=name,
                        price=current_price,
                        dt_str=current_dt.isoformat(),
                        signal_type=signal["signal_type"],
                        score=signal["score"],
                        reasons=signal["reasons"],
                        stop_price=signal.get("stop_price"),
                    )
                    if pos:
                        self.limits.refresh()
                        self._persist_state(symbol, current_dt, force=True)
                        print(
                            f"[RUNWAY_V2_ENTRY] {symbol} {name} price={current_price} "
                            f"type={signal['signal_type']} score={signal['score']}"
                        )
                        notify_entry(
                            symbol=symbol,
                            name=name,
                            price=current_price,
                            shares=pos.shares,
                            signal_type=signal["signal_type"],
                            score=signal["score"],
                            reasons=signal["reasons"],
                        )
                        self.sync_to_firebase()

    def on_tick(self, symbol: str, price: float, current_dt: datetime) -> None:
        """即時 Tick 更新：檢查現有持倉的停利、停損與收盤強制平倉。"""
        if not self.enabled:
            return

        time_str = current_dt.strftime("%H:%M:%S")
        is_force_exit = time_str >= FORCE_EXIT_TIME

        with self.lock:
            self._ensure_restored(current_dt)

            if symbol not in self.manager.positions and not is_force_exit:
                return

            # 如果是強制出場時間，對所有現有持倉平倉
            # 每檔以自己的最新成交價出場 (觸發檔用本筆 tick，其餘用 pos.current_price)，不可用盤中最高價
            if is_force_exit:
                for sym, pos in list(self.manager.positions.items()):
                    exit_event = self.manager.update_price(
                        symbol=sym,
                        current_price=price if sym == symbol else pos.current_price,
                        dt_str=current_dt.isoformat(),
                        force_exit=True,
                    )
                    if exit_event:
                        self.limits.refresh()
                        self._after_exit(exit_event, current_dt)
                        print(f"[RUNWAY_V2_EXIT] {exit_event}")
                        notify_exit(
                            symbol=exit_event["symbol"],
                            name=exit_event["name"],
                            entry_price=exit_event["entry_price"],
                            exit_price=exit_event["exit_price"],
                            shares=exit_event["shares"],
                            net_pnl=exit_event["net_pnl"],
                            return_pct=exit_event["return_pct"],
                            reason=exit_event["reason"],
                        )
                self.sync_to_firebase()
                return

            # 正常單一股票價格更新
            exit_event = self.manager.update_price(
                symbol=symbol,
                current_price=price,
                dt_str=current_dt.isoformat(),
                force_exit=False,
            )
            if exit_event:
                self.limits.refresh()
                self._after_exit(exit_event, current_dt)
                print(f"[RUNWAY_V2_EXIT] {exit_event}")
                notify_exit(
                    symbol=exit_event["symbol"],
                    name=exit_event["name"],
                    entry_price=exit_event["entry_price"],
                    exit_price=exit_event["exit_price"],
                    shares=exit_event["shares"],
                    net_pnl=exit_event["net_pnl"],
                    return_pct=exit_event["return_pct"],
                    reason=exit_event["reason"],
                )
                self.sync_to_firebase()
            else:
                self._persist_state(symbol, current_dt)

    def export_snapshot(self) -> dict:
        today_str = datetime.now().strftime("%Y-%m-%d")
        open_positions = {}
        for sym, pos in self.manager.positions.items():
            open_positions[sym] = {
                "trade_id": pos.trade_id,
                "symbol": pos.symbol,
                "name": pos.name,
                "entry_time": pos.entry_time,
                "entry_price": pos.entry_price,
                "current_price": getattr(pos, "current_price", pos.highest_price),
                "highest_price": pos.highest_price,
                "stop_price": pos.stop_price,
                "shares": pos.shares,
                "signal_type": pos.signal_type,
                "score": pos.score,
                "reasons": pos.reasons,
                "half_closed": pos.half_closed,
            }

        all_today = get_daily_trades(today_str, self.db_path)
        closed_trades = {
            t["trade_id"]: {
                "trade_id": t["trade_id"],
                "symbol": t["symbol"],
                "name": t["name"],
                "entry_time": t["entry_time"],
                "entry_price": t["entry_price"],
                "exit_time": t["exit_time"],
                "exit_price": t["exit_price"],
                "exit_reason": t["exit_reason"],
                "shares": t["shares"],
                "net_pnl": t["net_pnl"],
                "return_pct": t["return_pct"],
                "signal_type": t["signal_type"],
                "score": t["score"],
                "reasons": t["reasons"],
            }
            for t in all_today
            if t.get("status") == "CLOSED"
        }

        return {
            "last_update_at": datetime.now().isoformat(),
            "open_positions": open_positions,
            "closed_trades": closed_trades,
            "session": "daytrade" if datetime.now().strftime("%H:%M:%S") < "13:00:00" else "closed",
        }

    def sync_to_firebase(self) -> None:
        try:
            import firebase_admin
            from firebase_admin import db
            if firebase_admin._apps:
                snapshot = self.export_snapshot()
                db.reference("/market_data/intraday_live/runway_v2").set(snapshot)
        except Exception:
            pass

    def register_bidask_subscriber(self, fn: Any) -> None:
        """註冊向 Shioaji 訂閱 BidAsk 的回呼函式 fn(symbol)"""
        self.subscribe_bidask_fn = fn

    def on_bidask(self, symbol: str, quote: Any) -> None:
        """接收 Shioaji BidAsk 即時推播並更新五檔快照"""
        if not self.enabled:
            return
        self.orderbook_tracker.update(symbol, quote)


_INSTANCE: RunwayV2Runner | None = None
_INIT_LOCK = threading.Lock()


def get_runway_v2() -> RunwayV2Runner:
    global _INSTANCE
    if _INSTANCE is None:
        with _INIT_LOCK:
            if _INSTANCE is None:
                _INSTANCE = RunwayV2Runner()
    return _INSTANCE
