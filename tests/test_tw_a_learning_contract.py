"""Synthetic inputs only: reject foreign, future, stale and unit-mixed data."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from research.tw_a_learning_v1.contract import (
    ContractError, FEATURES, completed_candles, feature_row, valid_price,
)
from research.tw_a_learning_v1.preflight import DATA_PROOFS, check_manifest


def snapshot():
    return {
        "market": "TW", "venue": "TWSE", "symbol": "2330", "instrument_type": "COMMON_STOCK",
        "decision_at": "2026-09-30T10:00:00+08:00", "session_date": "2026-09-30",
        "trading_day_verified": True, "features_as_of": "2026-09-30T10:00:00+08:00",
        "quote_at": "2026-09-30T10:00:00+08:00", "price": 100,
        "eligibility_as_of": "2026-09-30T09:00:00+08:00", "daytrade_eligible": True,
        "previous_reference": {"price": 99, "session_at": "2026-09-29T13:30:00+08:00", "available_at": "2026-09-30T08:30:00+08:00"},
        "limit_up": 108.5, "limit_down": 89.1, "return_5m_pct": 1,
        "radar": {"as_of": "2026-09-30T10:00:00+08:00", "history_seconds": 400,
                  "classified_ratio_60s": .8, "buy_ratio_60s": .6, "surge_60s": 2,
                  "amount_60s": 1000000, "amount_unit": "TWD"},
        "day_volume": {"as_of": "2026-09-30T10:00:00+08:00", "value": 3000000, "unit": "SHARES"},
        "book": {"as_of": "2026-09-30T10:00:00+08:00", "bid": 100, "ask": 100.5,
                 "size_unit": "SHARES", "bid_shares": 1000, "ask_shares": 2000},
        "market_context": {"index": "TAIEX", "source_kind": "OFFICIAL_INDEX",
                           "as_of": "2026-09-30T10:00:00+08:00", "price": 20000,
                           "price_60s_ago": 19990, "price_5m_ago": 19900,
                           "price_60s_at": "2026-09-30T09:59:00+08:00",
                           "price_5m_at": "2026-09-30T09:55:00+08:00",
                           "session_high_so_far": 20100},
    }


def candle(start="2026-09-30T09:59:00+08:00", end="2026-09-30T10:00:00+08:00"):
    return dict(symbol="2330", market="TW", venue="TWSE", instrument_type="COMMON_STOCK",
                start_at=start, end_at=end, available_at=end, trading_day_verified=True,
                open=100, high=101, low=99.9, close=100.5,
                volume=1000, volume_unit="SHARES", amount=100500, amount_unit="TWD")


class TaiwanContractTests(unittest.TestCase):
    def test_shared_features_use_taiwan_index_and_explicit_volume(self):
        row = snapshot()
        result = feature_row(row)
        self.assertEqual(tuple(result), FEATURES)
        self.assertEqual(result["day_volume_lots"], 3000)
        self.assertAlmostEqual(result["relative_return_5m_pct"], 1 - (20000 / 19900 - 1) * 100)
        self.assertLess(result["market_drawdown_from_high_pct"], 0)
        row["day_volume"].update(value=3000, unit="LOT")
        self.assertEqual(result, feature_row(row))

    def test_foreign_markets_etfs_unknown_eligibility_and_naive_times_rejected(self):
        for update in ({"market": "US"}, {"venue": "SSE"}, {"symbol": "AAPL"},
                       {"symbol": "0050", "instrument_type": "ETF"},
                       {"daytrade_eligible": None}, {"trading_day_verified": False},
                       {"decision_at": "2026-09-30T10:00:00"}):
            with self.subTest(update=update):
                row = snapshot(); row.update(update)
                with self.assertRaises(ContractError):
                    feature_row(row)

    def test_future_and_stale_sources_fail_closed(self):
        for key in ("features_as_of", "quote_at", "eligibility_as_of"):
            row = snapshot(); row[key] = "2026-09-30T10:00:01+08:00"
            with self.subTest(key=key), self.assertRaises(ContractError):
                feature_row(row)
        for key in ("book", "radar", "day_volume", "market_context"):
            row = snapshot(); row[key]["as_of"] = "2026-09-30T09:59:00+08:00"
            with self.subTest(key=key), self.assertRaises(ContractError):
                feature_row(row)

    def test_matching_index_required_not_etf_or_foreign_proxy(self):
        for update in ({"index": "SP500"}, {"source_kind": "ETF_PROXY"}):
            row = snapshot(); row["market_context"].update(update)
            with self.subTest(update=update), self.assertRaises(ContractError):
                feature_row(row)
        row = snapshot(); row["venue"] = "TPEX"
        with self.assertRaises(ContractError):
            feature_row(row)
        row["market_context"]["index"] = "TPEX_INDEX"
        self.assertEqual(len(feature_row(row)), len(FEATURES))

    def test_bad_units_missing_history_and_future_high_rejected(self):
        for key, update in (("day_volume", {"unit": "UNKNOWN"}),
                            ("day_volume", {"value": 1.5}),
                            ("book", {"size_unit": "LOT"}),
                            ("book", {"ask_shares": 1.5}),
                            ("radar", {"amount_unit": "USD"}),
                            ("market_context", {"price_5m_at": "2026-09-30T09:59:00+08:00"}),
                            ("market_context", {"as_of": "2026-09-30T13:30:00+08:00"})):
            row = snapshot(); row[key].update(update)
            with self.subTest(key=key, update=update), self.assertRaises(ContractError):
                feature_row(row)
        row = snapshot(); del row["market_context"]
        with self.assertRaises(ContractError):
            feature_row(row)

    def test_only_existing_a_entry_window(self):
        for at in ("09:29:59", "12:30:00", "13:20:00"):
            row = snapshot(); row["decision_at"] = "2026-09-30T" + at + "+08:00"
            with self.subTest(at=at), self.assertRaises(ContractError):
                feature_row(row)

    def test_extreme_finite_inputs_cannot_produce_infinite_features(self):
        row = snapshot()
        row["market_context"].update(price=1e300, session_high_so_far=1e300, price_5m_ago=1e-300)
        with self.assertRaises(ContractError):
            feature_row(row)

    def test_tick_boundaries_and_invalid_values(self):
        for p in (9.99, 10, 49.95, 50, 99.9, 100, 499.5, 500, 999, 1000, 1005):
            self.assertEqual(valid_price(p), p)
        for p in (10.01, 50.05, 100.1, 500.5, 1001, 0, -1, True, float("nan"), float("inf")):
            with self.subTest(p=p), self.assertRaises(ContractError):
                valid_price(p)

    def candles(self, rows):
        return completed_candles(rows, decision_at="2026-09-30T10:00:00+08:00", market="TW", venue="TWSE", symbol="2330")

    def test_only_completed_available_candles(self):
        self.assertEqual(len(self.candles([candle()])), 1)
        for update in ({"available_at": "2026-09-30T10:00:01+08:00"},
                       {"end_at": "2026-09-30T10:01:00+08:00"},
                       {"volume_unit": "LOT"}, {"volume": 0},
                       {"instrument_type": "ETF"}, {"high": 99.9}):
            row = candle(); row.update(update)
            with self.subTest(update=update), self.assertRaises(ContractError):
                self.candles([row])

    def test_no_missing_or_overlapping_candles(self):
        prior = candle("2026-09-30T09:57:00+08:00", "2026-09-30T09:58:00+08:00")
        with self.assertRaises(ContractError):
            self.candles([prior, candle()])
        with self.assertRaises(ContractError):
            self.candles([candle(), candle()])
        with self.assertRaises(ContractError):
            self.candles([])

    def test_prior_sessions_not_flattened_into_contiguous_minutes(self):
        prior = candle("2026-09-29T13:29:00+08:00", "2026-09-29T13:30:00+08:00")
        # Jumping from yesterday's close straight to 09:59 omits today's history.
        with self.assertRaises(ContractError):
            self.candles([prior, candle()])


class MetadataPreflightTests(unittest.TestCase):
    def manifest(self):
        root = Path(__file__).resolve().parents[1]
        return json.loads((root / "research/tw_a_learning_v1/readiness.manifest.json").read_text())

    def test_example_is_blocked_and_no_execution_is_authorized(self):
        report = check_manifest(self.manifest())
        self.assertEqual(report["status"], "BLOCKED_NOT_READY")
        for key in ("market_data_opened", "model_weights_opened", "training_executed", "training_authorized", "production_changed", "production_ready"):
            self.assertIs(report[key], False)
        self.assertFalse(report["monitor"]["may_change_market_gate"])

    def test_foreign_training_and_post_cutoff_dates_rejected(self):
        for update in ({"training_markets": ["TW", "US"]},
                       {"training_markets": ["CN"]},
                       {"start_date": "2026-09-01", "end_date": "2026-10-05"}):
            m = self.manifest(); m["dataset"].update(update)
            report = check_manifest(m)
            failed = {c["check"] for c in report["checks"] if not c["passed"]}
            self.assertTrue({"taiwan_training_only", "historical_scope_through_2026_10_02"} & failed)

    def test_complete_self_declared_metadata_still_never_authorizes_training(self):
        m = self.manifest()
        m["dataset"].update(dataset_id="SYNTHETIC_TEST_ONLY", start_date="2026-09-01", end_date="2026-10-02")
        m["dataset"].update({key: True for key in DATA_PROOFS})
        m["preregistration_commit"] = "a" * 40
        m["freeze_hashes"] = {key: "b" * 64 for key in ("preregistration", "dataset_registry", "exposure_ledger", "cost_model", "evaluation_plan", "baseline_policy")}
        for desc in m["models"].values():
            desc.update(implementation_reviewed=True, package_version="test-only", revision="c" * 40,
                        weight_sha256="d" * 64, license_reviewed=True,
                        pretraining_overlap_status="AUDITED_NO_EVALUATION_OVERLAP", inference_resource_verified=True)
        with patch("research.tw_a_learning_v1.preflight.metadata.version", return_value="test-only"):
            report = check_manifest(m)
        self.assertEqual(report["status"], "METADATA_COMPLETE_NOT_AUTHORIZED")
        self.assertFalse(report["training_authorized"])
        self.assertFalse(report["production_ready"])

    def test_metadata_check_never_opens_dataset_or_weights(self):
        m = self.manifest()
        m["dataset"]["path"] = "DO_NOT_OPEN_RESERVED_DATA"
        with patch("builtins.open", side_effect=AssertionError("unexpected data access")), patch.object(Path, "open", side_effect=AssertionError("unexpected path access")):
            report = check_manifest(m)
        self.assertFalse(report["market_data_opened"])


if __name__ == "__main__":
    unittest.main()
