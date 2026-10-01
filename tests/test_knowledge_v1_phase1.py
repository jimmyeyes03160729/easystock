"""Comprehensive unit, causality, look-ahead, equivalence and canonical provenance tests for Knowledge V1 Phase 1.

Verifies:
- FIX-1: Causality & delayed execution clock (+2s safety buffer, next-minute open, NO_CAUSAL_EXECUTION, forward returns from execution)
- FIX-2: Feature semantics & reuse equivalence (High <= Low -> None, dual VWAP scopes, zero aggressor volume -> None, production functions untouched)
- FIX-3 & Provenance Final Fix:
  - Canonical G19, G20, G21 preserved strictly with their original canonical meanings
  - New research parameters use validated canonical IDs G22, G23, G24
  - G05_RVOL_THRESHOLD mapped correctly to RESEARCH_GRID_G05
  - C02 scope creep (max_extension = 0.015) completely removed
  - CanonicalGridValidator fail-closed enforcement
  - Exact 09:30:30 intraminute boundary test
"""
import copy
import math
import unittest
from datetime import datetime, timedelta

from daytrade_learning.knowledge_v1.causal_tools import (
    CompletedBar,
    CausalBarSeries,
    CausalSwingSegmenter,
    parse_timestamp,
    TPE,
)
from daytrade_learning.knowledge_v1.features import KnowledgeV1Features
from daytrade_learning.knowledge_v1.registry import FeatureRegistry, RegistryStatus
from daytrade_learning.knowledge_v1.rules import (
    KnowledgeV1RuleEvaluator,
    KnowledgeV1Parameters,
    GridParameter,
)
from daytrade_learning.knowledge_v1.backtest_dataset import (
    ResearchDatasetBuilder,
    compute_causal_execution_time,
)
from daytrade_learning.knowledge_v1.validator import CanonicalGridValidator
from strategy_engine import upper_wick_ratio, bar_position, calculate_vwap


class TestKnowledgeV1FeatureSemantics(unittest.TestCase):
    """FIX-2: Feature semantics, defensive null policies, dual VWAP scopes, and production invariance."""

    def setUp(self):
        self.base_time = datetime(2026, 10, 2, 9, 0, 0, tzinfo=TPE)

    def test_candle_geometry_normal(self):
        """Normal bullish candle geometry produces correct ratios."""
        bar = CompletedBar(
            start_time=self.base_time,
            end_time=self.base_time + timedelta(minutes=1),
            open=100.0,
            high=105.0,
            low=98.0,
            close=104.0,
            volume=50.0,
        )
        self.assertEqual(KnowledgeV1Features.body_ratio(bar), 0.5714)
        self.assertEqual(KnowledgeV1Features.body_return_pct(bar), 0.04)
        self.assertEqual(KnowledgeV1Features.upper_shadow_ratio(bar), 0.1429)
        self.assertEqual(KnowledgeV1Features.lower_shadow_ratio(bar), 0.2857)
        self.assertEqual(KnowledgeV1Features.close_location_value(bar), 0.7143)

    def test_candle_geometry_high_le_low_returns_none(self):
        """FIX-2 Requirement: When High <= Low, geometry ratios MUST return None, not 0.0."""
        flat_bar = CompletedBar(
            start_time=self.base_time,
            end_time=self.base_time + timedelta(minutes=1),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=10.0,
        )
        self.assertIsNone(KnowledgeV1Features.body_ratio(flat_bar))
        self.assertIsNone(KnowledgeV1Features.upper_shadow_ratio(flat_bar))
        self.assertIsNone(KnowledgeV1Features.lower_shadow_ratio(flat_bar))
        self.assertIsNone(KnowledgeV1Features.close_location_value(flat_bar))

        # Inverted bar (High < Low)
        inverted_bar = {"open": 100.0, "high": 95.0, "low": 105.0, "close": 98.0}
        self.assertIsNone(KnowledgeV1Features.body_ratio(inverted_bar))
        self.assertIsNone(KnowledgeV1Features.upper_shadow_ratio(inverted_bar))
        self.assertIsNone(KnowledgeV1Features.lower_shadow_ratio(inverted_bar))
        self.assertIsNone(KnowledgeV1Features.close_location_value(inverted_bar))

    def test_production_functions_unmodified(self):
        """FIX-2 Constraint: Production functions must retain their existing behavior untouched."""
        flat_dict = {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
        # In strategy_engine, flat bar yields 0.0 for upper_wick_ratio and 0.5 for bar_position
        self.assertEqual(upper_wick_ratio(flat_dict), 0.0)
        self.assertEqual(bar_position(flat_dict), 0.5)

        # Knowledge V1 wrapper intercepts flat bar safely to return None
        self.assertIsNone(KnowledgeV1Features.upper_shadow_ratio(flat_dict))
        self.assertIsNone(KnowledgeV1Features.close_location_value(flat_dict))

        # Normal bar equivalence
        normal_dict = {"open": 50.0, "high": 55.0, "low": 48.0, "close": 53.0}
        self.assertEqual(KnowledgeV1Features.upper_shadow_ratio(normal_dict), round(upper_wick_ratio(normal_dict), 4))
        self.assertEqual(
            KnowledgeV1Features.close_location_value(normal_dict),
            round(2.0 * bar_position(normal_dict) - 1.0, 4)
        )

    def test_vwap_dual_scope_separation(self):
        """FIX-2 Requirement: Separate BAR_TYPICAL_PRICE_VWAP from BROKER_AVERAGE_PRICE."""
        bars = [
            {"high": 102.0, "low": 98.0, "close": 100.0, "volume": 100},  # typical = 100.0
            {"high": 106.0, "low": 102.0, "close": 104.0, "volume": 100},  # typical = 104.0
        ]
        bar_vwap = KnowledgeV1Features.calculate_bar_typical_vwap(bars)
        self.assertEqual(bar_vwap, 102.0)

        dist_bar = KnowledgeV1Features.dist_to_bar_vwap_pct(104.04, bars)
        self.assertEqual(dist_bar, 0.02)

        dist_broker = KnowledgeV1Features.dist_to_broker_avg_price_pct(104.04, 101.0)
        self.assertEqual(dist_broker, 0.030099)
        self.assertNotEqual(dist_bar, dist_broker)

        self.assertIsNone(KnowledgeV1Features.dist_to_broker_avg_price_pct(100.0, 0.0))
        self.assertIsNone(KnowledgeV1Features.dist_to_broker_avg_price_pct(100.0, None))

    def test_aggressor_flow_zero_volume_returns_none(self):
        """FIX-2 Requirement: When classified volume is zero, aggressor flow metrics return None."""
        self.assertIsNone(KnowledgeV1Features.aggressor_buy_share(0.0, 0.0))
        self.assertIsNone(KnowledgeV1Features.aggressor_sell_share(0.0, 0.0))
        self.assertIsNone(KnowledgeV1Features.aggressor_volume_delta(0.0, 0.0))

        # Valid non-zero flow
        self.assertEqual(KnowledgeV1Features.aggressor_buy_share(60.0, 40.0), 0.6)
        self.assertEqual(KnowledgeV1Features.aggressor_sell_share(60.0, 40.0), 0.4)
        self.assertEqual(KnowledgeV1Features.aggressor_volume_delta(60.0, 40.0), 20.0)

    def test_volume_and_return_features(self):
        """Volume acceleration, gap open, and intraday backward returns."""
        self.assertEqual(KnowledgeV1Features.gap_open_pct(102.0, 100.0), 0.02)
        self.assertEqual(KnowledgeV1Features.gap_open_pct(98.0, 100.0), -0.02)
        self.assertIsNone(KnowledgeV1Features.gap_open_pct(100.0, 0.0))

        self.assertEqual(KnowledgeV1Features.relative_volume_open(300.0, [100.0, 200.0]), 2.0)
        self.assertIsNone(KnowledgeV1Features.relative_volume_open(300.0, []))

        self.assertEqual(KnowledgeV1Features.volume_acceleration([10.0, 20.0, 50.0]), 20.0)
        self.assertIsNone(KnowledgeV1Features.volume_acceleration([10.0, 20.0]))

        self.assertEqual(KnowledgeV1Features.intraday_return_nm(105.0, 100.0), 0.05)
        self.assertIsNone(KnowledgeV1Features.intraday_return_nm(105.0, 0.0))


class TestKnowledgeV1CausalityAndClock(unittest.TestCase):
    """FIX-1: Causality, delayed execution clock, NO_CAUSAL_EXECUTION, and forward metrics."""

    def setUp(self):
        self.base_time = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)

    def test_execution_clock_exact_minute_boundary(self):
        """FIX-1: Signal at 09:30:00 -> decision available at 09:30:02 -> execution at 09:31:00."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        avail_t, exec_t = compute_causal_execution_time(signal_t, safety_buffer_seconds=2)

        self.assertEqual(avail_t, datetime(2026, 10, 2, 9, 30, 2, tzinfo=TPE))
        self.assertEqual(exec_t, datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE))
        self.assertGreater(exec_t, signal_t)

    def test_execution_clock_exact_093030_intraminute(self):
        """FIX-1: Signal at exact 09:30:30 -> decision available at 09:30:32 -> execution at 09:31:00."""
        signal_t = datetime(2026, 10, 2, 9, 30, 30, tzinfo=TPE)
        avail_t, exec_t = compute_causal_execution_time(signal_t, safety_buffer_seconds=2)

        self.assertEqual(avail_t, datetime(2026, 10, 2, 9, 30, 32, tzinfo=TPE))
        self.assertEqual(exec_t, datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE))

    def test_execution_clock_inside_minute(self):
        """FIX-1: Signal at 09:30:45 -> decision available at 09:30:47 -> execution at 09:31:00."""
        signal_t = datetime(2026, 10, 2, 9, 30, 45, tzinfo=TPE)
        avail_t, exec_t = compute_causal_execution_time(signal_t, safety_buffer_seconds=2)

        self.assertEqual(avail_t, datetime(2026, 10, 2, 9, 30, 47, tzinfo=TPE))
        self.assertEqual(exec_t, datetime(2026, 10, 2, 9, 31, 0, tzinfo=TPE))

        # Late in minute: 09:30:59 + 2s = 09:31:01 -> execution at 09:32:00
        late_signal_t = datetime(2026, 10, 2, 9, 30, 59, tzinfo=TPE)
        late_avail_t, late_exec_t = compute_causal_execution_time(late_signal_t, safety_buffer_seconds=2)
        self.assertEqual(late_avail_t, datetime(2026, 10, 2, 9, 31, 1, tzinfo=TPE))
        self.assertEqual(late_exec_t, datetime(2026, 10, 2, 9, 32, 0, tzinfo=TPE))

    def test_execution_clock_same_bar_open_forbidden(self):
        """FIX-1: A signal occurring at 09:30:00 CANNOT execute at 09:30:00 Open."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        bars = [
            CompletedBar(signal_t, signal_t + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 10.0),
            CompletedBar(signal_t + timedelta(minutes=1), signal_t + timedelta(minutes=2), 102.0, 103.0, 101.5, 102.5, 10.0),
        ]
        trigger = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=signal_t,
            current_price=100.5,
            prior_high=100.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        self.assertTrue(trigger.triggered)

        record = ResearchDatasetBuilder.build_record(
            symbol="2330",
            trigger_result=trigger,
            candidate_bars=bars,
            slippage_bps=0.0,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.execution_time, (signal_t + timedelta(minutes=1)).isoformat())
        self.assertEqual(record.execution_price, 102.0)
        self.assertNotEqual(record.execution_price, 100.0)

    def test_execution_clock_no_causal_execution_when_next_bar_missing(self):
        """FIX-1: If no bar starts at execution_time, mark NO_CAUSAL_EXECUTION, do not hallucinate price."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        bars = [
            CompletedBar(signal_t, signal_t + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 10.0),
        ]
        trigger = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=signal_t,
            current_price=100.5,
            prior_high=100.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        record = ResearchDatasetBuilder.build_record(
            symbol="2330",
            trigger_result=trigger,
            candidate_bars=bars,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.execution_status, "NO_CAUSAL_EXECUTION")
        self.assertIsNone(record.execution_price)
        self.assertIsNone(record.forward_return_1m)
        self.assertIsNone(record.mfe)

    def test_forward_metrics_calculated_strictly_from_execution_time_and_price(self):
        """FIX-1: Returns, MFE, and MAE must be measured strictly against execution_price from execution_time."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        trigger = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=signal_t,
            current_price=100.0,
            prior_high=99.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        bars = [
            CompletedBar(signal_t, signal_t + timedelta(minutes=1), 99.0, 100.0, 98.0, 100.0, 10),
            CompletedBar(signal_t + timedelta(minutes=1), signal_t + timedelta(minutes=2), 100.0, 102.0, 99.0, 101.0, 10),
            CompletedBar(signal_t + timedelta(minutes=2), signal_t + timedelta(minutes=3), 101.0, 110.0, 95.0, 105.0, 10),
        ]
        record = ResearchDatasetBuilder.build_record(
            symbol="2330",
            trigger_result=trigger,
            candidate_bars=bars,
            slippage_bps=0.0,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record.execution_status, "FILLED")
        self.assertEqual(record.execution_price, 100.0)
        self.assertEqual(record.forward_return_1m, 0.01)
        self.assertEqual(record.mfe, 0.1)
        self.assertEqual(record.mae, 0.05)

    def test_features_vector_excludes_labels_and_future_data(self):
        """FIX-1 & Dataset Leakage: features_vector() must strictly isolate causal features from labels."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        trigger = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=signal_t,
            current_price=100.0,
            prior_high=99.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        bars = [
            CompletedBar(signal_t, signal_t + timedelta(minutes=1), 99.0, 100.0, 98.0, 100.0, 10),
            CompletedBar(signal_t + timedelta(minutes=1), signal_t + timedelta(minutes=2), 100.0, 102.0, 99.0, 101.0, 10),
        ]
        record = ResearchDatasetBuilder.build_record(
            symbol="2330",
            trigger_result=trigger,
            candidate_bars=bars,
        )
        feat_vec = record.features_vector()
        forbidden_keys = [
            "forward_return_1m", "forward_return_3m", "forward_return_5m",
            "forward_return_10m", "forward_return_30m", "mfe", "mae",
            "execution_price", "execution_time", "realized_pnl", "transaction_cost_estimate"
        ]
        for key in forbidden_keys:
            self.assertNotIn(key, feat_vec)

    def test_future_mutation_does_not_alter_execution_selection(self):
        """FIX-1 Proof: Adding or mutating bars after execution bar does not alter execution price."""
        signal_t = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)
        trigger = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=signal_t,
            current_price=100.0,
            prior_high=99.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        bars_clean = [
            CompletedBar(signal_t, signal_t + timedelta(minutes=1), 99.0, 100.0, 98.0, 100.0, 10),
            CompletedBar(signal_t + timedelta(minutes=1), signal_t + timedelta(minutes=2), 101.0, 102.0, 100.5, 101.5, 10),
        ]
        record_clean = ResearchDatasetBuilder.build_record("2330", trigger, bars_clean, slippage_bps=0.0)

        bars_mutated = list(bars_clean)
        for i in range(2, 10):
            bars_mutated.append(
                CompletedBar(signal_t + timedelta(minutes=i), signal_t + timedelta(minutes=i + 1),
                             50.0, 50.0, 50.0, 50.0, 999999)
            )
        record_mutated = ResearchDatasetBuilder.build_record("2330", trigger, bars_mutated, slippage_bps=0.0)

        self.assertEqual(record_clean.execution_time, record_mutated.execution_time)
        self.assertEqual(record_clean.execution_price, record_mutated.execution_price)

    def test_causal_bar_series_as_of_filtering(self):
        """Verifies that queries at time t NEVER see bars ending after t."""
        bars = [
            CompletedBar(
                start_time=self.base_time + timedelta(minutes=i),
                end_time=self.base_time + timedelta(minutes=i + 1),
                open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.0 + i, volume=10.0
            )
            for i in range(10)
        ]
        series = CausalBarSeries(bars)
        t_query = self.base_time + timedelta(minutes=3)
        available = series.as_of(t_query)
        self.assertEqual(len(available), 3)
        self.assertEqual(available[-1].end_time, t_query)
        self.assertNotIn(bars[3], available)

    def test_causal_swing_segmenter_confirmation_delay(self):
        """Verifies that a swing high at bar k is NOT confirmed until bar k+c closes."""
        bars = [
            CompletedBar(self.base_time + timedelta(minutes=i), self.base_time + timedelta(minutes=i + 1),
                         100, h, 95, 100, 10)
            for i, h in enumerate([100, 110, 120, 115, 112])
        ]
        pivot_at_2 = CausalSwingSegmenter.find_latest_confirmed_pivot(bars[:3], confirmation_bars=2)
        self.assertIsNone(pivot_at_2)

        pivot_at_4 = CausalSwingSegmenter.find_latest_confirmed_pivot(bars[:5], confirmation_bars=2)
        self.assertIsNotNone(pivot_at_4)
        self.assertEqual(pivot_at_4.pivot_index, 2)
        self.assertEqual(pivot_at_4.pivot_price, 120.0)
        self.assertEqual(pivot_at_4.confirmed_index, 4)
        self.assertEqual(pivot_at_4.confirmed_time, bars[4].end_time)

    def test_mathematical_lookahead_regression_proof(self):
        """CRITICAL PROOF: Mutating future data strictly has 0 effect on past features."""
        bars_original = [
            CompletedBar(
                start_time=self.base_time + timedelta(minutes=i),
                end_time=self.base_time + timedelta(minutes=i + 1),
                open=100.0 + i, high=102.0 + i, low=99.0 + i, close=101.0 + i, volume=10.0 * (i + 1)
            )
            for i in range(5)
        ]
        t_decision = self.base_time + timedelta(minutes=5)
        series_clean = CausalBarSeries(bars_original)
        clean_bars = series_clean.as_of(t_decision)

        feat_clean = {
            "body_ratio": KnowledgeV1Features.body_ratio(clean_bars[-1]),
            "clv": KnowledgeV1Features.close_location_value(clean_bars[-1]),
            "dist_high": KnowledgeV1Features.dist_to_prev_high_pct(clean_bars[-1].close, [b.high for b in clean_bars[:-1]]),
            "vwap": KnowledgeV1Features.calculate_bar_typical_vwap(clean_bars),
        }

        bars_mutated = list(bars_original)
        for i in range(5, 20):
            bars_mutated.append(CompletedBar(
                start_time=self.base_time + timedelta(minutes=i),
                end_time=self.base_time + timedelta(minutes=i + 1),
                open=50.0, high=52.0, low=10.0, close=15.0, volume=1000000.0
            ))

        series_mutated = CausalBarSeries(bars_mutated)
        mutated_bars_asof = series_mutated.as_of(t_decision)

        feat_mutated = {
            "body_ratio": KnowledgeV1Features.body_ratio(mutated_bars_asof[-1]),
            "clv": KnowledgeV1Features.close_location_value(mutated_bars_asof[-1]),
            "dist_high": KnowledgeV1Features.dist_to_prev_high_pct(mutated_bars_asof[-1].close, [b.high for b in mutated_bars_asof[:-1]]),
            "vwap": KnowledgeV1Features.calculate_bar_typical_vwap(mutated_bars_asof),
        }
        self.assertEqual(feat_clean, feat_mutated)


class TestKnowledgeV1ParameterProvenance(unittest.TestCase):
    """FIX-3: Parameter provenance chains, grid ID bindings, and trigger bound verification."""

    def setUp(self):
        self.base_time = datetime(2026, 10, 2, 9, 30, 0, tzinfo=TPE)

    def test_c01_provenance_and_grid_injection(self):
        """C01: VWAP pullback support binds to G01/G22 and records provenance."""
        bar = {"open": 100.1, "close": 100.2, "low": 99.5, "high": 100.3}
        custom_params = KnowledgeV1Parameters(g01_touch_band=0.003, g01_stop_band=0.002, g22_lower_shadow_min=0.25)
        res = KnowledgeV1RuleEvaluator.evaluate_c01_vwap_pullback_support(
            symbol="2330",
            current_time=self.base_time,
            current_price=100.2,
            vwap=100.0,
            latest_bar=bar,
            params=custom_params,
        )
        self.assertTrue(res.triggered)
        self.assertIn("SV004", res.source_claim_ids)
        self.assertIn("AQ_R_003", res.ai_quantized_ids)

        prov = res.parameter_provenance
        self.assertEqual(prov["g01_touch_band"]["grid_id"], "RESEARCH_GRID_G01")
        self.assertEqual(prov["g01_touch_band"]["ai_quantized_id"], "AQ_R_003")
        self.assertEqual(prov["g22_lower_shadow_min"]["grid_id"], "RESEARCH_GRID_G22")

    def test_c02_scope_creep_removed_and_breakout_trigger(self):
        """C02: Restored to Phase 1 specification without max_extension gate."""
        # Case 1: Normal fresh breakout (current_price 105.5 > prior_20d_high 105.0) -> triggers
        res_fresh = KnowledgeV1RuleEvaluator.evaluate_c02_daily_trend_and_open_breakout(
            symbol="2330",
            current_time=self.base_time,
            current_price=105.5,
            session_open=102.0,
            prev_close=100.0,
            daily_ma5=98.0,
            daily_ma10=95.0,
            daily_ma20=90.0,
            prior_20d_high=105.0,
        )
        self.assertTrue(res_fresh.triggered)
        self.assertEqual(res_fresh.parameter_provenance["g23_breakout_proximity"]["grid_id"], "RESEARCH_GRID_G23")
        # Ensure max_extension is not in provenance
        self.assertNotIn("max_extension", res_fresh.parameter_provenance)

        # Case 2: Strong extension breakout (current_price 108.5 > prior_high 105.0, +3.3%) -> NOW TRIGGERS
        # Verifies that scope creep (0.015 gate) was successfully removed.
        res_extended = KnowledgeV1RuleEvaluator.evaluate_c02_daily_trend_and_open_breakout(
            symbol="2330",
            current_time=self.base_time,
            current_price=108.5,
            session_open=102.0,
            prev_close=100.0,
            daily_ma5=98.0,
            daily_ma10=95.0,
            daily_ma20=90.0,
            prior_20d_high=105.0,
        )
        self.assertTrue(res_extended.triggered)

    def test_c03_c04_c05_provenance(self):
        """C03, C04, C05 verify proper provenance tracking and grid references."""
        # C04
        res_c04 = KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol(
            symbol="2330",
            current_time=self.base_time,
            current_price=101.0,
            prior_high=100.0,
            volume_ratio=2.0,
            buy_volume=70.0,
            sell_volume=30.0,
        )
        self.assertTrue(res_c04.triggered)
        self.assertIn("SV001", res_c04.source_claim_ids)
        self.assertIn("AQ_R_002", res_c04.ai_quantized_ids)
        # Correctly pointing to RESEARCH_GRID_G05
        self.assertEqual(res_c04.parameter_provenance["volume_ratio_min"]["grid_id"], "RESEARCH_GRID_G05")

        # C05
        bar = {"open": 99.0, "close": 98.8, "high": 100.0, "low": 98.5}
        res_c05 = KnowledgeV1RuleEvaluator.evaluate_c05_failed_rebound_reversal(
            symbol="2330",
            current_time=self.base_time,
            current_price=99.8,
            resistance_price=100.0,
            latest_bar=bar,
            buy_volume=30.0,
            sell_volume=70.0,
        )
        self.assertTrue(res_c05.triggered)
        self.assertIn("SV005", res_c05.source_claim_ids)
        self.assertEqual(res_c05.parameter_provenance["g24_upper_shadow_min"]["grid_id"], "RESEARCH_GRID_G24")

    def test_candidate_evaluation_result_provenance_integrity(self):
        """All evaluation results must contain fully non-empty provenance records."""
        bar = {"open": 100.1, "close": 100.2, "low": 99.5, "high": 100.3}
        res = KnowledgeV1RuleEvaluator.evaluate_c01_vwap_pullback_support(
            symbol="2330",
            current_time=self.base_time,
            current_price=100.2,
            vwap=100.0,
            latest_bar=bar,
        )
        self.assertIsInstance(res.parameter_provenance, dict)
        self.assertGreater(len(res.parameter_provenance), 0)
        for param, meta in res.parameter_provenance.items():
            self.assertIn("value", meta)
            self.assertIn("grid_id", meta)
            self.assertIn("source_claim_id", meta)


class TestCanonicalGridConsistency(unittest.TestCase):
    """Canonical Parameter Grid verification: preserves G19-G21, verifies G22-G24, and enforces fail-closed validation."""

    def setUp(self):
        self.canonical_grids = CanonicalGridValidator.load_canonical_grids()

    def test_canonical_g19_g20_g21_preserved(self):
        """STEP 1 & 2: Canonical G19, G20, G21 retain their original definitions untouched."""
        self.assertIn("G19", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G19"]["parameter"], "futures_spread_candidate")
        self.assertEqual(self.canonical_grids["G19"]["values"], [0.003, 0.005, 0.006])

        self.assertIn("G20", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G20"]["parameter"], "pyramid_profit_trigger")
        self.assertEqual(self.canonical_grids["G20"]["values"], [0.004, 0.008, 0.015])

        self.assertIn("G21", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G21"]["parameter"], "stop_ticks_candidate")
        self.assertEqual(self.canonical_grids["G21"]["values"], [2, 3, 5])

    def test_new_research_parameters_in_canonical_grids(self):
        """STEP 2: New research parameters G22, G23, G24 exist in canonical YAML with valid values."""
        self.assertIn("G22", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G22"]["parameter"], "lower_shadow_support_ratio")
        self.assertIn(0.25, self.canonical_grids["G22"]["values"])

        self.assertIn("G23", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G23"]["parameter"], "breakout_proximity_band")
        self.assertIn(0.001, self.canonical_grids["G23"]["values"])

        self.assertIn("G24", self.canonical_grids)
        self.assertEqual(self.canonical_grids["G24"]["parameter"], "upper_shadow_rejection_ratio")
        self.assertIn(0.45, self.canonical_grids["G24"]["values"])

    def test_g05_mapping_points_to_g05(self):
        """STEP 4: G05_RVOL_THRESHOLD strictly points to canonical G05."""
        p = KnowledgeV1Parameters.G05_RVOL_THRESHOLD
        self.assertEqual(p.grid_id, "RESEARCH_GRID_G05")
        self.assertEqual(p.parameter_name, "rvol_threshold")
        self.assertEqual(p.seed_value, 1.5)

        # Validate against canonical
        validated = CanonicalGridValidator.validate_parameter(p.grid_id, p.parameter_name, p.seed_value)
        self.assertEqual(validated["grid_id"], "G05")

    def test_validator_fail_closed_on_missing_grid_id(self):
        """STEP 5: Non-existent Grid IDs must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            CanonicalGridValidator.validate_parameter("G999", "some_param", 1.0)
        self.assertIn("does NOT exist in canonical", str(ctx.exception))

    def test_validator_fail_closed_on_parameter_name_mismatch(self):
        """STEP 5: Existing Grid ID with mismatched parameter_name must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            CanonicalGridValidator.validate_parameter("G01", "wrong_parameter_name", 0.003)
        self.assertIn("parameter name mismatch", str(ctx.exception))

    def test_validator_fail_closed_on_unallowed_value(self):
        """STEP 5: Value not in canonical values list must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            CanonicalGridValidator.validate_parameter("G01", "vwap_touch_band_fraction", 0.999)
        self.assertIn("is NOT in canonical allowed values", str(ctx.exception))

    def test_all_active_strategy_thresholds_validated_against_canonical(self):
        """STEP 5 & 6: Every threshold registered in KnowledgeV1Parameters passes canonical validation."""
        active_params = [
            KnowledgeV1Parameters.G01_VWAP_TOUCH_BAND,
            KnowledgeV1Parameters.G02_VWAP_STOP_BAND,
            KnowledgeV1Parameters.G04_PRIOR_HIGH_WINDOW,
            KnowledgeV1Parameters.G05_RVOL_THRESHOLD,
            KnowledgeV1Parameters.G14_AGGRESSOR_SHARE,
            KnowledgeV1Parameters.G15_DROP_FROM_REFERENCE,
            KnowledgeV1Parameters.G17_PULLBACK_VOL_DECAY,
            KnowledgeV1Parameters.G19_CANONICAL_FUTURES_SPREAD,
            KnowledgeV1Parameters.G20_CANONICAL_PYRAMID_PROFIT,
            KnowledgeV1Parameters.G21_CANONICAL_STOP_TICKS,
            KnowledgeV1Parameters.G22_LOWER_SHADOW_SUPPORT,
            KnowledgeV1Parameters.G23_BREAKOUT_PROXIMITY,
            KnowledgeV1Parameters.G24_UPPER_SHADOW_REJECTION,
        ]
        for param in active_params:
            with self.subTest(grid_id=param.grid_id):
                # Must not raise
                canonical_entry = CanonicalGridValidator.validate_parameter(
                    grid_id=param.grid_id,
                    parameter_name=param.parameter_name,
                    value=param.seed_value,
                    status=param.status,
                )
                self.assertIsNotNone(canonical_entry)


class TestKnowledgeV1RegistryAndBoundaries(unittest.TestCase):
    """Registry status validation, boundaries, and prohibition integrity."""

    def setUp(self):
        self.registry = FeatureRegistry()

    def test_registry_status_and_boundary_classifications(self):
        partial_reused = self.registry.list_by_status(RegistryStatus.PARTIAL_REUSE)
        new_res = self.registry.list_by_status(RegistryStatus.NEW_RESEARCH)
        unsupported = self.registry.list_by_status(RegistryStatus.UNSUPPORTED)
        future = self.registry.list_by_status(RegistryStatus.FUTURE_DATA_REQUIRED)

        self.assertGreaterEqual(len(partial_reused), 3)
        self.assertGreaterEqual(len(new_res), 10)
        self.assertGreaterEqual(len(unsupported), 5)
        self.assertGreaterEqual(len(future), 4)

        # Verify prohibited features are strictly UNSUPPORTED
        unsupported_ids = {m.feature_id for m in unsupported}
        self.assertIn("F_order_book_imbalance_5", unsupported_ids)
        self.assertIn("F_bid_wall_thickness_ratio", unsupported_ids)
        self.assertIn("F_wall_depletion_velocity", unsupported_ids)
        self.assertIn("F_tx_traded_lots_spread", unsupported_ids)


if __name__ == "__main__":
    unittest.main()
