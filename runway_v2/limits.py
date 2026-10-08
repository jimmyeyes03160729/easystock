"""Runway V2: 每日買進額度與虧損熔斷 (盤中即時執行)
1. 每日買進額度：只計買進成交額，新部位會使今日累計超過 DAILY_MAX_BUY_AMOUNT 時跳過該筆。
2. 虧損熔斷：今日已實現淨損益 <= -DAILY_MAX_LOSS_CIRCUIT_BREAKER 後停止所有新進場。
計數一律由 ledger (get_daily_trades) 重建：每日第一次使用、服務重啟後、每次開倉或平倉寫入後，
因此重啟不會把今日額度或熔斷歸零。
"""
from __future__ import annotations
from pathlib import Path
from .config import (
    DAILY_MAX_BUY_AMOUNT,
    DAILY_MAX_LOSS_CIRCUIT_BREAKER,
    DEFAULT_POSITION_AMOUNT,
)
from .ledger import get_daily_trades

BUY_CAP = "daily_buy_cap"
LOSS_CIRCUIT_BREAKER = "daily_loss_circuit_breaker"


def planned_shares(price: float) -> int:
    """與 PositionManagerV2.open_position 相同的股數算法。
    manager.py 受 META_B_FILTER_V1 預註冊釘選 blob hash，故在此複製而不改動它；
    tests/test_runway_v2_live_limits.py 驗證兩者一致。
    """
    return max(1000, int(DEFAULT_POSITION_AMOUNT // (price * 1000)) * 1000)


class DailyLimits:
    def __init__(
        self,
        db_path: Path | str | None = None,
        max_buy_amount: float = DAILY_MAX_BUY_AMOUNT,
        max_loss: float = DAILY_MAX_LOSS_CIRCUIT_BREAKER,
    ):
        self.db_path = db_path
        self.max_buy_amount = float(max_buy_amount)
        self.max_loss = float(max_loss)
        self.day: str | None = None
        self.buy_amount = 0.0
        self.realized_net_pnl = 0.0
        self._logged: set[tuple[str, str]] = set()

    def roll_to(self, day: str) -> None:
        """切換到交易日 day；換日或重啟後第一次呼叫時由 ledger 重建計數。"""
        if day != self.day:
            self.day = day
            self._logged.clear()
            self.refresh()

    def refresh(self) -> None:
        """由 ledger 重新計算今日買進額與已實現淨損益 (以進場日歸屬)。"""
        if self.day is None:
            return
        trades = get_daily_trades(self.day, self.db_path)
        self.buy_amount = round(
            sum(float(t["entry_price"]) * int(t["shares"]) for t in trades), 2
        )
        self.realized_net_pnl = round(
            sum(float(t["net_pnl"]) for t in trades if t.get("net_pnl") is not None), 2
        )

    def block_reason(self, notional: float) -> str | None:
        if self.realized_net_pnl <= -self.max_loss:
            return LOSS_CIRCUIT_BREAKER
        if round(self.buy_amount + notional, 2) > self.max_buy_amount:
            return BUY_CAP
        return None

    def first_block_today(self, symbol: str, reason: str) -> bool:
        """同一檔同一原因每日只記一次 log，避免訊號持續時每輪雷達洗版。"""
        key = (symbol, reason)
        if key in self._logged:
            return False
        self._logged.add(key)
        return True
