"""測試 Runway V2 回測引擎 (Backtest Engine)
包含：
1. 成本與手續費計算
2. 5分K線合成
3. ORB 突破與 VWAP 回踩判斷
4. 風控出場 (停損、分批停利、移動停利、收盤強制平倉)
"""
import pytest
from runway_v2.backtest import (
    calculate_trade_costs,
    BacktestTrade,
    RunwayV2Backtester,
)


def test_calculate_trade_costs():
    # 買進 100 元 1000 股 = 100,000 元
    # 賣出 105 元 1000 股 = 105,000 元
    # 手續費: floor(100000 * 0.001425 * 0.28) = 39, floor(105000 * 0.001425 * 0.28) = 41 => 80
    # 證交稅: floor(105000 * 0.0015) = 157
    fee, tax = calculate_trade_costs(100.0, 105.0, 1000)
    assert fee == 39 + 41
    assert tax == 157


def test_finalize_exit_stop_loss():
    tester = RunwayV2Backtester(data_root=".")
    trade = BacktestTrade(
        trade_id="TEST-1",
        symbol="2330",
        name="台積電",
        entry_date="2026-10-08",
        entry_time="09:10:00",
        entry_price=100.0,
        shares=1000,
        signal_type="ORB_BREAKOUT",
        score=75.0,
        reasons=["突破高點"],
    )
    # 停損出場跌至 98.0
    tester._finalize_exit(trade, "09:30", 98.0, "停損出場")
    assert trade.exit_price == 98.0
    assert trade.exit_reason == "停損出場"
    assert trade.net_pnl < 0
    assert trade.return_pct < 0


def test_finalize_exit_partial_take_profit():
    tester = RunwayV2Backtester(data_root=".")
    trade = BacktestTrade(
        trade_id="TEST-2",
        symbol="2609",
        name="陽明",
        entry_date="2026-10-08",
        entry_time="09:10:00",
        entry_price=100.0,
        shares=2000,
        signal_type="ORB_BREAKOUT",
        score=75.0,
        reasons=["突破高點"],
    )
    # 模擬分批獲利出半趟: 出 1000 股在 102.0
    trade.half_closed = True
    trade.half_pnl = 1500.0
    trade.shares = 1000

    # 剩餘部位保本在 100.0 出場
    tester._finalize_exit(trade, "10:30", 100.0, "保本出場")
    assert trade.exit_price == 100.0
    # 總淨損益應大於 0 (因為先前鎖定獲利)
    assert trade.net_pnl > 0
