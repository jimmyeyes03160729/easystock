import json
from datetime import datetime
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

import trade_chart_feed as feed

DAY = '2026-10-16'
NOW = datetime.fromisoformat(DAY + 'T09:33:00+08:00')


def minute(hhmm, close=101, **extra):
    return dict(at=f'{DAY}T{hhmm}:00+08:00', open=100, high=103, low=99, close=close, volume=10, **extra)


class Ref:
    def __init__(self, writes, path='', lock=None): self.writes, self.path, self.lock = writes, path, lock
    def child(self, key): return Ref(self.writes, self.path + '/' + key, self.lock)
    def set(self, value):
        if self.lock is not None:
            assert self.lock.acquire(blocking=False), 'network write while bar-book lock held'
            self.lock.release()
        self.writes.append((self.path, value))


def store(lock=None):
    writes = []
    live = dict(closed_trades=[dict(symbol='2330', entry_time=DAY+'T09:30:00+08:00', private_account='never public')],
                runway_b_lanes={'lanes': {'B1': {'open_positions': {'x': dict(symbol='2330', entry_time=DAY+'T09:31:00+08:00')}}}})
    return SimpleNamespace(root=Ref(writes, lock=lock), live=SimpleNamespace(get=lambda: live)), writes


class ChartFeedTests(unittest.TestCase):
    def test_real_minutes_aggregate_and_current_bar_remains_visible(self):
        p = feed.payload('2330', DAY, [minute('09:30'), minute('09:31', 102), minute('09:32', forming=True)], now=NOW)
        self.assertEqual(len(p['minute_bars']), 3)
        self.assertEqual(len(p['bars']), 1)
        self.assertEqual(p['bars'][0]['volume'], 30)
        self.assertEqual(p['bars'][0]['open'], 100)
        self.assertEqual(p['bars'][0]['close'], 101)
        self.assertTrue(p['bars'][0]['forming'])
        self.assertFalse(p['session_closed'])
        self.assertEqual(p['quote_at'], DAY+'T09:32:00+08:00')

    def test_never_fabricate_wrong_day_future_invalid_or_missing_minutes(self):
        rows = [minute('09:30'), minute('09:32'), minute('09:34'), dict(minute('09:31'), high=10), dict(minute('09:31'), open=None), dict(minute('09:31'), at='2026-10-15T09:31:00+08:00')]
        p = feed.payload('2330', DAY, rows, now=NOW)
        self.assertEqual([r['time'][11:16] for r in p['minute_bars']], ['09:30', '09:32'])
        self.assertEqual(p['status'], 'partial')
        self.assertIsNone(feed.payload('2330', DAY, [], now=NOW))
        with self.assertRaises(ValueError): feed.payload('2330', DAY, [minute('09:30'), minute('09:30', 102)], now=NOW)

    def test_record_selection_unifies_a_b_without_publishing_trade_metadata(self):
        s, _ = store()
        self.assertEqual(feed.records(s.live.get()), [(DAY, '2330')])
        p = feed.payload('2330', DAY, [minute('09:30')], now=NOW)
        self.assertNotIn('private_account', json.dumps(p))
        self.assertNotIn('entry_price', p)

    def test_stream_snapshot_releases_lock_before_network_and_deduplicates(self):
        lock = threading.Lock(); s, writes = store(lock)
        b = SimpleNamespace(start=datetime.fromisoformat(DAY+'T09:30:00+08:00'), open=100, high=103, low=99, close=101, volume=10)
        book = SimpleNamespace(_lock=lock, completed_1m={'2330': []}, current_1m={'2330': b})
        worker = feed.ChartPublisher(s, book)
        worker.once(NOW); worker.once(NOW)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], '/intraday_charts/'+DAY+'/2330')
        self.assertTrue(writes[0][1]['minute_bars'][0]['forming'])
        b.close = 102; worker.once(NOW)
        self.assertEqual(len(writes), 2)
        worker.stop(); worker.once(NOW)
        self.assertEqual(len(writes), 2)

    def test_cached_history_reuses_price_data_and_only_receipts_its_own_files(self):
        s, writes = store()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'bars'/DAY/'2330.json'; p.parent.mkdir(parents=True)
            p.write_text(json.dumps(dict(symbol='2330', date=DAY, bars=[minute('09:30')], account='private')))
            self.assertEqual(feed.publish_cached(s, tmp, now=NOW)['published'], 1)
            self.assertEqual(feed.publish_cached(s, tmp, now=NOW)['unchanged'], 1)
            self.assertEqual(len(writes), 1)
            self.assertNotIn('private', json.dumps(writes))
            self.assertTrue(p.exists())

    def test_canonical_and_runtime_modules_are_identical(self):
        self.assertEqual(Path('trade_chart_feed.py').read_bytes(), Path('vm_runtime/trade_chart_feed.py').read_bytes())


if __name__ == '__main__': unittest.main()
