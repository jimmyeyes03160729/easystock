"""Unit tests for Runway V2 (獨立高勝率當沖動能跑道)."""
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from runway_v2.config import (
    MIN_PRICE,
    MAX_PRICE,
    MIN_GAIN_PCT,
    MAX_GAIN_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_HALF_PCT,
)
from runway_v2.strategy import calculate_vwap, score_candidate, evaluate_signal
from runway_v2.manager import PositionManagerV2, calculate_costs
from runway_v2.ledger import init_db, get_daily_trades, get_open_trades
from runway_v2.reporter import generate_comparison_report
from runway_v2.runner import RunwayV2Runner

TPE = timezone(timedelta(hours=8))


def test_calculate_vwap():
    bars = [
        {"high": 100, "low": 98, "close": 99, "volume": 100},
        {"high": 102, "low": 99, "close": 101, "volume": 200},
    ]
    # bar 1 typical = (100+98+99)/3 = 99; value = 9900
    # bar 2 typical = (102+99+101)/3 = 100.6667; value = 20133.333
    # total val = 30033.333; total vol = 300; vwap = 100.111
    vwap = calculate_vwap(bars)
    assert vwap is not None
    assert round(vwap, 2) == 100.11


def test_score_candidate():
    radar = {
        "surge_60s": 3.5,
        "buy_ratio_60s": 0.88,
        "amount_60s": 50_000_000,
    }
    score, reasons = score_candidate(
        price=103.0,
        vwap=102.0,
        previous_close=100.0,
        radar_metrics=radar,
    )
    assert score >= 60.0
    assert len(reasons) >= 2


def test_evaluate_signal_orb():
    # 模擬 09:10 的 ORB 突破
    kbars5 = [
        {"high": 101.5, "low": 99.5, "close": 101.0, "volume": 500},
    ]
    radar = {
        "surge_60s": 2.5,
        "buy_ratio_60s": 0.80,
    }
    signal = evaluate_signal(
        symbol="2330",
        name="台積電",
        current_price=102.0,  # 突破 101.5
        previous_close=100.0,  # 漲幅 2%
        current_time_str="09:10:00",
        kbars5=kbars5,
        radar_metrics=radar,
    )
    assert signal is not None
    assert signal["signal_type"] == "ORB_BREAKOUT"
    assert signal["score"] >= 60.0
    assert signal["stop_price"] < 102.0


def test_position_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ledger.sqlite"
        manager = PositionManagerV2(db_path=db_path)

        # 1. 建立部位
        pos = manager.open_position(
            symbol="2330",
            name="台積電",
            price=100.0,
            dt_str="2026-10-08T09:10:00+08:00",
            signal_type="ORB_BREAKOUT",
            score=85.0,
            reasons=["突破早盤高點", "量能放大"],
            stop_price=98.5,
        )
        assert pos is not None
        assert pos.shares == 3000
        assert len(manager.positions) == 1
        assert len(get_open_trades(db_path)) == 1

        # 2. 價格微漲，尚未達停利
        event = manager.update_price("2330", 101.0, "2026-10-08T09:15:00+08:00")
        assert event is None
        assert pos.highest_price == 101.0

        # 3. 獲利達 +1.6% (>= 1.5%) -> 觸發分批平倉 50%
        event = manager.update_price("2330", 101.6, "2026-10-08T09:20:00+08:00")
        assert event is not None
        assert event["is_partial"] is True
        assert event["shares"] == 1500
        assert event["net_pnl"] > 0
        assert pos.half_closed is True
        assert pos.stop_price == 100.0  # 防守點拉高到成本價保本

        # 4. 回測觸及保本成本價 100.0 -> 觸發保本平倉
        event2 = manager.update_price("2330", 99.9, "2026-10-08T09:30:00+08:00")
        assert event2 is not None
        assert event2["reason"] == "保本出場"
        assert len(manager.positions) == 0


def test_trailing_stop_profit():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ledger.sqlite"
        manager = PositionManagerV2(db_path=db_path)

        pos = manager.open_position(
            symbol="2454",
            name="聯發科",
            price=1000.0,
            dt_str="2026-10-08T09:10:00+08:00",
            signal_type="ORB_BREAKOUT",
            score=88.0,
            reasons=["爆量突破"],
        )
        assert pos is not None

        # 暴衝到 +3%
        manager.update_price("2454", 1030.0, "2026-10-08T09:25:00+08:00")
        assert pos.trailing_active is True
        assert pos.highest_price == 1030.0

        # 自 1030 回檔超過 0.8% (1030 * 0.992 = 1021.76)
        exit_event = manager.update_price("2454", 1020.0, "2026-10-08T09:35:00+08:00")
        assert exit_event is not None
        assert "移動停利" in exit_event["reason"]
        assert exit_event["net_pnl"] > 0


def test_comparison_report_format():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ledger.sqlite"
        manager = PositionManagerV2(db_path=db_path)

        pos = manager.open_position(
            symbol="2330",
            name="台積電",
            price=100.0,
            dt_str="2026-10-08T09:10:00+08:00",
            signal_type="ORB_BREAKOUT",
            score=80.0,
            reasons=["動能強勁"],
        )
        manager.update_price("2330", 102.0, "2026-10-08T09:30:00+08:00")

        report = generate_comparison_report(day="2026-10-08", db_path=db_path)
        assert "【EasyStock 當沖雙跑道對照日報】" in report
        assert "跑道 A：現有 AI 模型體系" in report
        assert "跑道 B：新獨立動能跑道 V2" in report
        assert "台積電" in report
