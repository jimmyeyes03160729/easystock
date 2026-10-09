"""Offline behavioral tests: no broker, Firebase or messaging endpoints."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from runway_v2.lanes import LaneSuite, TPE, completed_bars


class LaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sent = []
        self.suite = LaneSuite(Path(self.temp.name) / "lanes.sqlite", sender=lambda text, key: self.sent.append((text, key)))
        self.now = datetime(2026, 10, 12, 9, 3, tzinfo=TPE)
        self.suite.advance(self.now)

    def tearDown(self):
        self.suite.worker.shutdown(wait=True)
        self.temp.cleanup()

    def book(self, at, symbol="TEST", bid=121, ask=121.5, depth=20):
        self.suite.on_bidask(symbol, {"datetime": at, "bid_price": [bid-i*.5 for i in range(5)],
            "ask_price": [ask+i*.5 for i in range(5)], "bid_volume": [depth]*5, "ask_volume": [depth/3]*5})

    def ready(self):
        s, now = self.suite, self.now
        s.books.clear()
        s.tapes.clear()
        s.market = {"valid": True, "gate_action": "PASS", "observed_at": now.timestamp()}
        s.rows = {"TEST": {"symbol": "TEST", "name": "測試股", "previous_close": 119,
            "price": 121.5, "sector": "01", "observed_at": now.timestamp()}}
        for sym in ("PEER1", "PEER2"):
            s.rows[sym] = {"previous_close": 100, "price": 102, "sector": "01", "observed_at": now.timestamp()}
        for sec, p in ((50,120),(40,122),(30,121.5),(20,122),(9,120.5),(7,121),(5,121),(3,121.5),(1,121.5),(0,121.5)):
            s.on_tick("TEST", p, now-timedelta(seconds=sec), 1, 10)
        for sec in (10,6,0):
            self.book(now-timedelta(seconds=sec))

    def test_b1_uses_continuous_book_and_tape_without_5m_bar(self):
        self.ready()
        self.suite.advance(self.now)
        pos = self.suite.state["B1"]["positions"]["TEST"]
        self.assertEqual(pos["entry_price"], 121.5)
        self.assertEqual(pos["stop_price"], 120.5)
        self.assertEqual(pos["target"], 123)
        self.assertEqual(pos["shares"], 1000)
        self.assertEqual(self.suite.state["B2"]["positions"], {})
        self.assertEqual(self.suite.state["B3"]["positions"], {})

    def test_missing_or_stale_book_is_never_fallback_entry(self):
        self.ready()
        self.suite.books.clear()
        self.assertIsNone(self.suite._signal("B1", "TEST", self.now)[0])
        self.book(self.now-timedelta(seconds=4))
        self.assertIsNone(self.suite._signal("B1", "TEST", self.now)[0])

    def test_one_snapshot_unknown_tape_or_missing_sector_cannot_trigger(self):
        self.ready()
        last = self.suite.books["TEST"][-1]
        self.suite.books["TEST"].clear()
        self.suite.books["TEST"].append(last)
        self.assertIsNone(self.suite._signal("B1", "TEST", self.now)[0])
        self.ready()
        self.suite.rows["TEST"]["sector"] = ""
        self.assertEqual(self.suite._signal("B1", "TEST", self.now)[1], "族群資料不足或方向不同")

    def test_at_0910_exit_and_report_preserve_independent_backgrounds(self):
        self.ready()
        self.suite.advance(self.now)
        cutoff = self.now.replace(minute=10)
        self.book(cutoff)
        self.suite.advance(cutoff)
        self.suite.advance(cutoff+timedelta(seconds=1))
        self.suite.worker.shutdown(wait=True)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("B2／B3 尚未日結", self.sent[0][0])
        self.assertIn("已平倉1筆", self.sent[0][0])
        self.assertFalse(self.suite.state["B1"]["positions"])
        self.assertEqual(self.suite.state["B1"]["trades"][0]["exit_reason"], "時段結束")

    def test_stale_exit_remains_pending_and_does_not_fake_profit(self):
        self.ready()
        self.suite.advance(self.now)
        cutoff = self.now.replace(minute=10)
        self.suite.advance(cutoff)
        self.assertTrue(self.suite.state["B1"]["positions"])
        snapshot = self.suite.export_snapshot(cutoff)["lanes"]["B1"]
        self.assertEqual(snapshot["session"], "pending_exit")
        self.assertIsNone(snapshot["open_positions"]["TEST"]["current_price"])

    def test_sessions_survive_restart_and_do_not_reenter_closed_symbol(self):
        self.ready()
        self.suite.advance(self.now)
        restored = LaneSuite(self.suite.path, sender=lambda *a: None)
        restored.advance(self.now)
        self.assertEqual(restored.state["B1"]["used"], 121500)
        self.assertIn("TEST", restored.state["B1"]["positions"])
        restored.worker.shutdown(wait=True)

    def test_cap_never_rounds_up_to_one_lot(self):
        self.ready()
        self.suite.state["B1"]["used"] = 950000
        self.suite.advance(self.now)
        self.assertEqual(self.suite.state["B1"]["positions"], {})

    def test_no_feed_no_holiday_report(self):
        self.suite.advance(self.now.replace(hour=13))
        self.suite.worker.shutdown(wait=True)
        self.assertEqual(self.sent, [])

    def test_bars_reject_future_forming_and_previous_day(self):
        bar = {"open":120,"high":121,"low":119,"close":120,"volume":10}
        now = self.now.replace(minute=15)
        rows = [{**bar,"date": now.replace(minute=m).isoformat()} for m in (5,10,15)]
        rows.append({**bar,"date": (now-timedelta(days=1)).isoformat()})
        self.assertEqual(len(completed_bars(rows, now)), 2)

    def test_out_of_order_simulated_or_invalid_book_rejected(self):
        self.book(self.now)
        self.book(self.now-timedelta(seconds=1))
        self.book(self.now, bid=122, ask=121)
        self.assertEqual(len(self.suite.books["TEST"]), 1)

    def test_short_costs_charge_tax_on_sell_not_buy(self):
        pos = {"direction": -1,"entry_price":120,"shares":1000}
        self.assertAlmostEqual(self.suite._net(pos,119), 1000-47-47-180)

    def test_unknown_aggressor_tape_is_rejected(self):
        self.ready()
        self.suite.tapes["TEST"] = type(self.suite.tapes["TEST"])(
            [(dt,p,0,v) for dt,p,_,v in self.suite.tapes["TEST"]], maxlen=4000)
        self.assertIsNone(self.suite._signal("B1", "TEST", self.now)[0])

    def test_b3_completed_volume_breakout_is_independent_of_b1(self):
        self.now = self.now.replace(minute=16)
        self.ready()
        self.suite.bars["TEST"] = [
            {"date": self.now.replace(minute=m,second=0).isoformat(),
             "open":120,"high":high,"low":low,"close":close,"volume":vol}
            for m,high,low,close,vol in [(0,121,119,120,10),(5,121,119.5,120.5,10),(10,122,120.5,122,25)]]
        signal, reason = self.suite._signal("B3", "TEST", self.now)
        self.assertIsNotNone(signal, reason)
        self.suite.advance(self.now)
        self.assertFalse(self.suite.state["B1"]["positions"])
        self.assertIn("TEST", self.suite.state["B3"]["positions"])
        self.assertEqual(self.suite.state["B3"]["positions"]["TEST"]["stop_price"], 120)

    def test_b2_requires_warmup_and_returns_inside_band(self):
        self.now = self.now.replace(hour=10,minute=41)
        self.ready()
        self.assertEqual(self.suite._signal("B2", "TEST", self.now)[1], "等待20根完整五分K")
        start = self.now.replace(hour=9,minute=0,second=0)
        self.suite.bars["TEST"] = [{"date": (start+timedelta(minutes=i*5)).isoformat(),
            "open":123,"high":125,"low":120,"close":122 if i%2 else 124,"volume":10}
            for i in range(20)]
        signal, reason = self.suite._signal("B2", "TEST", self.now)
        self.assertIsNotNone(signal, reason)
        self.assertEqual(signal["target"], 123)

    def test_unconfirmed_short_eligibility_never_opens_position(self):
        self.ready()
        self.suite._signal = lambda *a: ({"direction":-1,"entry_price":121,"stop_price":122,
            "target":119.5,"signal_type":"B1","reasons":[],"score":0}, "")
        self.suite.advance(self.now)
        self.assertFalse(self.suite.state["B1"]["positions"])
        self.assertIn("未確認先賣後買資格", self.suite.state["B1"]["rejects"])

    def test_insufficient_exit_depth_reports_pending_then_final(self):
        self.ready()
        self.suite.advance(self.now)
        end = self.now.replace(hour=12,minute=55)
        self.book(end, depth=.5)
        self.suite.advance(end)
        self.assertTrue(self.suite.state["B1"]["positions"])
        self.book(end+timedelta(seconds=1))
        self.suite.advance(end+timedelta(seconds=1))
        self.suite.worker.shutdown(wait=True)
        keys = [key for _,key in self.sent]
        self.assertEqual(sum(key.endswith(":pending1255") for key in keys), 1)
        self.assertEqual(sum(key.endswith(":final") for key in keys), 1)

    def test_high_frequency_quotes_retain_enough_observation_time(self):
        for i in range(601):
            self.book(self.now-timedelta(seconds=6)+timedelta(milliseconds=i*10))
        history = self.suite.books["TEST"]
        self.assertLess(len(history), 30)
        self.assertGreater((history[-1]["dt"]-history[0]["dt"]).total_seconds(), 5)

    def test_both_channels_dedupe_each_phase_across_restarts(self):
        from easystock_admin.store import Store
        from easystock_admin import notifications
        from trade_notifications import _send
        store = Store(Path(self.temp.name)/"notify.sqlite", {"min_price":1,"max_price":100,"max_gain_pct":5})
        current = notifications.policy(store)
        notifications.update(store, {**{k: k.endswith("summary") for k in notifications.POLICY_FIELDS}, "version":current["version"]})
        with patch("trade_notifications._line_send", return_value="sent") as line, patch("trade_notifications._telegram_send", return_value="sent") as tg:
            for phase in ("0910","final"):
                key = f"b-lanes:v1:2026-10-12:{phase}"
                self.assertTrue(_send("三條狀態", "summary", key, store))
                self.assertFalse(_send("重啟後再試", "summary", key, store))
            self.assertEqual(line.call_count, 2)
            self.assertEqual(tg.call_count, 2)


if __name__ == "__main__":
    unittest.main()
