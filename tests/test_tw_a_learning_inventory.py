import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.tw_a_learning_v1.audit_inventory import allowed_day, label_inventory, partition_inventory, read_scoped_json


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, day, rows):
        path = self.root / (day + ".json")
        path.write_text(json.dumps(rows))
        return path

    def row(self, day="2026-10-02"):
        return dict(date=day, at=day + "T10:00:00+08:00", symbol="2330", profile="fixture",
                    features=[1, 2, 3, .5, 10], net_return_pct="MUST_NOT_EVALUATE")

    def test_post_cutoff_rejected_before_open(self):
        for day in ("2026-10-05", "2027-01-01", "2026-99-99"):
            with patch("builtins.open", side_effect=AssertionError("opened forbidden file")):
                with self.assertRaises(ValueError):
                    read_scoped_json(self.root / (day + ".json"), root=self.root, day=day)

    def test_foreign_path_rejected_before_open(self):
        with patch("builtins.open", side_effect=AssertionError("opened foreign path")):
            with self.assertRaises(ValueError):
                read_scoped_json(self.root / "outside/2026-10-02.json", root=self.root, day="2026-10-02")

    def test_future_partition_is_filename_only(self):
        self.write("2026-10-02", [self.row()])
        future = self.root / "2026-10-05.json"
        future.write_text("NOT JSON; MUST NEVER OPEN")
        result = label_inventory(self.root)
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["contents_opened"], ["2026-10-02"])
        self.assertFalse(result["files"][1]["content_read"])
        self.assertNotIn("net_return_pct", json.dumps(result["profiles"]))
        self.assertNotIn("MUST_NOT_EVALUATE", json.dumps(result))

    def test_duplicates_and_profile_groups_not_pooled(self):
        a = self.row(); b = {**a, "profile": "other"}
        self.write("2026-10-02", [a, a, b])
        r = label_inventory(self.root)
        self.assertEqual(r["duplicate_keys"], 1)
        self.assertEqual(len(r["profiles"]), 2)
        self.assertEqual(r["valid_five_feature_rows"], 3)
        self.assertEqual(r["explicit_label_available_at_rows"], 0)

    def test_malformed_record_identity_and_features_are_counted(self):
        self.write("2026-10-02", [self.row("2026-10-05"), {**self.row(), "features": [True, 2, 3, 4, 5]}])
        r = label_inventory(self.root)
        self.assertEqual(r["invalid_identity_rows"], 1)
        self.assertEqual(r["invalid_five_feature_rows"], 1)

    def test_non_common_stock_code_is_separate_from_corrupt_identity(self):
        self.write("2026-10-02", [self.row(), {**self.row(), "symbol": "0050"}])
        r = label_inventory(self.root)
        self.assertEqual(r["rows"], 2)
        self.assertEqual(r["invalid_identity_rows"], 0)
        self.assertEqual(r["out_of_scope_code_rows"], 1)
        self.assertEqual(r["profiles"][0]["rows"], 2)
        self.assertEqual(r["profiles"][0]["common_stock_code_rows"], 1)

    def test_allowed_journal_join_uses_keys_without_evaluating_returns(self):
        labels = self.root / "labels"; labels.mkdir()
        (labels / "2026-10-02.json").write_text(json.dumps([self.row()]))
        sample = {"kind": "sample", "data": {"symbol": "2330", "observed_at": "2026-10-02T10:00:00+08:00", "quote_at": "2026-10-02T09:59:59+08:00", "policy": {"stop_loss_pct": .018}}}
        (self.root / "journal-2026-10-02.jsonl").write_text(json.dumps(sample) + "\n")
        r = label_inventory(labels)["files"][0]["journal_join"]
        self.assertEqual(r["matched_keys"], 1)
        self.assertEqual(r["quote_time_present"], 1)
        self.assertTrue(r["complete_scan"])

    def test_raw_schema_sampling_never_opens_post_cutoff_partition(self):
        safe, future = self.root / "2026-10-02", self.root / "2026-10-05"
        safe.mkdir(); future.mkdir()
        (safe / "2330.json.gz").write_bytes(gzip.compress(json.dumps({"date": "2026-10-02", "ticks": {"ts": [1], "close": [999]}, "audit": {"training_eligible": False}}).encode()))
        (future / "2330.json.gz").write_bytes(b"MUST_NOT_OPEN")
        r = partition_inventory(self.root, compressed=True)
        self.assertEqual(r["allowed_date_partitions"], 1)
        self.assertEqual(r["allowed_file_count"], 1)
        self.assertIn("close", r["schema_samples"][0]["ticks_fields"])
        self.assertNotIn("999", json.dumps(r))

    def test_symlink_sources_rejected_without_read(self):
        target = self.write("2026-10-02", [self.row()])
        with patch.object(Path, "is_symlink", return_value=True), patch("builtins.open", side_effect=AssertionError("opened symlink")):
            with self.assertRaises(ValueError):
                read_scoped_json(target, root=self.root, day="2026-10-02")


if __name__ == "__main__":
    unittest.main()
