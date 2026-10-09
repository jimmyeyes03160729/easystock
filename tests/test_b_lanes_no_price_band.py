"""The 100~149 price band was removed on 2026-10-09; sub-100 stocks may enter."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from runway_v2.lanes import LaneSuite, TPE


class NoPriceBandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.suite = LaneSuite(Path(self.temp.name) / "lanes.sqlite", sender=lambda text, key: None)
        self.now = datetime(2026, 10, 12, 9, 3, tzinfo=TPE)
        self.suite.advance(self.now)

    def tearDown(self):
        self.suite.worker.shutdown(wait=True)
        self.temp.cleanup()

    def test_b1_enters_a_stock_priced_below_100(self):
        s, now = self.suite, self.now
        s.market = {"valid": True, "gate_action": "PASS", "observed_at": now.timestamp()}
        s.rows = {"LOW": {"symbol": "LOW", "name": "低價股", "previous_close": 69,
            "price": 71.5, "sector": "01", "observed_at": now.timestamp()}}
        for sym in ("PEER1", "PEER2"):
            s.rows[sym] = {"previous_close": 100, "price": 102, "sector": "01", "observed_at": now.timestamp()}
        for sec, p in ((50,70),(40,72),(30,71.5),(20,72),(9,70.5),(7,71),(5,71),(3,71.5),(1,71.5),(0,71.5)):
            s.on_tick("LOW", p, now-timedelta(seconds=sec), 1, 10)
        for sec in (10, 6, 0):
            s.on_bidask("LOW", {"datetime": now-timedelta(seconds=sec),
                "bid_price": [71.4-i*.1 for i in range(5)], "ask_price": [71.5+i*.1 for i in range(5)],
                "bid_volume": [20]*5, "ask_volume": [20/3]*5})
        s.advance(now)
        pos = s.state["B1"]["positions"].get("LOW")
        self.assertIsNotNone(pos, s.state["B1"]["rejects"])
        self.assertEqual(pos["entry_price"], 71.5)


if __name__ == "__main__":
    unittest.main()
