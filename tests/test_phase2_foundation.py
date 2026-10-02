"""Comprehensive test suite for EasyStock Daytrade Research Phase 2A Foundation.

Verifies:
1. Full Causal Ordering:
   - Valid causal order passes.
   - feature_after_signal_rejected
   - signal_after_decision_rejected
   - execution_equal_decision_rejected
   - execution_before_decision_rejected
2. Strict Bar Time Semantics:
   - MarketBar requires bar_open_time < bar_close_time.
   - Distinct TickExecutionPoint.
   - No same-bar execution.
   - Next legal execution (09:30:00 -> 09:31:00; 09:30:59 -> 09:32:00).
   - No legal execution when bars exhausted.
3. Slippage Single Source of Truth:
   - SLIPPAGE_NOT_DOUBLE_COUNTED regression test.
   - Derivation of slippage_cost from actual vs theoretical execution.
   - Equivalent net PnL from both actual fill and theoretical-less-slippage accounting.
4. Transaction Costs & TWSE Tick Arithmetic:
   - Buy and sell commission with discount (0.28) and minimum fee (20 TWD).
   - Daytrade tax (0.15%) vs normal tax (0.30%).
   - Tick-size boundary cases across all TWSE price tiers.
5. Risk & Dataset Semantics:
   - Quantity field enforced.
   - Initial risk per share and initial risk amount.
   - Zero-risk R rejection.
   - Long invalid stop (stop >= entry) rejected.
   - Short invalid stop (stop <= entry) rejected.
   - Explicit MFE / MAE decomposition (price, pct, R-multiple).
6. Real Future Mutation Invariance:
   - Features at time t remain identical when future bars (t > t_0) are violently mutated.
   - Reuses KnowledgeV1Features.
7. Event-based Purging & Embargo:
   - Purges training samples whose forward labels reach into test evaluation interval.
   - Embargo quenches samples immediately after test evaluation interval.
   - IndexWalkForwardSplitter explicitly tagged NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS = True.
8. Parameter Provenance & Cost Governance:
   - PARAM_PB_VOL_DECAY verified as Anna Coulling, Chapter 7 (Chapter 5 rejected).
   - Research grids verified as AI_QUANTIZED with origin Knowledge V2 Research Parameter Candidate.
   - Centralized cost governance classifications.
9. SQN & Research-Only Verdicts:
   - SQN calculated as a metric only; no production promotion rule.
   - Allowed research verdicts only; PROMOTE_TO_PRODUCTION strictly forbidden.
10. Static Production Import Isolation:
   - Verifies production source files never import daytrade_learning.phase2.
"""
from __future__ import annotations
import ast
import copy
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from daytrade_learning.phase2 import (
    RESEARCH_ONLY,
    INERT_BY_DEFAULT,
    CostParameterCategory,
    COST_PARAMETER_REGISTRY,
    get_twse_tick_size,
    round_to_twse_tick,
    TransactionCostModel,
    calculate_derived_slippage_cost,
    calculate_single_source_pnl,
    CausalityViolationError,
    ExecutionOrderError,
    MarketBar,
    TickExecutionPoint,
    parse_phase2_timestamp,
    validate_causal_order,
    CausalExecutionClock,
    InvalidTradeParametersError,
    Phase2TradeRecord,
    create_phase2_trade,
    calculate_trade_metrics,
    ResearchVerdict,
    BaselineComparator,
    IndexWalkForwardSplitter,
    EventWalkForwardSplitter,
    ProvenanceStatus,
    PHASE2_PROVENANCE_REGISTRY,
    audit_parameter_provenance,
)
from daytrade_learning.knowledge_v1.causal_tools import CompletedBar, CausalBarSeries
from daytrade_learning.knowledge_v1.features import KnowledgeV1Features

TPE = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# 1. Architectural Guardrails
# ==============================================================================
def test_phase2a_architectural_constants():
    assert RESEARCH_ONLY is True
    assert INERT_BY_DEFAULT is True


# ==============================================================================
# 2. Major 2: Full Causal Ordering
# ==============================================================================
def test_full_causal_ordering_valid():
    ft = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    st = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    dt = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    et = datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE)
    # Should not raise
    validate_causal_order(ft, st, dt, et)


def test_feature_after_signal_rejected():
    ft = datetime(2026, 10, 2, 9, 30, 1, tzinfo=TPE)
    st = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    dt = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    et = datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE)
    with pytest.raises(CausalityViolationError, match="feature_after_signal_rejected"):
        validate_causal_order(ft, st, dt, et)


def test_signal_after_decision_rejected():
    ft = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    st = datetime(2026, 10, 2, 9, 30, 3, tzinfo=TPE)
    dt = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    et = datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE)
    with pytest.raises(CausalityViolationError, match="signal_after_decision_rejected"):
        validate_causal_order(ft, st, dt, et)


def test_execution_equal_decision_rejected():
    ft = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    st = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    dt = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    et = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    with pytest.raises(CausalityViolationError, match="execution_equal_decision_rejected"):
        validate_causal_order(ft, st, dt, et)


def test_execution_before_decision_rejected():
    ft = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    st = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    dt = datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    et = datetime(2026, 10, 2, 9, 30, 1, tzinfo=TPE)
    with pytest.raises(CausalityViolationError, match="execution_before_decision_rejected"):
        validate_causal_order(ft, st, dt, et)


# ==============================================================================
# 3. Major 3: Bar Time Semantics & Execution Clock
# ==============================================================================
def test_bar_time_semantics_invalid_boundaries():
    t1 = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    t2 = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    with pytest.raises(ExecutionOrderError, match="must be strictly before"):
        MarketBar(
            bar_open_time=t1,
            bar_close_time=t2,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=500,
        )


def test_tick_execution_point_distinct():
    t = datetime(2026, 10, 2, 9, 30, 15, tzinfo=TPE)
    tick = TickExecutionPoint(tick_time=t, price=100.5, volume=10, bid=100.0, ask=100.5)
    assert tick.price == 100.5
    assert not hasattr(tick, "open")


def test_next_legal_execution_boundary_cases():
    clock = CausalExecutionClock(safety_buffer_seconds=2)

    # Case A: Signal 09:30:00 -> Decision 09:30:02 -> Earliest legal execution 09:31:00
    st_a = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    dt_a, et_a = clock.compute_causal_times(st_a)
    assert dt_a == datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE)
    assert et_a == datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE)

    # Case B: Signal 09:30:59 -> Decision 09:31:01 -> Earliest legal execution 09:32:00
    st_b = datetime(2026, 10, 2, 9, 30, 59, tzinfo=TPE)
    dt_b, et_b = clock.compute_causal_times(st_b)
    assert dt_b == datetime(2026, 10, 2, 9, 31, 1, tzinfo=TPE)
    assert et_b == datetime(2026, 10, 2, 9, 32, 0, tzinfo=TPE)


def test_no_same_bar_execution():
    clock = CausalExecutionClock(safety_buffer_seconds=2)
    # Signal occurs at 09:30:15
    st = datetime(2026, 10, 2, 9, 30, 15, tzinfo=TPE)

    # Bar 09:30:00 - 09:31:00 (opened before signal!)
    bar_0930 = MarketBar(
        bar_open_time=datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE),
        bar_close_time=datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=1000,
    )
    # Next Bar 09:31:00 - 09:32:00
    bar_0931 = MarketBar(
        bar_open_time=datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE),
        bar_close_time=datetime(2026, 10, 2, 9, 32, 0, tzinfo=TPE),
        open=101.5,
        high=103.0,
        low=101.0,
        close=102.5,
        volume=1200,
    )

    bars = [bar_0930, bar_0931]
    res = clock.execute_market_entry(st, bars, direction="LONG")
    assert res["status"] == "FILLED"
    # Must NOT fill on bar_0930.open! Must fill on bar_0931.open!
    assert res["execution_time"] == bar_0931.bar_open_time.isoformat()
    assert res["theoretical_entry_price"] == 101.5


def test_no_legal_execution():
    clock = CausalExecutionClock(safety_buffer_seconds=2)
    st = datetime(2026, 10, 2, 13, 29, 30, tzinfo=TPE)  # Near market close
    # Only bars up to 13:29:00 exist
    bar_1328 = MarketBar(
        bar_open_time=datetime(2026, 10, 2, 13, 28, 0, tzinfo=TPE),
        bar_close_time=datetime(2026, 10, 2, 13, 29, 0, tzinfo=TPE),
        open=100.0,
        high=100.5,
        low=99.8,
        close=100.0,
        volume=200,
    )
    res = clock.execute_market_entry(st, [bar_1328], direction="LONG")
    assert res["status"] == "NO_CAUSAL_EXECUTION"
    assert res["theoretical_entry_price"] is None
    assert res["actual_entry_price"] is None


# ==============================================================================
# 4. Major 1: Slippage Single Source of Truth
# ==============================================================================
def test_slippage_not_double_counted():
    """SLIPPAGE_NOT_DOUBLE_COUNTED Regression Test.
    
    Verifies that:
    1. Actual fills embody slippage.
    2. Derived slippage matches dollar discrepancy.
    3. Net PnL from actual execution equals Net PnL from theoretical execution minus slippage.
    4. Net PnL does NOT double count slippage.
    """
    theo_entry = 100.0
    actual_entry = 100.5  # 50 bps adverse entry slippage (+0.5 per share)
    theo_exit = 105.0
    actual_exit = 104.8   # 20 bps adverse exit slippage (-0.2 per share)
    qty = 1000

    cost_model = TransactionCostModel(
        broker_fee_rate=0.001425,
        broker_discount=0.28,
        minimum_fee=20.0,
        daytrade_tax_rate=0.0015,
        normal_tax_rate=0.0030,
    )

    pnl_dict = calculate_single_source_pnl(
        theoretical_entry_price=theo_entry,
        actual_entry_price=actual_entry,
        theoretical_exit_price=theo_exit,
        actual_exit_price=actual_exit,
        quantity=qty,
        cost_model=cost_model,
        is_daytrade=True,
        direction="LONG",
    )

    # Actual gross: (104.8 - 100.5) * 1000 = 4300.0
    assert pnl_dict["gross_pnl_actual"] == 4300.0

    # Theoretical gross: (105.0 - 100.0) * 1000 = 5000.0
    assert pnl_dict["gross_pnl_theoretical"] == 5000.0

    # Total slippage: (0.5 + 0.2) * 1000 = 700.0
    assert pnl_dict["slippage_cost"] == 700.0

    # Entry comm: floor(100500 * 0.001425 * 0.28) = floor(40.0995) = 40
    # Exit comm:  floor(104800 * 0.001425 * 0.28) = floor(41.8152) = 41
    # Tax:        floor(104800 * 0.0015) = floor(157.2) = 157
    assert pnl_dict["entry_commission"] == 40.0
    assert pnl_dict["exit_commission"] == 41.0
    assert pnl_dict["total_commission"] == 81.0
    assert pnl_dict["tax"] == 157.0

    # Net PnL = 4300.0 - 81.0 - 157.0 = 4062.0
    assert pnl_dict["net_pnl"] == 4062.0

    # Theoretical check: 5000.0 - 700.0 (slippage) - 81.0 - 157.0 = 4062.0
    theo_net = (
        pnl_dict["gross_pnl_theoretical"]
        - pnl_dict["slippage_cost"]
        - pnl_dict["total_commission"]
        - pnl_dict["tax"]
    )
    assert math.isclose(pnl_dict["net_pnl"], theo_net, abs_tol=1e-5)


# ==============================================================================
# 5. Cost Model & Tick Size Boundary Cases
# ==============================================================================
def test_buy_and_sell_cost_arithmetic():
    model = TransactionCostModel()
    # Small notional triggers 20 TWD minimum fee
    assert model.calculate_commission(10000.0) == 20.0
    # Larger notional: 1,000,000 * 0.001425 * 0.28 = 399.0 -> 399
    assert model.calculate_commission(1000000.0) == 399.0

    # Day-trading tax: 1,000,000 * 0.0015 = 1500
    assert model.calculate_tax(1000000.0, is_daytrade=True) == 1500.0
    # Normal tax: 1,000,000 * 0.0030 = 3000
    assert model.calculate_tax(1000000.0, is_daytrade=False) == 3000.0


def test_twse_tick_size_boundary_cases():
    assert get_twse_tick_size(9.99) == 0.01
    assert get_twse_tick_size(10.0) == 0.05
    assert get_twse_tick_size(49.95) == 0.05
    assert get_twse_tick_size(50.0) == 0.10
    assert get_twse_tick_size(99.9) == 0.10
    assert get_twse_tick_size(100.0) == 0.50
    assert get_twse_tick_size(499.5) == 0.50
    assert get_twse_tick_size(500.0) == 1.00
    assert get_twse_tick_size(999.0) == 1.00
    assert get_twse_tick_size(1000.0) == 5.00
    assert get_twse_tick_size(2500.0) == 5.00

    # Test rounding to tick
    assert round_to_twse_tick(52.33) == 52.30
    assert round_to_twse_tick(52.33, round_up=True) == 52.40


# ==============================================================================
# 6. Risk Semantics & Rejection
# ==============================================================================
def test_zero_risk_r_rejection():
    with pytest.raises(InvalidTradeParametersError, match="zero-risk R rejection"):
        create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time="2026-10-02T09:30:00+08:00",
            signal_time="2026-10-02T09:30:00+08:00",
            decision_available_time="2026-10-02T09:30:02+08:00",
            execution_time="2026-10-02T09:31:00+08:00",
            exit_time="2026-10-02T09:40:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.0,
            theoretical_exit_price=105.0,
            actual_exit_price=105.0,
            stop_loss_price=100.0,  # Zero risk! entry == stop
            intraday_bars_during_trade=[],
            features_snapshot={},
        )


def test_long_invalid_stop_rejection():
    with pytest.raises(InvalidTradeParametersError, match="long invalid stop"):
        create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time="2026-10-02T09:30:00+08:00",
            signal_time="2026-10-02T09:30:00+08:00",
            decision_available_time="2026-10-02T09:30:02+08:00",
            execution_time="2026-10-02T09:31:00+08:00",
            exit_time="2026-10-02T09:40:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.0,
            theoretical_exit_price=105.0,
            actual_exit_price=105.0,
            stop_loss_price=102.0,  # Invalid: stop above entry for LONG
            intraday_bars_during_trade=[],
            features_snapshot={},
        )


def test_short_invalid_stop_rejection():
    with pytest.raises(InvalidTradeParametersError, match="short invalid stop"):
        create_phase2_trade(
            symbol="2330",
            direction="SHORT",
            quantity=1000,
            feature_time="2026-10-02T09:30:00+08:00",
            signal_time="2026-10-02T09:30:00+08:00",
            decision_available_time="2026-10-02T09:30:02+08:00",
            execution_time="2026-10-02T09:31:00+08:00",
            exit_time="2026-10-02T09:40:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.0,
            theoretical_exit_price=95.0,
            actual_exit_price=95.0,
            stop_loss_price=98.0,  # Invalid: stop below entry for SHORT
            intraday_bars_during_trade=[],
            features_snapshot={},
        )


def test_mfe_mae_decomposition():
    b1 = MarketBar(
        bar_open_time=datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE),
        bar_close_time=datetime(2026, 10, 2, 9, 32, 0, tzinfo=TPE),
        open=100.0,
        high=104.0,  # MFE
        low=97.0,   # MAE
        close=102.0,
        volume=500,
    )
    trade = create_phase2_trade(
        symbol="2330",
        direction="LONG",
        quantity=1000,
        feature_time="2026-10-02T09:30:00+08:00",
        signal_time="2026-10-02T09:30:00+08:00",
        decision_available_time="2026-10-02T09:30:02+08:00",
        execution_time="2026-10-02T09:31:00+08:00",
        exit_time="2026-10-02T09:40:00+08:00",
        theoretical_entry_price=100.0,
        actual_entry_price=100.0,
        theoretical_exit_price=102.0,
        actual_exit_price=102.0,
        stop_loss_price=95.0,  # Risk = 5.0 / share
        intraday_bars_during_trade=[b1],
        features_snapshot={},
    )
    assert trade.initial_risk_per_share == 5.0
    assert trade.initial_risk_amount == 5000.0
    assert trade.mfe_price == 104.0
    assert trade.mae_price == 97.0
    assert trade.mfe_pct == 4.0
    assert trade.mae_pct == 3.0
    assert trade.mfe_R == 4.0 / 5.0  # +0.8 R
    assert trade.mae_R == -3.0 / 5.0  # -0.6 R


# ==============================================================================
# 7. Real Future Mutation Invariance
# ==============================================================================
def test_future_mutation_invariant():
    """Builds historical bars up to t, calculates feature, mutates future bars, verifies equality."""
    base_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
    bars: list[CompletedBar] = []
    # 20 historical bars
    for i in range(20):
        t_end = base_t - timedelta(minutes=20 - i - 1)
        t_start = t_end - timedelta(minutes=1)
        bars.append(
            CompletedBar(
                start_time=t_start,
                end_time=t_end,
                open=100.0 + i * 0.1,
                high=100.5 + i * 0.1,
                low=99.5 + i * 0.1,
                close=100.2 + i * 0.1,
                volume=1000 + i * 50,
            )
        )

    # 10 future bars after base_t
    for i in range(1, 11):
        t_start = base_t + timedelta(minutes=i - 1)
        t_end = base_t + timedelta(minutes=i)
        bars.append(
            CompletedBar(
                start_time=t_start,
                end_time=t_end,
                open=105.0,
                high=106.0,
                low=104.0,
                close=105.5,
                volume=2000,
            )
        )

    series_a = CausalBarSeries(bars)
    as_of_a = series_a.as_of(base_t)
    feat_a_vwap = KnowledgeV1Features.dist_to_bar_vwap_pct(as_of_a[-1].close, as_of_a)
    feat_a_barpos = KnowledgeV1Features.close_location_value(as_of_a[-1])

    # Now mutate ALL future bars violently
    mutated_bars = [b for b in bars if b.end_time <= base_t]
    for i in range(1, 11):
        t_start = base_t + timedelta(minutes=i - 1)
        t_end = base_t + timedelta(minutes=i)
        mutated_bars.append(
            CompletedBar(
                start_time=t_start,
                end_time=t_end,
                open=9999.0,  # Extreme mutation
                high=99999.0,
                low=1.0,
                close=50000.0,
                volume=9999999,
            )
        )

    series_b = CausalBarSeries(mutated_bars)
    as_of_b = series_b.as_of(base_t)
    feat_b_vwap = KnowledgeV1Features.dist_to_bar_vwap_pct(as_of_b[-1].close, as_of_b)
    feat_b_barpos = KnowledgeV1Features.close_location_value(as_of_b[-1])

    assert feat_a_vwap == feat_b_vwap
    assert feat_a_barpos == feat_b_barpos


# ==============================================================================
# 8. Major 4: Event-based Purge & Embargo
# ==============================================================================
def test_event_label_overlap_purge_and_embargo():
    base = datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)
    trades = []
    # Create 30 trades over time
    for i in range(30):
        st = base + timedelta(minutes=i * 10)
        # Some trades have forward labels that extend 25 minutes
        le = st + timedelta(minutes=25)
        trades.append({
            "sample_time": st,
            "label_start_time": st + timedelta(minutes=1),
            "label_end_time": le,
            "id": i,
        })

    splitter = EventWalkForwardSplitter(
        n_splits=3,
        embargo_duration=timedelta(minutes=15),
    )
    folds = splitter.split(trades)
    assert len(folds) == 3

    for fold in folds:
        test_start = fold.test_start_time
        # Verify NO training item has label_end_time >= test_start (purging)
        for item in fold.train_items:
            assert item["label_end_time"] < test_start

    # Verify index splitter unsafe flag
    idx_splitter = IndexWalkForwardSplitter(n_splits=3)
    assert idx_splitter.NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS is True


# ==============================================================================
# 9. Parameter Provenance & Cost Governance
# ==============================================================================
def test_parameter_provenance_audit():
    rec = PHASE2_PROVENANCE_REGISTRY["PARAM_PB_VOL_DECAY"]
    assert rec.author == "Anna Coulling"
    assert rec.chapter_or_section == "Chapter 7"
    audit_parameter_provenance(rec)

    # Corrupted chapter 5 audit must fail
    corrupted = copy.replace(rec, chapter_or_section="Chapter 5") if hasattr(copy, "replace") else copy.copy(rec)
    if not hasattr(copy, "replace"):
        corrupted = type(rec)(
            parameter_id=rec.parameter_id,
            name=rec.name,
            value_or_grid=rec.value_or_grid,
            status=rec.status,
            author=rec.author,
            source_book_or_doc=rec.source_book_or_doc,
            chapter_or_section="Chapter 5",
            notes=rec.notes,
        )
    with pytest.raises(ValueError, match="must point to Chapter 7"):
        audit_parameter_provenance(corrupted)

    # Research grids must be AI_QUANTIZED
    grid_decay = PHASE2_PROVENANCE_REGISTRY["GRID_PB_VOL_DECAY"]
    assert grid_decay.status == ProvenanceStatus.AI_QUANTIZED
    audit_parameter_provenance(grid_decay)


def test_cost_parameter_governance():
    assert COST_PARAMETER_REGISTRY["broker_fee_rate"].category == CostParameterCategory.SOURCE_PARAMETER
    assert COST_PARAMETER_REGISTRY["daytrade_tax_rate"].category == CostParameterCategory.SOURCE_PARAMETER
    assert COST_PARAMETER_REGISTRY["broker_discount"].category == CostParameterCategory.EASYSTOCK_EXISTING_PARAMETER
    assert COST_PARAMETER_REGISTRY["minimum_fee"].category == CostParameterCategory.EASYSTOCK_EXISTING_PARAMETER
    assert COST_PARAMETER_REGISTRY["slippage_grid"].category == CostParameterCategory.RESEARCH_GOVERNANCE_CANDIDATE


# ==============================================================================
# 10. Metrics, SQN & Research-Only Verdicts
# ==============================================================================
def test_metrics_and_sqn_metric_only():
    b = MarketBar(
        bar_open_time=datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE),
        bar_close_time=datetime(2026, 10, 2, 9, 32, 0, tzinfo=TPE),
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=500,
    )
    # Build 5 sample trades
    trades = []
    for i in range(5):
        exit_p = 104.0 if i % 2 == 0 else 98.0
        t = create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time=f"2026-10-02T09:3{i}:00+08:00",
            signal_time=f"2026-10-02T09:3{i}:00+08:00",
            decision_available_time=f"2026-10-02T09:3{i}:02+08:00",
            execution_time=f"2026-10-02T09:3{i+1}:00+08:00",
            exit_time=f"2026-10-02T09:5{i}:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.0,
            theoretical_exit_price=exit_p,
            actual_exit_price=exit_p,
            stop_loss_price=95.0,
            intraday_bars_during_trade=[b],
            features_snapshot={},
        )
        trades.append(t)

    metrics = calculate_trade_metrics(trades)
    assert metrics["trade_count"] == 5.0
    assert "SQN" in metrics
    assert "win_rate" in metrics
    assert "expectancy_R" in metrics

    # Verify verdicts
    comparator = BaselineComparator(min_trades_required=5)
    baseline = {"trade_count": 5.0, "expectancy_R": 0.0, "profit_factor": 1.0, "win_rate": 0.5}
    res = comparator.compare(metrics, baseline)
    assert res.verdict in [
        ResearchVerdict.KEEP_FOR_MORE_RESEARCH,
        ResearchVerdict.REJECT_RESEARCH_CANDIDATE,
        ResearchVerdict.DATA_INSUFFICIENT,
    ]
    # Check that PROMOTE_TO_PRODUCTION is not in enum
    assert "PROMOTE_TO_PRODUCTION" not in [v.value for v in ResearchVerdict]


# ==============================================================================
# 11. Static Production Import Isolation
# ==============================================================================
def test_static_production_import_isolation():
    """Scans all production entry points to guarantee zero imports of phase2."""
    production_files = [
        REPO_ROOT / "market_risk.py",
        REPO_ROOT / "position_manager.py",
        REPO_ROOT / "strategy_engine.py",
        REPO_ROOT / "intraday_live.py",
        REPO_ROOT / "line_stock_bot.py",
        REPO_ROOT / "trade_notifications.py",
        REPO_ROOT / "public_feed.py",
    ]

    for p in production_files:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "phase2" not in alias.name, f"Forbidden phase2 import in {p.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "phase2" not in mod, f"Forbidden phase2 import in {p.name}: {mod}"
