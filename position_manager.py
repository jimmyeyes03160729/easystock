#!/usr/bin/env python3
"""
Paper Trade Position & Capital Manager
動態權益部位計算與結算模組 (整合本機 SQLite Admin State)
"""

from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta
from vm_runtime.easystock_admin.store import (
    read_paper_trade_settings,
    record_paper_trade_settlement
)

TPE = timezone(timedelta(hours=8))

# 交易成本參數
BROKER_FEE_RATE = 0.001425 * 0.28  # 手續費 (以 28 折計)
TAX_RATE = 0.0015                 # 現股當沖證交稅 0.15%

class PaperWallet:
    def __init__(self):
        self.state = read_paper_trade_settings()

    def refresh(self) -> dict:
        self.state = read_paper_trade_settings()
        return self.state

    def is_active(self) -> bool:
        return self.state.get("status") == "running"

    def current_capital(self) -> float:
        return float(self.state.get("current_capital") or self.state.get("initial_capital", 100000.0))

    def calculate_order_size(self, price: float) -> int:
        if not self.is_active() or price <= 0:
            return 0
        capital = self.current_capital()
        # 單筆最多投入當日可用資金的 80% (保留防守保證金緩衝)
        allocable = capital * 0.8
        shares = math.floor(allocable / price)
        if shares >= 1000:
            shares = (shares // 1000) * 1000
        return max(0, shares)

    def close_and_settle(self, symbol: str, entry_price: float, exit_price: float, shares: int) -> dict:
        start_cap = self.current_capital()
        buy_amount = entry_price * shares
        sell_amount = exit_price * shares

        buy_fee = max(20, round(buy_amount * BROKER_FEE_RATE))
        sell_fee = max(20, round(sell_amount * BROKER_FEE_RATE))
        tax = round(sell_amount * TAX_RATE)
        costs = buy_fee + sell_fee + tax

        gross_pnl = sell_amount - buy_amount
        net_pnl = round(gross_pnl - costs, 2)
        end_cap = round(start_cap + net_pnl, 2)

        today_str = datetime.now(TPE).strftime('%Y-%m-%d')
        record_paper_trade_settlement(
            date_str=today_str,
            start_bal=start_cap,
            end_bal=end_cap,
            net_pnl=net_pnl,
            symbols_str=symbol,
            costs=costs,
            trades_count=1
        )
        self.refresh()
        print(f"[Paper Settle] {symbol} 買 {entry_price} 賣 {exit_price} ({shares}股) | 淨損益: {net_pnl:+.0f} | 結餘: {end_cap:,.0f}")
        return {
            "date": today_str,
            "start_balance": start_cap,
            "end_balance": end_cap,
            "net_pnl": net_pnl,
            "costs": costs
        }
