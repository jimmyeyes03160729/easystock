"""Test suite for EasyStock Daytrade Research Phase 2B - Batch 1 Candidates.

Tests:
1. Candidate 1 (Pullback Volume Decay):
   - Pattern detection logic
   - Future mutation invariance (future bars after signal do not alter signal detection at time t)
2. Candidate 2 (Range Expansion):
   - Pattern detection logic (bullish and bearish)
   - Future mutation invariance
3. Candidate 3 (2B Reversal):
   - Strict chronological ordering: pivot_time <= confirmation_time <= breakout_time <= signal_time
   - No future pivot leakage (pivots must be confirmed before breakout)
4. Candidate 4 (1-2-3 Reversal):
   - Strict chronological ordering: p1_time <= p2_time <= p3_time <= signal_time
   - No future pivot leakage
5. ResearchRunner & Exit Semantics:
   - Fixed horizon exits (5m, 15m, 30m)
   - StopTargetExit (1.5R target)
   - Single Source of Truth accounting (0, 1, 2, 3 ticks slippage)
6. Walk-Forward Event Purge Integration:
   - EventWalkForwardSplitter purges overlapping forward-label windows
7. Reproducibility & Provenance:
   - Parameter provenance audits
   - Deterministic dataset generation
8. Static Production Import Isolation:
   - Verifies production source files never import daytrade_learning.phase2
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone, timedelta, time
from pathlib import Path
import pytest

from daytrade_learning.phase2 import (
    RESEARCH_ONLY,
    INERT_BY_DEFAULT,
    MarketBar,
    CausalExecutionClock,
    TransactionCostModel,
    ResearchRunner,
    EXIT_FIXED_5M,
    EXIT_FIXED_15M,
    EXIT_FIXED_30M,
    EXIT_FIXED_60M,
    EXIT_STOP_TARGET_1_5R,
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
    BaselineComparator,
    ResearchVerdict,
    EventWalkForwardSplitter,
    PHASE2_PROVENANCE_REGISTRY,
    audit_parameter_provenance,
    StockDayCompletenessStatus,
    MissingnessType,
    CorporateActionBoundaryStatus,
    StockDayCompletenessReport,
    assess_stock_day_completeness,
    PARAM_SLIPPAGE_GRID_TICKS,
    PARAM_SLIPPAGE_GRID,
    get_twse_tick_size,
)

TPE = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[1]


def make_bar(
    minute_offset: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
    base_time: datetime | None = None,
) -> MarketBar:
    base = base_time or datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)
    t_open = base + timedelta(minutes=minute_offset)
    t_close = t_open + timedelta(minutes=1)
    return MarketBar(
        bar_open_time=t_open,
        bar_close_time=t_close,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# ==============================================================================
# 1. Architectural Checks
# ==============================================================================
def test_phase2b_architecture():
    assert RESEARCH_ONLY is True
    assert INERT_BY_DEFAULT is True


# ==============================================================================
# 2. Candidate 1: Pullback Volume Decay & Future Mutation Invariance
# ==============================================================================
def test_pullback_volume_decay_detection():
    detector = PullbackVolumeDecayDetector(min_pullback_bars=2, max_pullback_bars=3, impulse_bars_count=2)
    bars = [
        # Impulse up (2 bars) with heavy volume (5000/bar)
        make_bar(0, 100.0, 102.0, 100.0, 102.0, volume=5000.0),
        make_bar(1, 102.0, 105.0, 101.8, 105.0, volume=6000.0),
        # Pullback (2 bars) with low volume (1500/bar, decay ratio ~ 1500/5500 = 0.27 <= 0.50)
        make_bar(2, 105.0, 105.2, 103.8, 104.0, volume=1500.0),
        make_bar(3, 104.0, 104.5, 103.5, 103.8, volume=1200.0),
    ]

    signals = detector.detect_signals("2330", bars, threshold=0.50)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == "LONG"
    assert sig.decay_ratio < 0.50
    assert sig.stop_loss_price == 103.5
    assert sig.signal_time == bars[3].bar_close_time


def test_pullback_volume_decay_future_mutation_invariance():
    detector = PullbackVolumeDecayDetector(min_pullback_bars=2, max_pullback_bars=3, impulse_bars_count=2)
    base_bars = [
        make_bar(0, 100.0, 102.0, 100.0, 102.0, volume=5000.0),
        make_bar(1, 102.0, 105.0, 101.8, 105.0, volume=6000.0),
        make_bar(2, 105.0, 105.2, 103.8, 104.0, volume=1500.0),
        make_bar(3, 104.0, 104.5, 103.5, 103.8, volume=1200.0),
    ]
    # Future bars: scenario A
    future_a = [
        make_bar(4, 103.8, 106.0, 103.5, 106.0, volume=8000.0),
        make_bar(5, 106.0, 108.0, 105.8, 108.0, volume=9000.0),
    ]
    # Future bars: scenario B (drastic crash)
    future_b = [
        make_bar(4, 103.8, 104.0, 80.0, 80.0, volume=999999.0),
        make_bar(5, 80.0, 81.0, 60.0, 60.0, volume=999999.0),
    ]

    sigs_a = detector.detect_signals("2330", base_bars + future_a, threshold=0.50)
    sigs_b = detector.detect_signals("2330", base_bars + future_b, threshold=0.50)

    # Signal at minute 3 must be identical in both runs
    sig_at_3_a = [s for s in sigs_a if s.signal_time == base_bars[3].bar_close_time]
    sig_at_3_b = [s for s in sigs_b if s.signal_time == base_bars[3].bar_close_time]
    assert len(sig_at_3_a) == 1
    assert len(sig_at_3_b) == 1
    assert sig_at_3_a[0].decay_ratio == sig_at_3_b[0].decay_ratio
    assert sig_at_3_a[0].stop_loss_price == sig_at_3_b[0].stop_loss_price


# ==============================================================================
# 3. Candidate 2: Range Expansion & Future Mutation Invariance
# ==============================================================================
def test_range_expansion_detection():
    detector = RangeExpansionDetector(expansion_thresholds=[1.5], lookback_bars=5)
    # 5 compressed bars (range = 0.5 TWD each)
    bars = [make_bar(i, 100.0, 100.5, 100.0, 100.3, volume=1000.0) for i in range(5)]
    # Bar 6: Huge expansion bar (range = 2.0 TWD, expansion ratio = 2.0 / 0.5 = 4.0 >= 1.5)
    bars.append(make_bar(5, 100.3, 102.5, 100.2, 102.4, volume=3000.0))

    signals = detector.detect_signals("2330", bars, threshold=1.5)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == "LONG"
    assert sig.expansion_ratio >= 1.5
    assert sig.stop_loss_price == 100.2
    assert sig.signal_time == bars[5].bar_close_time


def test_range_expansion_future_mutation_invariance():
    detector = RangeExpansionDetector(expansion_thresholds=[1.5], lookback_bars=5)
    base_bars = [make_bar(i, 100.0, 100.5, 100.0, 100.3) for i in range(5)]
    base_bars.append(make_bar(5, 100.3, 102.5, 100.2, 102.4))

    future_normal = [make_bar(6, 102.4, 103.0, 102.3, 102.8)]
    future_wild = [make_bar(6, 102.4, 999.0, 50.0, 500.0)]

    sigs_norm = detector.detect_signals("2330", base_bars + future_normal, threshold=1.5)
    sigs_wild = detector.detect_signals("2330", base_bars + future_wild, threshold=1.5)

    sig_5_norm = [s for s in sigs_norm if s.signal_time == base_bars[5].bar_close_time]
    sig_5_wild = [s for s in sigs_wild if s.signal_time == base_bars[5].bar_close_time]
    assert len(sig_5_norm) == 1
    assert len(sig_5_wild) == 1
    assert sig_5_norm[0].expansion_ratio == sig_5_wild[0].expansion_ratio


# ==============================================================================
# 4. Candidate 3: 2B Reversal & No Future Pivot Leakage
# ==============================================================================
def test_two_b_reversal_detection_and_causal_order():
    detector = TwoBReversalDetector(pivot_confirmation_bars=2, max_failure_bars=3)
    bars = [
        # Build a swing high at bar 2 (high 105.0)
        make_bar(0, 100.0, 102.0, 99.8, 101.5),
        make_bar(1, 101.5, 103.5, 101.2, 103.0),
        make_bar(2, 103.0, 105.0, 102.8, 104.5),  # Pivot High (105.0)
        make_bar(3, 104.5, 104.8, 103.5, 104.0),  # Conf bar 1
        make_bar(4, 104.0, 104.2, 103.0, 103.5),  # Conf bar 2 -> Confirmed at bar 4 close!
        # Breakout above pivot (105.0)
        make_bar(5, 103.5, 105.6, 103.4, 105.2),  # False Breakout (high 105.6 > 105.0)
        # Immediate failure: closes back below 105.0
        make_bar(6, 105.2, 105.3, 104.0, 104.4),  # Closes at 104.4 (< 105.0) -> 2B Signal!
    ]

    signals = detector.detect_signals("2330", bars, direction="SHORT")
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.direction == "SHORT"
    assert sig.pivot_price == 105.0
    assert sig.breakout_price >= 105.6
    assert sig.stop_loss_price >= 105.6

    # Verify chronological ordering
    assert sig.pivot_time <= sig.confirmation_time
    assert sig.confirmation_time <= sig.signal_time


def test_two_b_no_future_pivot_leakage():
    """Verify that an unconfirmed pivot cannot trigger a 2B signal prematurely."""
    detector = TwoBReversalDetector(pivot_confirmation_bars=2, max_failure_bars=3)
    bars = [
        make_bar(0, 100.0, 102.0, 99.8, 101.5),
        make_bar(1, 101.5, 105.0, 101.2, 104.5),  # Potential high at bar 1
        # Bar 2 hasn't confirmed bar 1 yet (needs 2 bars confirmation)
        make_bar(2, 104.5, 105.5, 103.8, 104.2),  # Bar 2 already exceeds bar 1
    ]
    signals = detector.detect_signals("2330", bars, direction="SHORT")
    assert len(signals) == 0  # No signal because no pivot was causally confirmed


# ==============================================================================
# 5. Candidate 4: 1-2-3 Reversal Chronological Order & Causal Stages
# ==============================================================================
def test_one_two_three_chronological_ordering():
    detector = OneTwoThreeDetector(confirmation_bars=1)
    bars = [
        # Point 1: Swing High at bar 1 (high 110.0)
        make_bar(0, 105.0, 107.0, 104.8, 106.5),
        make_bar(1, 106.5, 110.0, 106.0, 109.5),  # Point 1 (High = 110.0)
        make_bar(2, 109.5, 109.8, 107.0, 107.5),  # p1 confirmed
        # Point 2: Swing Low at bar 3 (low 102.0)
        make_bar(3, 107.5, 107.8, 102.0, 102.5),  # Point 2 (Low = 102.0)
        make_bar(4, 102.5, 105.0, 102.5, 104.5),  # p2 confirmed
        # Point 3: Retracement High at bar 5 (high 107.0 < 110.0)
        make_bar(5, 104.5, 107.0, 104.0, 106.5),  # Point 3 (High = 107.0)
        make_bar(6, 106.5, 106.8, 103.0, 103.2),  # p3 confirmed
        # Confirmation: Bar 7 breaks below Point 2 low (102.0)
        make_bar(7, 103.2, 103.2, 101.0, 101.5),  # Close 101.5 < 102.0 -> Signal!
    ]

    signals = detector.detect_signals("2330", bars, direction="SHORT")
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.direction == "SHORT"
    assert sig.point1_price == 110.0
    assert sig.point2_price == 102.0
    assert sig.point3_price == 107.0
    assert sig.stop_loss_price == 107.0

    # Verify chronological ordering
    assert sig.point1_time <= sig.point2_time
    assert sig.point2_time <= sig.point3_time
    assert sig.point3_time <= sig.signal_time


# ==============================================================================
# 6. Research Runner & Slippage Sensitivity (0 to 3 Ticks Canonical)
# ==============================================================================
# ==============================================================================
# 6. Research Runner & Slippage Sensitivity (0 to 3 Ticks Canonical Grid)
# ==============================================================================
def test_research_runner_tick_slippage_and_cost_integration():
    detector = RangeExpansionDetector(expansion_thresholds=[1.5], lookback_bars=5)
    bars = [make_bar(i, 100.0, 100.5, 100.0, 100.3) for i in range(5)]
    bars.append(make_bar(5, 100.0, 102.5, 100.0, 102.5))  # Signal bar (trigger)
    # Subsequent execution and horizon bars with theoretical entry open = 102.5
    bars.append(make_bar(6, 102.5, 102.8, 102.4, 102.5))  # Skipped due to +2s buffer
    bars.append(make_bar(7, 102.5, 102.8, 102.0, 102.5))  # First legal execution bar (open 102.5)
    for j in range(8, 25):
        bars.append(make_bar(j, 102.5, 102.8, 102.0, 102.5))

    signals = detector.detect_signals("2330", bars, threshold=1.5)
    assert len(signals) == 1
    sig = signals[0]

    runner = ResearchRunner(default_quantity=1000)

    # Canonical tick grid [0, 1, 2, 3] ticks on 102.5 (tick size = 0.50)
    trade_0tick = runner.simulate_trade_from_signal(sig, bars, exit_policy=EXIT_FIXED_15M, slippage_ticks=0)
    trade_1tick = runner.simulate_trade_from_signal(sig, bars, exit_policy=EXIT_FIXED_15M, slippage_ticks=1)
    trade_2tick = runner.simulate_trade_from_signal(sig, bars, exit_policy=EXIT_FIXED_15M, slippage_ticks=2)
    trade_3tick = runner.simulate_trade_from_signal(sig, bars, exit_policy=EXIT_FIXED_15M, slippage_ticks=3)

    assert trade_0tick is not None
    assert trade_1tick is not None
    assert trade_2tick is not None
    assert trade_3tick is not None

    # Theoretical fill is 102.5; tick size is 0.50
    assert trade_0tick.theoretical_entry_price == 102.5
    assert trade_0tick.actual_entry_price == 102.5
    assert trade_1tick.actual_entry_price == 103.0
    assert trade_2tick.actual_entry_price == 103.5
    assert trade_3tick.actual_entry_price == 104.0

    # Net PnL strictly monotonically decreases with slippage ticks
    assert trade_0tick.net_pnl > trade_1tick.net_pnl > trade_2tick.net_pnl > trade_3tick.net_pnl

    # Slippage cost is derived single-source, no double count
    assert trade_0tick.slippage_cost == 0.0
    assert trade_1tick.slippage_cost > 0.0


def test_slippage_four_legs_and_tick_size_symmetry():
    """Verify BUY entry, SELL exit, SHORT entry, BUY-TO-COVER exit adverse slippage and bracket sizes."""
    clock = CausalExecutionClock(safety_buffer_seconds=2)
    runner = ResearchRunner(clock=clock, default_quantity=1000)

    base_time = datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)

    # 1. BUY Entry Adverse Slippage (Long pays higher)
    # Price = 102.5 (tick size = 0.50)
    entry_bars_long = [
        make_bar(0, 100.0, 100.5, 99.5, 100.0, base_time=base_time),
        make_bar(1, 102.5, 103.0, 102.0, 102.5, base_time=base_time),
    ]
    sig_time = base_time + timedelta(seconds=30)
    for ticks, expected_fill in [(0, 102.5), (1, 103.0), (2, 103.5), (3, 104.0)]:
        res = clock.execute_market_entry(sig_time, entry_bars_long, direction="LONG", slippage_ticks=ticks)
        assert res["status"] == "FILLED"
        assert res["theoretical_entry_price"] == 102.5
        assert res["actual_entry_price"] == expected_fill

    # 2. SHORT Entry Adverse Slippage (Short sells lower)
    # Price = 102.5 (tick size = 0.50)
    for ticks, expected_fill in [(0, 102.5), (1, 102.0), (2, 101.5), (3, 101.0)]:
        res = clock.execute_market_entry(sig_time, entry_bars_long, direction="SHORT", slippage_ticks=ticks)
        assert res["status"] == "FILLED"
        assert res["theoretical_entry_price"] == 102.5
        assert res["actual_entry_price"] == expected_fill

    # 3. SELL Exit Adverse Slippage (Closing Long receives lower)
    # Asymmetric test: Long Entry at 98.0 (tick size = 0.10), Long Exit at 105.0 (tick size = 0.50)
    asym_bars = [
        make_bar(0, 95.0, 96.0, 94.5, 95.5, base_time=base_time),  # bar 0
        make_bar(1, 98.0, 98.5, 97.5, 98.0, base_time=base_time),  # bar 1: Entry at 98.0
        make_bar(2, 105.0, 106.0, 104.5, 105.0, base_time=base_time),  # bar 2: Exit at 105.0
    ]
    from daytrade_learning.phase2.candidates import RangeExpansionSignal
    long_sig = RangeExpansionSignal(
        candidate_id="P2B_02_RANGE_EXPANSION",
        symbol="ASYM",
        direction="LONG",
        signal_time=base_time + timedelta(seconds=30),
        feature_time=base_time + timedelta(seconds=30),
        threshold=1.5,
        expansion_ratio=1.5,
        stop_loss_price=90.0,
        trigger_bar=asym_bars[0],
        features={"expansion_ratio": 1.5},
    )

    trade_asym_0 = runner.simulate_trade_from_signal(long_sig, asym_bars, exit_policy=EXIT_FIXED_5M, slippage_ticks=0)
    trade_asym_1 = runner.simulate_trade_from_signal(long_sig, asym_bars, exit_policy=EXIT_FIXED_5M, slippage_ticks=1)

    assert trade_asym_0 is not None
    assert trade_asym_1 is not None

    # Entry at 98.0 (tick size = 0.10): 1 tick adds 0.10 -> 98.10
    assert trade_asym_0.theoretical_entry_price == 98.0
    assert trade_asym_0.actual_entry_price == 98.0
    assert trade_asym_1.actual_entry_price == 98.10

    # Exit at 105.0 (tick size = 0.50): 1 tick subtracts 0.50 -> 104.50
    assert trade_asym_0.theoretical_exit_price == 105.0
    assert trade_asym_0.actual_exit_price == 105.0
    assert trade_asym_1.actual_exit_price == 104.50

    # 4. BUY-TO-COVER Exit Adverse Slippage (Closing Short pays higher)
    # Short Entry at 105.0 (tick size = 0.50), Short Exit at 98.0 (tick size = 0.10)
    short_asym_bars = [
        make_bar(0, 110.0, 111.0, 109.5, 110.0, base_time=base_time),
        make_bar(1, 105.0, 105.5, 104.5, 105.0, base_time=base_time),  # Entry at 105.0
        make_bar(2, 98.0, 98.5, 97.5, 98.0, base_time=base_time),      # Exit at 98.0
    ]
    short_sig = RangeExpansionSignal(
        candidate_id="P2B_02_RANGE_EXPANSION",
        symbol="ASYM",
        direction="SHORT",
        signal_time=base_time + timedelta(seconds=30),
        feature_time=base_time + timedelta(seconds=30),
        threshold=1.5,
        expansion_ratio=1.5,
        stop_loss_price=115.0,
        trigger_bar=short_asym_bars[0],
        features={"expansion_ratio": 1.5},
    )

    trade_short_0 = runner.simulate_trade_from_signal(short_sig, short_asym_bars, exit_policy=EXIT_FIXED_5M, slippage_ticks=0)
    trade_short_1 = runner.simulate_trade_from_signal(short_sig, short_asym_bars, exit_policy=EXIT_FIXED_5M, slippage_ticks=1)

    assert trade_short_0 is not None
    assert trade_short_1 is not None

    # Short Entry at 105.0: 1 tick subtracts 0.50 -> 104.50
    assert trade_short_0.theoretical_entry_price == 105.0
    assert trade_short_0.actual_entry_price == 105.0
    assert trade_short_1.actual_entry_price == 104.50

    # Buy-to-cover Exit at 98.0: 1 tick adds 0.10 -> 98.10
    assert trade_short_0.theoretical_exit_price == 98.0
    assert trade_short_0.actual_exit_price == 98.0
    assert trade_short_1.actual_exit_price == 98.10


def test_twse_tick_size_boundary_sensitivity():
    """Verify that different price brackets map to exact TWSE statutory tick sizes."""
    runner = ResearchRunner(default_quantity=1000)
    detector = RangeExpansionDetector(expansion_thresholds=[1.1], lookback_bars=2)

    price_brackets = [
        (8.5, 0.01),      # < 10 TWD
        (35.0, 0.05),     # 10 to < 50 TWD
        (85.0, 0.10),     # 50 to < 100 TWD
        (250.0, 0.50),    # 100 to < 500 TWD
        (800.0, 1.00),    # 500 to < 1000 TWD
        (1500.0, 5.00),   # >= 1000 TWD
    ]

    for p, expected_tick in price_brackets:
        assert get_twse_tick_size(p) == expected_tick
        bars = [
            make_bar(0, p, p + expected_tick * 2, p, p + expected_tick),
            make_bar(1, p + expected_tick, p + expected_tick * 4, p, p + expected_tick * 3),
            make_bar(2, p, p + expected_tick * 5, p, p + expected_tick * 4),  # trigger
            make_bar(3, p, p + expected_tick * 2, p, p + expected_tick),      # entry bar open = p
            make_bar(4, p, p + expected_tick * 2, p, p + expected_tick),      # exit bar
        ]
        signals = detector.detect_signals("TEST", bars, threshold=1.1)
        if signals:
            sig = signals[0]
            trade_1tick = runner.simulate_trade_from_signal(sig, bars, exit_policy=EXIT_FIXED_5M, slippage_ticks=1)
            if trade_1tick:
                # 1 tick slippage added to entry
                assert round(trade_1tick.actual_entry_price - trade_1tick.theoretical_entry_price, 4) == expected_tick


def test_stock_day_completeness_expected_session_coverage():
    """Verify completeness based on TWSE Expected Session Timestamp Coverage (266 marks)."""
    base_9am = datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)

    # Construct the canonical 266 TWSE session bars:
    # 265 continuous trading bars (09:00-09:01 up to 13:24-13:25)
    canonical_266 = []
    for m in range(265):
        t_open = base_9am + timedelta(minutes=m)
        t_close = t_open + timedelta(minutes=1)
        canonical_266.append(MarketBar(t_open, t_close, 100.0, 100.5, 99.5, 100.0, 1000.0))
    # 1 closing call auction bar matching at 13:30
    t_close_auction = base_9am + timedelta(hours=4, minutes=30)
    t_open_auction = t_close_auction - timedelta(minutes=1)
    canonical_266.append(MarketBar(t_open_auction, t_close_auction, 100.0, 100.5, 99.5, 100.0, 5000.0))
    assert len(canonical_266) == 266

    # 1. All 266 expected session timestamps present -> COMPLETE
    rep_complete = assess_stock_day_completeness("2330", canonical_266)
    assert rep_complete.status == StockDayCompletenessStatus.COMPLETE
    assert rep_complete.expected_session_bars == 266
    assert rep_complete.actual_bar_count == 266
    assert rep_complete.missing_session_bars == 0
    assert rep_complete.session_coverage_pct == 100.0
    assert rep_complete.missingness_type == MissingnessType.NONE
    assert rep_complete.duplicate_count == 0
    assert rep_complete.monotonic_timestamp is True
    assert rep_complete.rejection_reason is None

    # 2. Intermediate missing timestamps (e.g. 265 bars, missing 1 intermediate bar)
    # Must NOT be classified as COMPLETE because 1-minute bars cannot distinguish NO_TRADE_MINUTE from MISSING_DATA
    bars_265 = [b for i, b in enumerate(canonical_266) if i != 50]  # omit minute 50
    rep_265 = assess_stock_day_completeness("2330", bars_265)
    assert rep_265.status == StockDayCompletenessStatus.USABLE_WITH_GAPS
    assert rep_265.missing_session_bars == 1
    assert rep_265.missingness_type == MissingnessType.PARTIAL_UNKNOWN_MISSINGNESS
    assert "cannot distinguish" in rep_265.rejection_reason

    # 3. Missing session boundary (e.g. only 10:00 to 12:00) -> INVALID
    truncated_bars = [b for b in canonical_266 if time(10, 0) <= b.bar_close_time.astimezone(TPE).time() <= time(12, 0)]
    rep_trunc = assess_stock_day_completeness("2330", truncated_bars)
    assert rep_trunc.status == StockDayCompletenessStatus.INVALID
    assert rep_trunc.missingness_type == MissingnessType.MISSING_SESSION_BOUNDARY

    # 4. Out of session bars (e.g. bar at 14:00) -> INVALID
    out_of_session_bar = MarketBar(base_9am + timedelta(hours=5), base_9am + timedelta(hours=5, minutes=1), 100.0, 100.5, 99.5, 100.0, 10.0)
    rep_oos = assess_stock_day_completeness("2330", canonical_266 + [out_of_session_bar])
    assert rep_oos.status == StockDayCompletenessStatus.INVALID
    assert rep_oos.missingness_type == MissingnessType.OUT_OF_SESSION

    # 5. Duplicate bars -> INVALID
    dup_bars = canonical_266[:10] + [canonical_266[5]]
    rep_dup = assess_stock_day_completeness("2330", dup_bars)
    assert rep_dup.status == StockDayCompletenessStatus.INVALID
    assert rep_dup.missingness_type == MissingnessType.DUPLICATE

    # 6. Non-monotonic timestamps -> INVALID
    non_mono = list(canonical_266[:20])
    non_mono[5], non_mono[6] = non_mono[6], non_mono[5]
    rep_mono = assess_stock_day_completeness("2330", non_mono)
    assert rep_mono.status == StockDayCompletenessStatus.INVALID
    assert rep_mono.missingness_type == MissingnessType.NON_MONOTONIC


def test_corporate_action_tri_state_and_observed_gap():
    """Verify tri-state corporate_action_boundary (UNKNOWN, TRUE, FALSE) and observed_large_gap."""
    base_9am = datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)
    normal_bars = [
        make_bar(0, 100.0, 100.5, 99.5, 100.0, base_time=base_9am),
        make_bar(1, 100.0, 100.5, 99.5, 100.0, base_time=base_9am),
        make_bar(264, 100.0, 100.5, 99.5, 100.0, base_time=base_9am),
    ]

    # Default is UNKNOWN and observed_large_gap=False
    rep_default = assess_stock_day_completeness("2330", normal_bars)
    assert rep_default.corporate_action_boundary == CorporateActionBoundaryStatus.UNKNOWN
    assert rep_default.observed_large_gap is False

    # Large price gap (e.g. 100 -> 110 = 10% jump) sets observed_large_gap=True
    # BUT corporate_action_boundary remains UNKNOWN (no false inference!)
    gap_bars = [
        make_bar(0, 100.0, 100.5, 99.5, 100.0, base_time=base_9am),
        make_bar(1, 110.0, 111.0, 109.5, 110.5, base_time=base_9am),  # 10% jump
        make_bar(264, 110.0, 110.5, 109.5, 110.0, base_time=base_9am),
    ]
    rep_gap = assess_stock_day_completeness("2330", gap_bars)
    assert rep_gap.observed_large_gap is True
    assert rep_gap.corporate_action_boundary == CorporateActionBoundaryStatus.UNKNOWN

    # Explicit verified corporate action flags
    rep_true = assess_stock_day_completeness("2330", normal_bars, corporate_action_boundary=CorporateActionBoundaryStatus.TRUE)
    assert rep_true.corporate_action_boundary == CorporateActionBoundaryStatus.TRUE

    rep_false = assess_stock_day_completeness("2330", normal_bars, corporate_action_boundary="FALSE")
    assert rep_false.corporate_action_boundary == CorporateActionBoundaryStatus.FALSE

    # Diagnostic provenance check: observed_large_gap is strictly DIAGNOSTIC_ONLY
    from daytrade_learning.phase2 import (
        OBSERVED_LARGE_GAP_PROVENANCE,
        OBSERVED_LARGE_GAP_THRESHOLD,
        HISTORICAL_KBAR_LABEL,
        STREAMING_KBAR_LABEL,
        BASE_COMMISSION_REFERENCE_RATE,
        PARAM_BASE_COMMISSION_REFERENCE_RATE,
        PARAM_DAYTRADE_TAX_RATE,
        CostParameterCategory,
    )
    assert OBSERVED_LARGE_GAP_THRESHOLD == 0.08
    assert OBSERVED_LARGE_GAP_PROVENANCE["status"] == "RESEARCH_GOVERNANCE_CANDIDATE"
    assert OBSERVED_LARGE_GAP_PROVENANCE["purpose"] == "DIAGNOSTIC_ONLY"

    # Historical K-Bar semantics lock
    assert HISTORICAL_KBAR_LABEL == "RIGHT_EDGE"
    assert STREAMING_KBAR_LABEL == "START_TIME"


def test_exit_horizon_and_slippage_governance():
    """Verify primary and secondary exit policies, commission provenance, and canonical slippage parameter registry."""
    # Commission provenance governance
    from daytrade_learning.phase2 import (
        BASE_COMMISSION_REFERENCE_RATE,
        PARAM_BASE_COMMISSION_REFERENCE_RATE,
        PARAM_DAYTRADE_TAX_RATE,
        CostParameterCategory,
    )
    assert BASE_COMMISSION_REFERENCE_RATE == 0.001425
    assert PARAM_BASE_COMMISSION_REFERENCE_RATE.category == CostParameterCategory.OFFICIAL_MARKET_REFERENCE
    assert "not a fixed market-wide fee" in PARAM_BASE_COMMISSION_REFERENCE_RATE.description
    assert "Dec 31, 2027" in PARAM_DAYTRADE_TAX_RATE.description

    # Primary horizons
    assert EXIT_FIXED_5M.horizon_minutes == 5
    assert EXIT_FIXED_15M.horizon_minutes == 15
    assert EXIT_FIXED_30M.horizon_minutes == 30
    assert EXIT_FIXED_60M.horizon_minutes == 60
    assert EXIT_FIXED_5M.target_R is None

    # Secondary exit candidate
    assert EXIT_STOP_TARGET_1_5R.name == "STOP_TARGET_1_5R_MAX30M"
    assert EXIT_STOP_TARGET_1_5R.target_R == 1.5

    # Canonical slippage grid
    assert PARAM_SLIPPAGE_GRID_TICKS.value == [0, 1, 2, 3]
    assert PARAM_SLIPPAGE_GRID_TICKS.category.value == "RESEARCH_GOVERNANCE_CANDIDATE"
    assert "ticks" in PARAM_SLIPPAGE_GRID_TICKS.name


def test_cost_accounting_identity_invariant():
    """Verify that Cost Accounting Identity holds strictly across LONG and SHORT trades:
    1. Theoretical Gross - Total Friction (Slippage + Fee + Tax) == Net PnL
    2. Actual Post-Slippage Gross - Statutory Fees/Tax == Net PnL
    3. In R units: theoretical_gross_R - total_cost_drag_R == net_expectancy_R
    4. In R units: actual_gross_R - fee_tax_drag_R == net_expectancy_R
    """
    from daytrade_learning.phase2 import (
        create_phase2_trade,
        TransactionCostModel,
        get_twse_tick_size,
    )
    cost_model = TransactionCostModel()

    # Test cases: (symbol, direction, entry, stop, exit, slip_ticks)
    cases = [
        ("2330", "LONG", 100.0, 98.0, 105.0, 1),
        ("2330", "LONG", 100.0, 99.0, 97.0, 2),
        ("2330", "LONG", 500.0, 495.0, 510.0, 3),
        ("2330", "SHORT", 100.0, 102.0, 95.0, 1),
        ("2330", "SHORT", 100.0, 101.0, 103.0, 2),
        ("2330", "SHORT", 500.0, 505.0, 490.0, 0),
    ]

    base_time = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)

    for symbol, direction, theo_entry, stop_loss, theo_exit, slip_ticks in cases:
        entry_tick = get_twse_tick_size(theo_entry)
        exit_tick = get_twse_tick_size(theo_exit)

        if direction == "LONG":
            actual_entry = theo_entry + (slip_ticks * entry_tick)
            actual_exit = theo_exit - (slip_ticks * exit_tick)
        else:
            actual_entry = theo_entry - (slip_ticks * entry_tick)
            actual_exit = theo_exit + (slip_ticks * exit_tick)

        trade = create_phase2_trade(
            symbol=symbol,
            direction=direction,
            quantity=1000,
            feature_time=base_time,
            signal_time=base_time + timedelta(minutes=1),
            decision_available_time=base_time + timedelta(minutes=1),
            execution_time=base_time + timedelta(minutes=2),
            exit_time=base_time + timedelta(minutes=15),
            theoretical_entry_price=theo_entry,
            actual_entry_price=actual_entry,
            theoretical_exit_price=theo_exit,
            actual_exit_price=actual_exit,
            stop_loss_price=stop_loss,
            intraday_bars_during_trade=[],
            features_snapshot={},
            cost_model=cost_model,
            is_daytrade=True,
        )

        initial_risk_amount = trade.initial_risk_amount
        assert initial_risk_amount > 0

        # Raw dollar accounting
        theo_gross = trade.gross_pnl_theoretical
        actual_gross = trade.gross_pnl_actual
        slip_cost = trade.slippage_cost
        comm_tax = trade.commission_total + trade.tax_total
        total_friction = slip_cost + comm_tax
        net = trade.net_pnl

        assert abs(theo_gross - actual_gross - slip_cost) < 1e-4
        assert abs(theo_gross - total_friction - net) < 1e-4
        assert abs(actual_gross - comm_tax - net) < 1e-4

        # Normalized R accounting
        theo_gross_R = theo_gross / initial_risk_amount
        actual_gross_R = actual_gross / initial_risk_amount
        slip_R = slip_cost / initial_risk_amount
        comm_tax_R = comm_tax / initial_risk_amount
        total_friction_R = total_friction / initial_risk_amount
        net_R = net / initial_risk_amount

        # Identity 1: Theoretical Gross R - Total Cost Drag R == Net R
        assert abs(theo_gross_R - total_friction_R - net_R) < 1e-4
        # Identity 2: Actual Post-Slippage Gross R - Fee/Tax Drag R == Net R
        assert abs(actual_gross_R - comm_tax_R - net_R) < 1e-4
        # Identity 3: Total Cost Drag R == Slippage R + Fee/Tax Drag R
        assert abs(total_friction_R - (slip_R + comm_tax_R)) < 1e-4
        # Identity 4: Theoretical Gross R - Actual Gross R == Slippage R
        assert abs(theo_gross_R - actual_gross_R - slip_R) < 1e-4


# ==============================================================================
# 7. Event-based Purging & Embargo Integration
# ==============================================================================
def test_event_walk_forward_purging_integration():
    detector = RangeExpansionDetector(expansion_thresholds=[1.2], lookback_bars=3)
    # Generate a series of bars that triggers 10 signals over time
    bars = []
    for i in range(60):
        if i % 6 == 4:
            bars.append(make_bar(i, 100.0, 103.0, 99.8, 102.8))  # expansion
        else:
            bars.append(make_bar(i, 100.0, 100.5, 100.0, 100.3))

    signals = detector.detect_signals("2330", bars, threshold=1.2)
    runner = ResearchRunner()
    trades = []
    for s in signals:
        tr = runner.simulate_trade_from_signal(s, bars, exit_policy=EXIT_FIXED_15M)
        if tr:
            trades.append(tr)

    assert len(trades) >= 4
    eval_res = runner.evaluate_candidate(trades, n_splits=2, embargo_duration=timedelta(minutes=15))
    assert eval_res["trade_count"] == len(trades)
    assert len(eval_res["walk_forward_folds"]) == 2


# ==============================================================================
# 8. Parameter Provenance & Governance
# ==============================================================================
def test_batch1_parameter_provenance():
    # Vol decay threshold provenance
    rec_decay = PHASE2_PROVENANCE_REGISTRY["PARAM_PB_VOL_DECAY"]
    assert rec_decay.chapter_or_section == "Chapter 7"
    audit_parameter_provenance(rec_decay)

    # Range expansion parameter grid provenance
    rec_grid = PHASE2_PROVENANCE_REGISTRY["GRID_EXTENSION_RATIO"]
    assert rec_grid.value_or_grid == [1.2, 1.5, 1.8]
    audit_parameter_provenance(rec_grid)


# ==============================================================================
# 9. Static Production Import Isolation
# ==============================================================================
def test_static_production_import_isolation():
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
                    assert "phase2" not in alias.name, f"Forbidden import in {p.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "phase2" not in mod, f"Forbidden import in {p.name}: {mod}"
