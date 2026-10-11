import sys
from unittest.mock import Mock, MagicMock

if 'shioaji' not in sys.modules:
    sys.modules['shioaji'] = MagicMock()
if 'firebase_admin' not in sys.modules:
    sys.modules['firebase_admin'] = MagicMock()

import pytest
from strategy_engine import evaluate_daytrade


def test_hard_vetoes_and_soft_penalties_separation():
    # 建立 10 根 5 分 K
    rows5 = [
        {"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.0, "volume": 1000}
        for _ in range(10)
    ]
    rows15 = [
        {"open": 100.0, "high": 102.0, "low": 99.5, "close": 101.0, "volume": 3000}
        for _ in range(3)
    ]

    # 情境 1: 跌破 VWAP (致命硬否決)
    stock_under_vwap = {"buy_ratio_60s": 0.55}
    # 讓最後一根 close 大幅低於均價 (例如 90)
    rows5_under = list(rows5[:-1]) + [{"open": 98.0, "high": 99.0, "low": 89.0, "close": 90.0, "volume": 1000}]
    res1 = evaluate_daytrade(rows5_under, rows15, stock=stock_under_vwap, market_level="GREEN")
    assert "跌破VWAP" in res1["hard_vetoes"]
    assert "跌破VWAP" in res1["vetoes"]
    assert res1["eligible"] is False

    # 情境 2: 站穩 VWAP，但買盤比率僅 45% (非致命軟性扣分，不應成為 hard_veto)
    stock_soft = {"buy_ratio_60s": 0.45}
    # 讓最後一根 close 站上 VWAP (例如 101.5)
    rows5_above = list(rows5[:-1]) + [{"open": 100.5, "high": 102.0, "low": 100.2, "close": 101.8, "volume": 2000}]
    res2 = evaluate_daytrade(rows5_above, rows15, stock=stock_soft, market_level="GREEN")
    assert "跌破VWAP" not in res2["hard_vetoes"]
    assert "跌破VWAP" not in res2["vetoes"]
    assert "主動買盤偏低(40-50%)" in res2["soft_penalties"]
    assert res2["penalty_score"] >= 6
    assert res2["daytrade_score"] == max(0, res2["raw_daytrade_score"] - res2["penalty_score"])


def test_reject_diagnostics_breakdown():
    from intraday_live import IntradayLiveEngine

    runner = IntradayLiveEngine.__new__(IntradayLiveEngine)
    import threading
    runner._lock = threading.RLock()
    runner._entry_reject_counts = {}
    runner._entry_reject_veto_counts = {}
    runner._entry_soft_penalty_counts = {}
    runner._entry_evaluation_count = 0
    runner._entry_reject_diagnostics = {}
    runner._entry_reject_last = {}
    runner._entry_reject_summary_at = 0.0
    runner._entry_reject_summary_logged = {}
    runner.store = Mock()
    runner.store.db = None

    # 模擬數次拒絕
    runner._entry_reject("2330", "strategy_veto", "veto=跌破VWAP,大盤開高走低出貨盤")
    runner._entry_reject("2454", "strategy_veto", "veto=跌破VWAP")
    runner._entry_reject("2317", "outside_entry_window", "08:50:00")
    runner._entry_reject("3008", "model_rejected", "probability=0.52 threshold=0.60")

    assert runner._entry_evaluation_count == 4
    assert runner._entry_reject_counts["strategy_veto"] == 2
    assert runner._entry_reject_counts["outside_entry_window"] == 1
    assert runner._entry_reject_counts["model_rejected"] == 1
    assert runner._entry_reject_veto_counts["veto:跌破VWAP"] == 2
    assert runner._entry_reject_veto_counts["veto:大盤開高走低出貨盤"] == 1

    # 執行診斷統計輸出
    runner.log_entry_reject_summary(force=True)
    diag = runner._entry_reject_diagnostics
    assert diag["total_evaluations"] == 4
    assert len(diag["top_bottlenecks"]) > 0
    # Top 1 瓶頸應為 veto:跌破VWAP (2次)
    assert diag["top_bottlenecks"][0]["reason"] == "veto:跌破VWAP"
    assert diag["top_bottlenecks"][0]["count"] == 2
