"""Regression for the VM's separate eleven-feature paper research services."""
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import paper_learning_cycle as paper
from daytrade_learning.model_runtime import DaytradeModel
from paper_legacy.decisions import Decisions, TPE
from paper_legacy.features import REQUIRED_FEATURES


class PaperLegacyTest(unittest.TestCase):
    def test_service_entry_points_import_with_current_live_model(self):
        self.assertEqual(len(REQUIRED_FEATURES), 11)
        self.assertEqual(DaytradeModel.__module__, 'daytrade_learning.model_runtime')
        self.assertEqual(paper.REQUIRED_FEATURES, REQUIRED_FEATURES)
        for name in ('paper_learning_cycle.py', 'wait_daily_collectors.py'):
            self.assertTrue((Path(__file__).resolve().parents[1] / name).is_file())
        self.assertTrue(callable(paper.collect))
        self.assertTrue(callable(paper.train))

    def test_observation_is_durable_and_quote_label_uses_subsequent_quotes(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Decisions(Path(temp) / 'decisions.sqlite')
            at = datetime(2026, 9, 24, 10, 0, tzinfo=TPE)
            features = {key: 1.0 for key in REQUIRED_FEATURES}
            key = book.record('2330', at, 100.0, features,
                              {'model_version': 'legacy-test', 'accepted': False}, {})
            self.assertEqual(key, book.record('2330', at, 100.0, features,
                                              {'model_version': 'legacy-test', 'accepted': False}, {}))
            with book.connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 1)
            start = int((at.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds() * 1e9)
            ticks = {'ts': [start + 2_000_000_000, start + 902_000_000_000],
                     'bid_price': [99.9, 101.0], 'ask_price': [100.0, 101.1]}
            label = paper.quote_label(ticks, at)
            self.assertIsNotNone(label)
            self.assertEqual(label['entry_ns'], ticks['ts'][0])
            self.assertEqual(label['exit_ns'], ticks['ts'][1])


if __name__ == '__main__':
    unittest.main()
