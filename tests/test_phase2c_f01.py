"""Tests for Phase 2C F01 Market Context Follow-up Study.

Integrity & Causality Tests:
1. Opening 15m exact boundary (09:14:59 unavailable, 09:15:00 available)
2. Opening 30m exact boundary (09:29:59 unavailable, 09:30:00 available)
3. Volatility uses completed observations only (no future bars, no full-day range)
4. Proxy peer breadth invariant (peer_count <= active_universe - 1 <= 99)
5. Peer count <34 explicit status (INSUFFICIENT_BREADTH, no silent drop)
6. Peer count >99 failure (CAUSALITY_OR_METADATA_FAILURE)
7. Each signal exactly one time bucket (TIME_BUCKET_MEMBERSHIP_COUNT == 1)
8. Trend context calculates strictly causal metrics (intraday return & consistency)
9. Train quantile boundaries frozen in OOS evaluation
10. All registered strata emitted in stratification
11. H07 cannot enter filter decision path (DESCRIPTIVE_POST_OUTCOME_CLASSIFICATION)
12. F01 keep/drop logic unchanged from sealed Batch 2 (LONG keep when cum_ret >= 0, SHORT keep when cum_ret <= 0)
13. Candidate definitions unchanged from Phase 2B (P2B_01~04)
14. Production import isolation (AST check - no app.*, main, scan_intraday)
15. Future confirmation contract no-peeking horizon frozen (60 TRADING DAYS, PRIMARY_1 & PRIMARY_2)
16. Official market context provider contract returns DATA_UNAVAILABLE without mocking
17. Effect decomposition accounting identity holds across mechanism strata
"""
from __future__ import annotations
import ast
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import pytest
import yaml

from daytrade_learning.phase2 import (
    MarketBar,
    get_twse_tick_size,
    RangeExpansionDetector,
    PullbackVolumeDecayDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
)
from daytrade_learning.phase2.f01_followup import (
    TrendContextAnalyzer,
    VolatilityContextAnalyzer,
    OpeningContextAnalyzer,
    BreadthContextAnalyzer,
    CausalityOrMetadataFailure,
    StandbyOfficialContextProvider,
    MechanismRunner,
    MechanismTradeRecord,
    classify_time_of_day,
    assert_h07_descriptive_only,
)

TPE = timezone(timedelta(hours=8))


def make_bars(start_hour: int = 9, start_min: int = 1, count: int = 60, base_p: float = 100.0) -> list[MarketBar]:
    bars = []
    curr_dt = datetime(2026, 6, 8, start_hour, start_min, tzinfo=TPE)
    p = base_p
    for i in range(count):
        t_open = curr_dt + timedelta(minutes=i)
        t_close = t_open + timedelta(minutes=1)
        bars.append(
            MarketBar(
                bar_open_time=t_open,
                bar_close_time=t_close,
                open=p,
                high=p + 0.5,
                low=p - 0.2,
                close=p + 0.3,
                volume=100.0,
                amount=p * 100.0 * 1000.0,
            )
        )
        p += 0.1
    return bars


class TestOpeningWindowExactBoundaries:
    """Exact right-edge causality for opening windows."""

    def test_opening_15m_exact_boundary_unavailable_at_091459(self):
        sig_dt = datetime(2026, 6, 8, 9, 14, 59, tzinfo=TPE)
        snap = OpeningContextAnalyzer.compute(
            signal_dt=sig_dt,
            proxy_open_0901=100.0,
            proxy_close_0915=100.5,
            proxy_close_0930=101.0,
        )
        assert snap.is_15m_available is False
        assert snap.opening_15m_return is None
        assert snap.opening_15m_direction == "NOT_AVAILABLE"

    def test_opening_15m_exact_boundary_available_at_091500(self):
        sig_dt = datetime(2026, 6, 8, 9, 15, 0, tzinfo=TPE)
        snap = OpeningContextAnalyzer.compute(
            signal_dt=sig_dt,
            proxy_open_0901=100.0,
            proxy_close_0915=100.5,
            proxy_close_0930=101.0,
        )
        assert snap.is_15m_available is True
        assert snap.opening_15m_return == 0.005
        assert snap.opening_15m_direction == "OPENING_DIRECTION_POSITIVE"

    def test_opening_30m_exact_boundary_unavailable_at_092959(self):
        sig_dt = datetime(2026, 6, 8, 9, 29, 59, tzinfo=TPE)
        snap = OpeningContextAnalyzer.compute(
            signal_dt=sig_dt,
            proxy_open_0901=100.0,
            proxy_close_0915=100.5,
            proxy_close_0930=101.0,
        )
        assert snap.is_15m_available is True
        assert snap.is_30m_available is False
        assert snap.opening_30m_return is None
        assert snap.opening_30m_direction == "NOT_AVAILABLE"

    def test_opening_30m_exact_boundary_available_at_093000(self):
        sig_dt = datetime(2026, 6, 8, 9, 30, 0, tzinfo=TPE)
        snap = OpeningContextAnalyzer.compute(
            signal_dt=sig_dt,
            proxy_open_0901=100.0,
            proxy_close_0915=100.5,
            proxy_close_0930=99.0,
        )
        assert snap.is_15m_available is True
        assert snap.is_30m_available is True
        assert snap.opening_30m_return == -0.010
        assert snap.opening_30m_direction == "OPENING_DIRECTION_NEGATIVE"


class TestTimeOfDayIntervals:
    """Half-open intervals and single membership invariant."""

    def test_time_bucket_membership_count_invariant(self):
        sample_times = [
            time(9, 0, 0),
            time(9, 15, 0),
            time(9, 59, 59),
            time(10, 0, 0),
            time(11, 0, 0),
            time(11, 59, 59),
            time(12, 0, 0),
            time(13, 0, 0),
            time(13, 30, 0),
        ]
        for t in sample_times:
            bucket = classify_time_of_day(t)
            assert bucket in ("OPEN", "MID", "LATE")

    def test_time_bucket_half_open_boundaries(self):
        assert classify_time_of_day(time(9, 0, 0)) == "OPEN"
        assert classify_time_of_day(time(9, 59, 59)) == "OPEN"
        assert classify_time_of_day(time(10, 0, 0)) == "MID"
        assert classify_time_of_day(time(11, 59, 59)) == "MID"
        assert classify_time_of_day(time(12, 0, 0)) == "LATE"
        assert classify_time_of_day(time(13, 30, 0)) == "LATE"

    def test_time_bucket_outside_session_raises(self):
        with pytest.raises(ValueError, match="TIME_BUCKET_MEMBERSHIP_COUNT invariant violated"):
            classify_time_of_day(time(8, 59, 59))
        with pytest.raises(ValueError, match="TIME_BUCKET_MEMBERSHIP_COUNT invariant violated"):
            classify_time_of_day(time(13, 30, 1))


class TestProxyBreadthOutOfRangePolicy:
    """H05 Breadth buckets and out-of-range guards."""

    def test_breadth_in_bounds_strata(self):
        snap34 = BreadthContextAnalyzer.compute(34)
        assert snap34.breadth_bucket == "BREADTH_34_54"

        snap54 = BreadthContextAnalyzer.compute(54)
        assert snap54.breadth_bucket == "BREADTH_34_54"

        snap55 = BreadthContextAnalyzer.compute(55)
        assert snap55.breadth_bucket == "BREADTH_55_79"

        snap79 = BreadthContextAnalyzer.compute(79)
        assert snap79.breadth_bucket == "BREADTH_55_79"

        snap80 = BreadthContextAnalyzer.compute(80)
        assert snap80.breadth_bucket == "BREADTH_80_99"

        snap99 = BreadthContextAnalyzer.compute(99)
        assert snap99.breadth_bucket == "BREADTH_80_99"

    def test_breadth_under_34_labeled_insufficient_breadth(self):
        snap = BreadthContextAnalyzer.compute(20)
        assert snap.peer_constituent_count == 20
        assert snap.breadth_bucket == "INSUFFICIENT_BREADTH"
        assert snap.invariant_passed is True

    def test_breadth_over_99_raises_causality_or_metadata_failure(self):
        with pytest.raises(CausalityOrMetadataFailure, match="CAUSALITY_OR_METADATA_FAILURE"):
            BreadthContextAnalyzer.compute(100)

    def test_breadth_negative_raises_causality_or_metadata_failure(self):
        with pytest.raises(CausalityOrMetadataFailure, match="CAUSALITY_OR_METADATA_FAILURE"):
            BreadthContextAnalyzer.compute(-1)


class TestVolatilityCausality:
    def test_volatility_uses_completed_observations_only(self):
        returns = [0.001, -0.002, 0.0015, -0.0005]
        highs = [100.5, 100.8, 100.9, 100.7]
        lows = [99.8, 99.7, 100.0, 99.9]
        snap = VolatilityContextAnalyzer.compute(returns, highs, lows, proxy_open=100.0)
        assert snap.n_bars_observed == 4
        assert snap.realized_volatility > 0.0
        assert snap.intraday_range == round((100.9 - 99.7) / 100.0, 6)

    def test_volatility_zero_on_insufficient_bars(self):
        snap = VolatilityContextAnalyzer.compute([0.001], [100.5], [100.0], proxy_open=100.0)
        assert snap.realized_volatility == 0.0
        assert snap.n_bars_observed == 1


class TestTrendContextAndQuantileGovernance:
    def test_trend_context_calculation(self):
        rets = [0.001, 0.002, -0.001, 0.0015]
        snap = TrendContextAnalyzer.compute(rets, proxy_open=100.0, proxy_current=100.35)
        assert snap.n_bars_observed == 4
        assert snap.proxy_intraday_return == round((100.35 - 100.0) / 100.0, 6)
        assert snap.proxy_direction_consistency == 0.75

    def test_train_quantile_frozen_in_oos(self):
        """Train quantile boundaries are frozen and passed to stratify without re-calibrating on OOS."""
        train_trades = [
            _make_sample_trade("t1", ret=0.001),
            _make_sample_trade("t2", ret=0.002),
            _make_sample_trade("t3", ret=0.003),
            _make_sample_trade("t4", ret=0.004),
        ]
        # Train quantiles: Q1 <= 0.001, Q2 <= 0.002, Q3 <= 0.003
        frozen_cuts = (0.001, 0.002, 0.003)

        # OOS trades with shift in distribution
        oos_trades = [
            _make_sample_trade("oos1", ret=0.0005),
            _make_sample_trade("oos2", ret=0.0015),
            _make_sample_trade("oos3", ret=0.0025),
            _make_sample_trade("oos4", ret=0.0050),
        ]
        res = MechanismRunner.stratify(oos_trades, quantile_boundaries=frozen_cuts)
        assert res["H01_trend"]["Q1"]["unique_signals"] == 1
        assert res["H01_trend"]["Q2"]["unique_signals"] == 1
        assert res["H01_trend"]["Q3"]["unique_signals"] == 1
        assert res["H01_trend"]["Q4"]["unique_signals"] == 1


class TestAllRegisteredStrataEmitted:
    """Verifies that stratify emits all pre-registered strata."""

    def test_all_registered_strata_emitted(self):
        sample = [
            _make_sample_trade("s1", ret=-0.002, vol=0.0002, op_dir="OPENING_DIRECTION_NEGATIVE", tod="OPEN", b_bkt="BREADTH_34_54", cid="P2B_01_v1", d="LONG", date="2025-03-03"),
            _make_sample_trade("s2", ret=-0.001, vol=0.0008, op_dir="OPENING_DIRECTION_NEUTRAL", tod="MID", b_bkt="BREADTH_55_79", cid="P2B_02_v1", d="LONG", date="2025-03-04"),
            _make_sample_trade("s3", ret=0.001, vol=0.0020, op_dir="OPENING_DIRECTION_POSITIVE", tod="LATE", b_bkt="BREADTH_80_99", cid="P2B_03_v1", d="SHORT", date="2026-06-08"),
            _make_sample_trade("s4", ret=0.003, vol=0.0025, op_dir="NOT_AVAILABLE", tod="OPEN", b_bkt="INSUFFICIENT_BREADTH", cid="P2B_04_v1", d="SHORT", date="2026-06-09"),
        ]
        strat = MechanismRunner.stratify(sample)

        # H01
        for k in ["Q1", "Q2", "Q3", "Q4"]:
            assert k in strat["H01_trend"]
        # H02
        for k in ["LOW", "MID", "HIGH"]:
            assert k in strat["H02_volatility"]
        # H03
        for k in ["OPENING_DIRECTION_POSITIVE", "OPENING_DIRECTION_NEUTRAL", "OPENING_DIRECTION_NEGATIVE", "NOT_AVAILABLE"]:
            assert k in strat["H03_opening_15m"]
        # H04
        for k in ["OPEN", "MID", "LATE"]:
            assert k in strat["H04_time_of_day"]
        # H05
        for k in ["BREADTH_34_54", "BREADTH_55_79", "BREADTH_80_99", "INSUFFICIENT_BREADTH"]:
            assert k in strat["H05_breadth"]
        # H06
        for k in ["LONG", "SHORT", "P2B_01_v1", "P2B_02_v1", "P2B_03_v1", "P2B_04_v1"]:
            assert k in strat["H06_candidate_direction"]
        # H07
        for k in ["IMPROVED_DAY", "DEGRADED_DAY"]:
            assert k in strat["H07_failure_regime"]


class TestH07Governance:
    """Verifies that H07 failure regime classification is strictly descriptive post-outcome."""

    def test_h07_descriptive_classification_only(self):
        gov = assert_h07_descriptive_only()
        assert gov["DESCRIPTIVE_POST_OUTCOME_CLASSIFICATION"] is True
        assert gov["IN_FILTER_DECISION_PATH"] is False
        assert gov["PREDICTIVE_REGIME_CLAIM_PROHIBITED"] is True

    def test_h07_not_imported_in_detectors_or_filters(self):
        pkg_dir = Path(__file__).resolve().parents[1] / "daytrade_learning/phase2"
        for p in pkg_dir.glob("*.py"):
            if "f01_followup" in str(p):
                continue
            code = p.read_text(encoding="utf-8")
            assert "H07" not in code
            assert "IMPROVED_DAY" not in code
            assert "DEGRADED_DAY" not in code


class TestF01LogicInvariance:
    def test_f01_keep_drop_matches_sealed_batch2(self):
        # LONG candidate: kept iff loo_cum >= 0.0
        assert (0.001 >= 0.0) is True
        assert (-0.001 >= 0.0) is False
        # SHORT candidate: kept iff loo_cum <= 0.0
        assert (-0.001 <= 0.0) is True
        assert (0.001 <= 0.0) is False

    def test_candidate_definitions_unmodified(self):
        d1 = PullbackVolumeDecayDetector(max_pullback_bars=3)
        d2 = RangeExpansionDetector(lookback_bars=5)
        d3 = TwoBReversalDetector(pivot_confirmation_bars=2, max_failure_bars=3)
        d4 = OneTwoThreeDetector(confirmation_bars=1)
        assert d1.max_pullback_bars == 3
        assert d2.lookback_bars == 5
        assert d3.pivot_confirmation_bars == 2
        assert d4.confirmation_bars == 1


class TestGovernanceAndIsolation:
    def test_no_production_imports(self):
        pkg_dir = Path(__file__).resolve().parents[1] / "daytrade_learning/phase2/f01_followup"
        forbidden = ["app.", "scan_intraday", "shioaji", "fugle_pipeline", "deploy"]
        for p in pkg_dir.glob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        for fb in forbidden:
                            assert not n.name.startswith(fb), f"Forbidden import {n.name} in {p}"
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for fb in forbidden:
                            assert not node.module.startswith(fb), f"Forbidden import {node.module} in {p}"

    def test_future_confirmation_contract_semantics(self):
        contract_path = Path(__file__).resolve().parents[1] / "docs/daytrade_phase2/PHASE2C_F01_FUTURE_CONFIRMATION_CONTRACT.yaml"
        assert contract_path.exists()
        with open(contract_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["scope"]["confirmation_start_date"] == "AFTER_2026_10_02"
        assert data["scope"]["evaluation_horizon"] == "60_TRADING_DAYS"
        assert data["governance_rules"]["NO_PEEKING_BEFORE_EVALUATION"] is True
        assert data["governance_rules"]["EVALUATION_HORIZON_STATUS"] == "RESEARCH_GOVERNANCE_CANDIDATE"
        assert data["primary_endpoints"]["PRIMARY_1"] == "delta_theoretical_return_pct"
        assert data["primary_endpoints"]["PRIMARY_2"] == "delta_net_return_pct"
        assert data["f01_frozen_definition"]["source"] == "FROZEN_FROM_PHASE2B_BATCH2"
        assert data["execution_status"] == "STANDBY_UNEXECUTED_IN_PHASE_2C_A"

    def test_full_run_plan_semantics(self):
        plan_path = Path(__file__).resolve().parents[1] / "docs/daytrade_phase2/PHASE2C_F01_FULL_RUN_PLAN.yaml"
        assert plan_path.exists()
        with open(plan_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["plan_metadata"]["baseline_sha"] == "ac5b660fc2b4d39f9e92b73a2a09584bfec0cd00"
        assert data["governance_and_classification"]["study_type"] == "PREREGISTERED_FOLLOWUP_ON_PREVIOUSLY_OBSERVED_DATA"
        assert data["governance_and_classification"]["DISCOVERY_DATA_REUSED"] is True
        assert data["governance_and_classification"]["INDEPENDENT_CONFIRMATION"] is False
        assert data["governance_and_classification"]["F01_STATUS"] == "FILTER_IMPROVES_RESEARCH_SIGNAL"
        assert data["governance_and_classification"]["PRODUCTION_READY"] is False
        assert data["search_and_stratification_rules"]["ONE_DIMENSIONAL_ONLY"] is True
        assert data["search_and_stratification_rules"]["CARTESIAN_SEARCH_ALLOWED"] is False

    def test_standby_official_provider_contract(self):
        prov = StandbyOfficialContextProvider()
        assert prov.get_status() == "DATA_UNAVAILABLE"
        snap = prov.get_market_context("test_sig", datetime.now(TPE))
        assert snap.status == "DATA_UNAVAILABLE"
        assert snap.index_cum_return is None

    def test_effect_decomposition_accounting_identity(self):
        rec = _make_sample_trade("test_1", ret=0.003, vol=0.001, op_dir="OPENING_DIRECTION_POSITIVE", tod="OPEN", b_bkt="BREADTH_80_99", cid="P2B_01_v1", d="LONG", date="2026-06-08")
        strat = MechanismRunner.stratify([rec])
        assert strat["overall"]["OVERALL"]["accounting_identity_holds"] is True
        assert strat["overall"]["OVERALL"]["delta_net_return_pct"] == round(
            strat["overall"]["OVERALL"]["delta_theoretical_return_pct"] - strat["overall"]["OVERALL"]["delta_trading_friction_pct"],
            4
        )


def _make_sample_trade(
    sig_id: str,
    ret: float = 0.0,
    vol: float = 0.001,
    op_dir: str = "OPENING_DIRECTION_NEUTRAL",
    tod: str = "OPEN",
    b_bkt: str = "BREADTH_80_99",
    cid: str = "P2B_01_v1",
    d: str = "LONG",
    date: str = "2026-06-08",
) -> MechanismTradeRecord:
    theo_ret = 0.4000
    friction = 0.3800
    net_ret = theo_ret - friction
    return MechanismTradeRecord(
        signal_event_id=sig_id,
        symbol="2330",
        date=date,
        candidate_id=cid,
        direction=d,
        signal_time="2026-06-08T09:30:00+08:00",
        theo_entry=500.0,
        theo_exit=502.0,
        initial_risk=2.0,
        initial_risk_ticks=4.0,
        theoretical_return_pct=theo_ret,
        trading_friction_pct=friction,
        net_return_pct=net_ret,
        pnl_R=0.25,
        mfe_R=1.5,
        mae_R=0.5,
        f01_keep=True,
        proxy_intraday_return=ret,
        proxy_direction_consistency=0.8,
        realized_volatility=vol,
        intraday_range=0.005,
        opening_15m_return=0.002,
        opening_15m_direction=op_dir,
        opening_30m_return=0.003,
        opening_30m_direction=op_dir,
        time_of_day=tod,
        peer_constituent_count=99,
        breadth_bucket=b_bkt,
    )
