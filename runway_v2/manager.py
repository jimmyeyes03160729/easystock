"""Runway V2: 獨立部位與風控管理器
核心風控機制：
1. 結構性停損 (約 1.5%)，不被小跳檔雜訊洗出場。
2. 分批停利：獲利達到 +1.5% 時先平倉 50% 鎖利，剩餘部位成本設保本。
3. 移動停利：獲利達 +2.0% 啟動，拉回 0.8% 出場，給足波段奔馳空間。
4. 12:55 收盤前全數平倉，不留倉。
"""
from __future__ import annotations
import math
import uuid
from datetime import datetime
from pathlib import Path
from .config import (
    FEE_RATE,
    TAX_RATE,
    DEFAULT_POSITION_AMOUNT,
    MAX_CONCURRENT_POSITIONS,
    STOP_LOSS_PCT,
    TAKE_PROFIT_HALF_PCT,
    TRAILING_TRIGGER_PCT,
    TRAILING_PULLBACK_PCT,
)
from .ledger import record_entry, record_exit, init_db


def calculate_costs(buy_price: float, sell_price: float, shares: int) -> tuple[float, float, float]:
    """計算 (手續費, 證交稅, 總成本)"""
    buy_amount = buy_price * shares
    sell_amount = sell_price * shares
    fee = math.floor(buy_amount * FEE_RATE) + math.floor(sell_amount * FEE_RATE)
    tax = math.floor(sell_amount * TAX_RATE)
    return float(fee), float(tax), float(fee + tax)


class PositionV2:
    def __init__(
        self,
        trade_id: str,
        symbol: str,
        name: str,
        entry_price: float,
        shares: int,
        entry_time: str,
        signal_type: str,
        score: float,
        reasons: list[str],
        initial_stop_price: float,
    ):
        self.trade_id = trade_id
        self.symbol = symbol
        self.name = name
        self.entry_price = entry_price
        self.shares = shares
        self.initial_shares = shares
        self.entry_time = entry_time
        self.signal_type = signal_type
        self.score = score
        self.reasons = reasons

        self.stop_price = initial_stop_price
        self.highest_price = entry_price
        self.current_price = entry_price
        self.half_closed = False
        self.trailing_active = False


class PositionManagerV2:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path
        self.positions: dict[str, PositionV2] = {}
        init_db(self.db_path)

    def can_open_new(self) -> bool:
        return len(self.positions) < MAX_CONCURRENT_POSITIONS

    def open_position(
        self,
        symbol: str,
        name: str,
        price: float,
        dt_str: str,
        signal_type: str,
        score: float,
        reasons: list[str],
        stop_price: float | None = None,
    ) -> PositionV2 | None:
        if not self.can_open_new() or symbol in self.positions:
            return None

        # 計算張數：依設定金額買進整張 (1000股)
        shares = max(1000, int(DEFAULT_POSITION_AMOUNT // (price * 1000)) * 1000)
        trade_id = f"V2-{symbol}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"
        init_stop = stop_price if stop_price is not None else price * (1.0 - STOP_LOSS_PCT)

        pos = PositionV2(
            trade_id=trade_id,
            symbol=symbol,
            name=name,
            entry_price=price,
            shares=shares,
            entry_time=dt_str,
            signal_type=signal_type,
            score=score,
            reasons=reasons,
            initial_stop_price=init_stop,
        )
        self.positions[symbol] = pos

        record_entry(
            trade_id=trade_id,
            symbol=symbol,
            name=name,
            entry_time=dt_str,
            entry_price=price,
            shares=shares,
            signal_type=signal_type,
            score=score,
            reasons=reasons,
            db_path=self.db_path,
        )
        return pos

    def update_price(
        self,
        symbol: str,
        current_price: float,
        dt_str: str,
        force_exit: bool = False,
    ) -> dict | None:
        pos = self.positions.get(symbol)
        if not pos:
            return None

        pos.current_price = current_price
        if current_price > pos.highest_price:
            pos.highest_price = current_price

        # 1. 強制平倉 (12:55)
        if force_exit:
            return self._close(pos, current_price, dt_str, "收盤強制平倉", pos.shares)

        # 2. 停損判斷
        if current_price <= pos.stop_price:
            exit_reason = "保本出場" if pos.half_closed else "停損出場"
            return self._close(pos, current_price, dt_str, exit_reason, pos.shares)

        # 3. 分批停利 (+1.5% 先出一半鎖利，剩下保本)
        return_pct = (current_price / pos.entry_price - 1.0)
        if not pos.half_closed and return_pct >= TAKE_PROFIT_HALF_PCT:
            half_shares = pos.shares // 2
            if half_shares >= 1000:
                pos.half_closed = True
                pos.shares -= half_shares
                # 剩餘部位防守拉高到進場價 (保本)
                pos.stop_price = max(pos.stop_price, pos.entry_price)
                event = self._close(
                    pos, current_price, dt_str, "分批停利 50%", half_shares, is_partial=True
                )
                return event

        # 4. 移動停利 (+2.0% 啟動，自高點拉回 0.8% 出場)
        if return_pct >= TRAILING_TRIGGER_PCT:
            pos.trailing_active = True

        if pos.trailing_active:
            pullback_pct = (pos.highest_price - current_price) / pos.highest_price
            if pullback_pct >= TRAILING_PULLBACK_PCT:
                return self._close(pos, current_price, dt_str, "移動停利出場", pos.shares)

        return None

    def _close(
        self,
        pos: PositionV2,
        exit_price: float,
        dt_str: str,
        reason: str,
        shares: int,
        is_partial: bool = False,
    ) -> dict:
        gross_pnl = (exit_price - pos.entry_price) * shares
        fee, tax, _ = calculate_costs(pos.entry_price, exit_price, shares)
        net_pnl = gross_pnl - (fee + tax)
        return_pct = (exit_price / pos.entry_price - 1.0) * 100.0

        if not is_partial:
            self.positions.pop(pos.symbol, None)

        record_exit(
            trade_id=pos.trade_id,
            exit_time=dt_str,
            exit_price=exit_price,
            exit_reason=reason,
            gross_pnl=gross_pnl,
            fee=fee,
            tax=tax,
            net_pnl=net_pnl,
            return_pct=return_pct,
            db_path=self.db_path,
        )

        return {
            "trade_id": pos.trade_id,
            "symbol": pos.symbol,
            "name": pos.name,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "shares": shares,
            "exit_time": dt_str,
            "reason": reason,
            "net_pnl": round(net_pnl, 0),
            "return_pct": round(return_pct, 2),
            "is_partial": is_partial,
        }
