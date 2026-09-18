#!/usr/bin/env python3
"""
Paper Trade Position & Capital Manager
動態權益部位計算與結算模組
"""

from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta

try:
    from easystock_admin.store import (
        read_paper_trade_settings,
        record_paper_trade_settlement,
        log_paper_trade_event,
        set_paper_position,
        clear_paper_position
    )
except ImportError:
    from vm_runtime.easystock_admin.store import (
        read_paper_trade_settings,
        record_paper_trade_settlement,
        log_paper_trade_event,
        set_paper_position,
        clear_paper_position
    )

TPE = timezone(timedelta(hours=8))
BROKER_FEE_RATE = 0.001425 * 0.28  # 預設 28 折手續費
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

    def try_buy(self, symbol: str, name: str, price: float) -> int:
        """嘗試開倉，若無法買進則記錄具體略過原因"""
        self.refresh()
        if not self.is_active():
            log_paper_trade_event(symbol, name, price, "略過", "後台模擬當沖處於【暫停】狀態")
            return 0

        capital = self.current_capital()
        # 單檔標的最多投入當日可用資金的 80% (保留保證金緩衝)
        max_budget = capital * 0.8
        one_lot_cost = price * 1000

        if one_lot_cost > max_budget:
            reason = f"資金不足：買進 1 張需 {one_lot_cost:,.0f} 元，已超過單檔上限 {max_budget:,.0f} 元 (總資金 {capital:,.0f} 元)"
            log_paper_trade_event(symbol, name, price, "略過", reason)
            print(f"[Paper Trade] {symbol} {name} 略過: {reason}")
            return 0

        shares = math.floor(max_budget / one_lot_cost) * 1000
        if shares > 0:
            set_paper_position(symbol, name, price, shares)
            log_paper_trade_event(symbol, name, price, "買進", f"成功買進 {shares} 股，花費約 {price * shares:,.0f} 元")
            print(f"[Paper Trade] 成功開倉 {symbol} {name} {shares} 股，價格 {price}")
            return shares

        log_paper_trade_event(symbol, name, price, "略過", "部位計算為 0 股，取消委託")
        return 0

    def close_and_settle(self, symbol: str, name: str, entry_price: float, exit_price: float, shares: int, exit_reason: str = "平倉出場") -> dict:
        """平倉出場並結算損益至 SQLite"""
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
        clear_paper_position(symbol)
        log_paper_trade_event(symbol, name, exit_price, "賣出", f"{exit_reason}：淨損益 {net_pnl:+,.0f} 元 (扣手續費與稅 {costs} 元)")

        record_paper_trade_settlement(
            date_str=today_str,
            start_bal=start_cap,
            end_bal=end_cap,
            net_pnl=net_pnl,
            symbols_str=f"{symbol} {name}",
            costs=costs,
            trades_count=1
        )
        self.refresh()
        print(f"[Paper Settle] {symbol} {name} 平倉完成 | 淨損益: {net_pnl:+.0f} | 最新本金: {end_cap:,.0f}")
        return {
            "date": today_str,
            "start_balance": start_cap,
            "end_balance": end_cap,
            "net_pnl": net_pnl,
            "costs": costs
        }
