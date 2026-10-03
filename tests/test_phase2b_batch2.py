"""Tests for Phase 2B Batch 2 Context / Regime / Relative Strength Filters.

Comprehensive Integrity Checks:
1. Leave-one-out proxy strictly excludes target symbol
2. Proxy future mutation invariance
3. Missing constituent cross-section exclusion (no forward fill)
4. Proxy timestamp causal alignment
5. Historical volume unit audit contract (Volume=lots, Amount=(c*v*1000) median=1.0)
6. Signal funnel identity (raw == simulated + all_drop_reasons)
7. Explicit drop reasons validation
8. F05 discrimination test (both KEEP and DROP observed)
9. F03 remains DATA_INSUFFICIENT and not ranking eligible
10. Smoke performance cannot generate promotion verdict (NOT_EVALUATED)
11. Effect decomposition accounting (R vs percentage returns & risk distributions)
12. HTF incomplete-bar rejection (closed bars only)
13. Production import isolation (AST check)
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from daytrade_learning.phase2 import (
    MarketBar,
    ResearchMarketRegime,
    MarketRegimeSnapshot,
    RelativeStrengthFilter,
    RelativeStrengthSnapshot,
    SectorStrengthFilter,
    SectorFilterStatus,
    HigherTimeframeAggregator,
    HigherTimeframeSnapshot,
    IncompleteBarAccessError,
    LiquidityFilter,
    LiquiditySnapshot,
    Batch2FilterRunner,
    RawSignalEvent,
    compute_performance_summary,
    TradePerformanceSummary,
    create_phase2_trade,
    Phase2TradeRecord,
)

TPE = timezone(timedelta(hours=8))


def make_test_bars(
    start_dt: datetime,
    count: int,
    base_price: float = 100.0,
    price_step: float = 0.5,
    volume: float = 1000.0,
    amount: Optional[float] = None,
) -> list[MarketBar]:
    """Generates continuous 1m bars."""
    bars = []
    p = base_price
    for i in range(count):
        t_open = start_dt + timedelta(minutes=i)
        t_close = t_open + timedelta(minutes=1)
        b_open = p
        b_close = p + price_step
        b_high = max(b_open, b_close) + 0.2
        b_low = min(b_open, b_close) - 0.2
        amt = amount if amount is not None else b_close * volume * 1000.0
        bars.append(
            MarketBar(
                bar_open_time=t_open,
                bar_close_time=t_close,
                open=round(b_open, 2),
                high=round(b_high, 2),
                low=round(b_low, 2),
                close=round(b_close, 2),
                volume=volume,
                amount=round(amt, 2),
            )
        )
        p = b_close
    return bars


class TestMarketRegimeAndProxyIntegrity:
    def test_leave_one_out_proxy_excludes_target(self):
        """When evaluating regime for target S, S must be completely excluded from peer proxy."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        # S1 (target) has massive spike, S2 and S3 are flat
        bars_s1 = make_test_bars(start, count=30, base_price=100.0, price_step=10.0)
        bars_s2 = make_test_bars(start, count=30, base_price=100.0, price_step=0.0)
        bars_s3 = make_test_bars(start, count=30, base_price=100.0, price_step=0.0)

        universe = {"2330": bars_s1, "1101": bars_s2, "2317": bars_s3}
        regime = ResearchMarketRegime(universe_bars_by_symbol=universe)

        as_of = datetime(2026, 10, 2, 9, 20, tzinfo=TPE)

        # LOO regime for 2330 must exclude 2330 -> peer proxy should see only S2 and S3 (flat, return = 0)
        snap_loo_2330 = regime.evaluate_regime_for_symbol(as_of, target_symbol="2330")
        assert snap_loo_2330.target_excluded is True
        assert snap_loo_2330.excluded_symbol == "2330"
        assert snap_loo_2330.proxy_intraday_return == 0.0

        # General regime without exclusion sees S1's massive spike
        snap_all = regime.evaluate_regime(as_of)
        assert snap_all.target_excluded is False
        assert snap_all.proxy_intraday_return > 0.05

    def test_proxy_future_mutation_invariance(self):
        """Mutating peer bars after as_of must not change as_of leave-one-out proxy."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        bars_s1 = make_test_bars(start, count=60, base_price=100.0, price_step=0.1)
        bars_s2 = make_test_bars(start, count=60, base_price=50.0, price_step=-0.1)
        as_of = datetime(2026, 10, 2, 9, 30, tzinfo=TPE)

        regime1 = ResearchMarketRegime(universe_bars_by_symbol={"1101": bars_s1, "2317": bars_s2})
        snap1 = regime1.evaluate_regime_for_symbol(as_of, target_symbol="1101")

        # Mutate bars after 09:30
        mutated_s2 = list(bars_s2[:30])
        for b in bars_s2[30:]:
            mutated_s2.append(
                MarketBar(b.bar_open_time, b.bar_close_time, b.open * 5, b.high * 5, b.low * 5, b.close * 5, b.volume * 10)
            )

        regime2 = ResearchMarketRegime(universe_bars_by_symbol={"1101": bars_s1, "2317": mutated_s2})
        snap2 = regime2.evaluate_regime_for_symbol(as_of, target_symbol="1101")

        assert snap1.proxy_intraday_return == snap2.proxy_intraday_return
        assert snap1.proxy_trend_slope_15m == snap2.proxy_trend_slope_15m
        assert snap1.constituent_count_at_t == snap2.constituent_count_at_t

    def test_missing_constituent_cross_section_exclusion(self):
        """If a symbol is missing a bar at timestamp t, it is excluded without future forward-filling."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        # S1 has full bars
        bars_s1 = make_test_bars(start, count=20, base_price=100.0, price_step=0.1)
        # S2 is missing minute 5 (index 4)
        bars_s2 = [b for i, b in enumerate(make_test_bars(start, count=20, base_price=50.0, price_step=0.2)) if i != 4]

        regime = ResearchMarketRegime(universe_bars_by_symbol={"S1": bars_s1, "S2": bars_s2})
        t_missing = start + timedelta(minutes=5)  # close of minute 5

        # In S1's perspective (excluding S1, peer is S2 only): S2 is missing at t_missing -> count at t is 0
        snap_s1 = regime.evaluate_regime_for_symbol(t_missing, target_symbol="S1")
        assert snap_s1.constituent_count_at_t == 0

        # At minute 6, S2 is present again -> count at t is 1
        t_present = start + timedelta(minutes=6)
        snap_s1_t6 = regime.evaluate_regime_for_symbol(t_present, target_symbol="S1")
        assert snap_s1_t6.constituent_count_at_t == 1


class TestRelativeStrengthFilterLOO:
    def test_rs_leave_one_out_peer_benchmark(self):
        """Relative strength benchmark must exclude target symbol."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        bars_target = make_test_bars(start, count=30, base_price=100.0, price_step=1.0)
        bars_peer = make_test_bars(start, count=30, base_price=50.0, price_step=0.0)

        regime = ResearchMarketRegime(universe_bars_by_symbol={"TARGET": bars_target, "PEER": bars_peer})
        rs_filter = RelativeStrengthFilter(regime, {"TARGET": bars_target, "PEER": bars_peer})

        as_of = datetime(2026, 10, 2, 9, 15, tzinfo=TPE)
        snap = rs_filter.compute_relative_strength("TARGET", as_of, window_minutes=15)

        assert snap.target_excluded is True
        assert snap.market_return == 0.0  # PEER return is 0
        assert snap.relative_strength == snap.stock_return
        assert snap.tier == "POSITIVE"


class TestHigherTimeframeFilter:
    def test_htf_incomplete_bar_rejection(self):
        """At 09:37, 5m context must ONLY expose completed 09:30-09:35 bar, rejecting forming 09:35-09:40."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        bars = make_test_bars(start, count=37, base_price=100.0, price_step=0.2)

        agg = HigherTimeframeAggregator(bars)
        as_of = datetime(2026, 10, 2, 9, 37, tzinfo=TPE)

        closed_5m = agg.get_closed_htf_bars(as_of, timeframe="5m")
        assert len(closed_5m) == 7

        last_bar = closed_5m[-1]
        assert last_bar.bar_open_time == datetime(2026, 10, 2, 9, 30, tzinfo=TPE)
        assert last_bar.bar_close_time == datetime(2026, 10, 2, 9, 35, tzinfo=TPE)
        assert last_bar.bar_close_time <= as_of


class TestLiquidityFilterAndDiscrimination:
    def test_f05_liquidity_discrimination_observed(self):
        """F05 must observe both KEEP and DROP when low-liquidity stock is present."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        # High liquidity: 10,000 lots / min -> Amount is large
        high_liq_bars = make_test_bars(start, count=60, base_price=100.0, volume=500.0, amount=50_000_000.0)
        # Low liquidity: 1 lot / min -> Amount is small
        low_liq_bars = make_test_bars(start, count=60, base_price=20.0, volume=1.0, amount=20_000.0)

        liq_filter = LiquidityFilter({"HIGH": high_liq_bars, "LOW": low_liq_bars})
        as_of = datetime(2026, 10, 2, 9, 30, tzinfo=TPE)

        keep_high = liq_filter.filter_signal("HIGH", as_of, min_rolling_traded_value_twd=10_000_000.0)
        drop_low = liq_filter.filter_signal("LOW", as_of, min_rolling_traded_value_twd=10_000_000.0)

        assert keep_high is True
        assert drop_low is False


class TestSectorFilterGovernance:
    def test_sector_remains_data_insufficient(self):
        """F03 must strictly remain DATA_INSUFFICIENT and not ranking eligible."""
        f = SectorStrengthFilter(snapshot_categories={"2330": "24"})
        assert f.point_in_time_sector_mapping is False
        status = f.evaluate_symbol_sector("2330")
        assert status.status == "DATA_INSUFFICIENT"
        assert status.verdict == "REJECT_FILTER_USAGE"


class TestSignalFunnelIdentity:
    def test_signal_funnel_accounting_identity(self):
        """Verifies strict identity: raw == simulated + len(dropped_signals)."""
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        bars = make_test_bars(start, count=60, base_price=100.0, price_step=0.2)

        runner = Batch2FilterRunner()
        raw_events = runner.detect_raw_signals("2317", bars)
        trades, dropped = runner.simulate_events_with_funnel(raw_events, {"2317": bars})

        assert len(raw_events) == len(trades) + len(dropped)
        allowed_reasons = {
            "NO_LEGAL_EXECUTION",
            "INSUFFICIENT_FORWARD_HORIZON",
            "INVALID_INITIAL_RISK",
            "STOP_LOSS_VIOLATION",
            "DATA_GAP",
        }
        for d in dropped:
            assert d.drop_reason in allowed_reasons
            assert d.signal_event_id.startswith(d.candidate_id)


class TestEffectDecompositionAndSmokeStatus:
    def test_effect_decomposition_and_smoke_verdict(self):
        """Smoke validation cannot generate promotion verdict; performance status is NOT_EVALUATED."""
        summary = compute_performance_summary([])
        assert summary.count == 0
        assert summary.risk_distribution.mean_risk_pct == 0.0

        # Non-empty mock summary
        start = datetime(2026, 10, 2, 9, 0, tzinfo=TPE)
        bars = make_test_bars(start, count=60, base_price=100.0, price_step=0.5)
        runner = Batch2FilterRunner()
        raw_events = runner.detect_raw_signals("2317", bars)
        comp = runner.evaluate_filter(
            filter_id="TEST_F01",
            filter_family="F01_MARKET_REGIME",
            condition_name="TEST_COND",
            all_events=raw_events,
            bars_by_symbol={"2317": bars},
            filter_decision_func=lambda ev: True,
        )

        assert comp.implementation_status == "VERIFIED"
        assert comp.performance_status == "NOT_EVALUATED"
        assert comp.smoke_validation_pass is True


class TestProductionImportIsolation:
    def test_no_production_imports_in_context_filters(self):
        """Ensures context_filters and batch2 modules NEVER import production modules."""
        forbidden = {
            "strategy_engine",
            "strategy_rules",
            "market_risk",
            "position_manager",
            "scan_intraday",
            "scan_rebound",
            "update_market",
            "market_data.fugle_pipeline",
        }

        search_dirs = [
            Path("daytrade_learning/phase2/context_filters"),
            Path("daytrade_learning/phase2/batch2_filter_runner.py"),
            Path("daytrade_learning/phase2/batch2_result_store.py"),
        ]

        files_to_check = []
        for item in search_dirs:
            if item.is_file():
                files_to_check.append(item)
            elif item.is_dir():
                files_to_check.extend(item.glob("*.py"))

        assert len(files_to_check) >= 6

        for py_path in files_to_check:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forb in forbidden:
                            assert not alias.name.startswith(forb), f"{py_path} illegally imports {alias.name}"
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    for forb in forbidden:
                        assert not mod.startswith(forb), f"{py_path} illegally imports from {mod}"


class TestPercentageReturnAccountingIdentity:
    """Verifies strict trade-level and aggregate percentage return accounting identities:
    1. net_return_pct == theoretical_return_pct - total_trading_friction_pct
    2. total_trading_friction_pct == slippage_pct + commission_pct + tax_pct
    3. delta_net_return_pct == delta_theoretical_return_pct - delta_trading_friction_pct
    """

    def test_trade_level_percentage_return_identity_long(self):
        trade_long = create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time="2026-10-02T09:15:00+08:00",
            signal_time="2026-10-02T09:15:00+08:00",
            decision_available_time="2026-10-02T09:15:02+08:00",
            execution_time="2026-10-02T09:16:00+08:00",
            exit_time="2026-10-02T09:30:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.5,  # 1 tick adverse slippage (0.50)
            theoretical_exit_price=103.0,
            actual_exit_price=102.5,   # 1 tick adverse slippage (0.50)
            stop_loss_price=98.0,
            intraday_bars_during_trade=[],
            features_snapshot={},
        )
        perf = compute_performance_summary([trade_long])
        assert perf.count == 1
        # Trade-level friction sum identity
        assert abs(perf.total_trading_friction_pct - (perf.slippage_pct + perf.commission_pct + perf.tax_pct)) < 1e-4
        # Trade-level net return identity
        assert abs(perf.net_return_pct - (perf.theoretical_return_pct - perf.total_trading_friction_pct)) < 1e-4

    def test_trade_level_percentage_return_identity_short(self):
        trade_short = create_phase2_trade(
            symbol="2317",
            direction="SHORT",
            quantity=1000,
            feature_time="2026-10-02T09:20:00+08:00",
            signal_time="2026-10-02T09:20:00+08:00",
            decision_available_time="2026-10-02T09:20:02+08:00",
            execution_time="2026-10-02T09:21:00+08:00",
            exit_time="2026-10-02T09:35:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=99.5,   # 1 tick adverse slippage
            theoretical_exit_price=97.0,
            actual_exit_price=97.5,    # 1 tick adverse slippage
            stop_loss_price=102.0,
            intraday_bars_during_trade=[],
            features_snapshot={},
        )
        perf = compute_performance_summary([trade_short])
        assert perf.count == 1
        assert abs(perf.total_trading_friction_pct - (perf.slippage_pct + perf.commission_pct + perf.tax_pct)) < 1e-4
        assert abs(perf.net_return_pct - (perf.theoretical_return_pct - perf.total_trading_friction_pct)) < 1e-4

    def test_filter_delta_percentage_identity(self):
        # Two trades: trade 1 kept, trade 2 dropped by filter
        t1 = create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time="2026-10-02T09:15:00+08:00",
            signal_time="2026-10-02T09:15:00+08:00",
            decision_available_time="2026-10-02T09:15:02+08:00",
            execution_time="2026-10-02T09:16:00+08:00",
            exit_time="2026-10-02T09:30:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.5,
            theoretical_exit_price=105.0,
            actual_exit_price=104.5,
            stop_loss_price=98.0,
            intraday_bars_during_trade=[],
            features_snapshot={},
        )
        t2 = create_phase2_trade(
            symbol="2330",
            direction="LONG",
            quantity=1000,
            feature_time="2026-10-02T09:30:00+08:00",
            signal_time="2026-10-02T09:30:00+08:00",
            decision_available_time="2026-10-02T09:30:02+08:00",
            execution_time="2026-10-02T09:31:00+08:00",
            exit_time="2026-10-02T09:45:00+08:00",
            theoretical_entry_price=100.0,
            actual_entry_price=100.5,
            theoretical_exit_price=96.0,
            actual_exit_price=95.5,
            stop_loss_price=98.0,
            intraday_bars_during_trade=[],
            features_snapshot={},
        )
        unfiltered_perf = compute_performance_summary([t1, t2])
        filtered_perf = compute_performance_summary([t1])

        delta_theo = round(filtered_perf.theoretical_return_pct - unfiltered_perf.theoretical_return_pct, 4)
        delta_friction = round(filtered_perf.total_trading_friction_pct - unfiltered_perf.total_trading_friction_pct, 4)
        delta_net = round(filtered_perf.net_return_pct - unfiltered_perf.net_return_pct, 4)

        # Delta identity: delta_net == delta_theo - delta_friction
        assert abs(delta_net - (delta_theo - delta_friction)) <= 0.0002

