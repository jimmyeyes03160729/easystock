"""Runway V2: 跑道 B 即時運行控制器 (Tap / Sidecar)
負責在盤中行情事件觸發時，以非侵入方式平行評估高勝率動能訊號。
"""
from __future__ import annotations
import threading
from datetime import datetime
from pathlib import Path
from .config import (
    RUNWAY_V2_ENABLED,
    ENTRY_START_TIME,
    ENTRY_CUTOFF_TIME,
    FORCE_EXIT_TIME,
    DB_PATH,
)
from .strategy import evaluate_signal
from .manager import PositionManagerV2
from .notifier import notify_entry, notify_exit


class RunwayV2Runner:
    def __init__(self, db_path: Path | str | None = None):
        self.enabled = RUNWAY_V2_ENABLED
        self.db_path = db_path or DB_PATH
        self.manager = PositionManagerV2(db_path=self.db_path)
        self.lock = threading.Lock()
        self.last_eval_time = ""

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
            # 1. 檢查是否在進場時間窗口內 (09:05:00 ~ 12:30:00)
            if not (ENTRY_START_TIME <= time_str <= ENTRY_CUTOFF_TIME):
                return

            if not self.manager.can_open_new():
                return

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

                signal = evaluate_signal(
                    symbol=symbol,
                    name=name,
                    current_price=current_price,
                    previous_close=prev_close,
                    current_time_str=time_str,
                    kbars5=rows5,
                    radar_metrics=row,
                )

                if signal:
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

    def on_tick(self, symbol: str, price: float, current_dt: datetime) -> None:
        """即時 Tick 更新：檢查現有持倉的停利、停損與收盤強制平倉。"""
        if not self.enabled:
            return

        time_str = current_dt.strftime("%H:%M:%S")
        is_force_exit = time_str >= FORCE_EXIT_TIME

        with self.lock:
            if symbol not in self.manager.positions and not is_force_exit:
                return

            # 如果是強制出場時間，對所有現有持倉平倉
            if is_force_exit:
                for sym in list(self.manager.positions.keys()):
                    exit_event = self.manager.update_price(
                        symbol=sym,
                        current_price=price if sym == symbol else self.manager.positions[sym].highest_price,
                        dt_str=current_dt.isoformat(),
                        force_exit=True,
                    )
                    if exit_event:
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
                return

            # 正常單一股票價格更新
            exit_event = self.manager.update_price(
                symbol=symbol,
                current_price=price,
                dt_str=current_dt.isoformat(),
                force_exit=False,
            )
            if exit_event:
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


_INSTANCE: RunwayV2Runner | None = None
_INIT_LOCK = threading.Lock()


def get_runway_v2() -> RunwayV2Runner:
    global _INSTANCE
    if _INSTANCE is None:
        with _INIT_LOCK:
            if _INSTANCE is None:
                _INSTANCE = RunwayV2Runner()
    return _INSTANCE
