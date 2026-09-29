import unittest

from range_rebound import RULE_VERSION, build_rebound_feed, evaluate_financial, evaluate_technical


class RangeReboundTests(unittest.TestCase):
    def setUp(self):
        self.asof = "2026-09-29"
        self.stock = {
            "symbol": "2330",
            "name": "台積電",
            "category": "半導體",
            "exchange": "TWSE",
            "updated_at": self.asof,
            "price": 100.0,
            "amount": 100_000_000,
            "rev_yoy": 5.0,
            "eps": 10.0,
            "operating_margin": 20.0,
            "debt_ratio": 30.0,
            "revenue_period": "202608",
            "field_meta": {
                "rev_yoy": {"as_of": self.asof, "source": "official-api", "period": "202608"},
                "eps": {"as_of": self.asof, "source": "official-filings", "period": "2026-Q2"},
                "operating_margin": {"as_of": self.asof, "source": "official-filings", "period": "2026-Q2"},
                "debt_ratio": {"as_of": self.asof, "source": "official-filings", "period": "2026-Q2"},
            },
            "legacy_fallback_fields": [],
        }

    def test_financial_gate_can_pass_with_current_official_fields(self):
        result = evaluate_financial(self.stock, self.asof)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["missing"])
        self.assertFalse(result["failed"])

    def test_short_kline_is_rejected_deterministically(self):
        rows = [
            {"time": "2026-09-28", "open": 99, "high": 101, "low": 98, "close": 100},
            {"time": "2026-09-29", "open": 100, "high": 102, "low": 99, "close": 101},
        ]
        result = evaluate_technical(rows, self.asof, 101)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["rule_version"], RULE_VERSION)
        self.assertIn("90", result["reason"])

    def test_feed_schema_is_stable_even_without_candidates(self):
        feed = build_rebound_feed(
            {"2330": self.stock},
            {"2330": []},
            self.asof,
            "release-test",
            "2026-09-29T08:00:00+00:00",
        )
        self.assertEqual(feed["schema_version"], 1)
        self.assertEqual(feed["strategy_version"], RULE_VERSION)
        self.assertEqual(feed["release_id"], "release-test")
        self.assertEqual(feed["signals"], [])


if __name__ == "__main__":
    unittest.main()
