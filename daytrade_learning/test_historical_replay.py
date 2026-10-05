import gzip
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from daytrade_learning import historical_replay as replay
from daytrade_learning.research import profile_hash

TPE = timezone(timedelta(hours=8))
DAY = '2026-10-02'


def ns(h, m, s=0):
    # Shioaji archive encodes local wall-clock in a naive UTC nanosecond value.
    return int(datetime(2026, 10, 2, h, m, s, tzinfo=timezone.utc).timestamp() * 1e9)


def payload():
    return {
        'symbol': '2330', 'date': DAY,
        'ticks': {
            'ts': [ns(9, 0), ns(9, 25), ns(9, 29, 2), ns(9, 30, 2), ns(9, 31)],
            'close': [100, 100, 100, 101, 102],
            'volume': [10, 10, 20, 30, 40],
            'tick_type': [1, 1, 2, 1, 1],
        },
        'kbars': {'ts': [ns(9, 31), ns(9, 32)],
                  'Open': [101, 102], 'High': [102, 103],
                  'Low': [100, 101], 'Close': [102, 103], 'Volume': [50, 60]},
    }


def official(day=DAY):
    return json.dumps({
        'stat': 'OK', 'date': day.replace('-', ''),
        'fields': ['證券代號', '證券名稱', '漲停價', '開盤競價基準', '跌停價',
                   '開盤競價基準', '收盤價', '買進揭示價', '賣出揭示價', '最近成交日', '可否零股交易'],
        'data': [['2330', '台積電', '110.00', '100.00', '90.00', '99.00',
                  '101.00', '101.00', '102.00', '115.10.01', '可']]
    }, ensure_ascii=False).encode()


def stub_radar(events, now):
    recent = [e for e in events if now - 60 < e[0] <= now]
    return {'surge_60s': 2.0, 'buy_ratio_60s': .6, 'amount_60s': 2_000_000.0,
            'history_seconds': now - events[0][0], 'classified_ratio_60s': 1.0} if recent else None


class ReplayTests(unittest.TestCase):
    def test_source_cutoff_is_enforced_before_read_or_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'raw' / '2026-10-03').mkdir(parents=True)
            store = replay.Archive(root / 'raw', DAY)
            self.assertEqual(store.days('2026-10-01'), [])
            with self.assertRaisesRegex(ValueError, 'source_after_cutoff'):
                store.files('2026-10-03')
            refs = replay.References(root / 'refs', DAY, fetch=lambda day: self.fail('must not fetch'))
            with self.assertRaisesRegex(ValueError, 'source_after_cutoff'):
                refs.get('2026-10-03')

    def test_official_reference_exact_date_schema_and_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            refs = replay.References(Path(folder), DAY, fetch=lambda day: official())
            result, digest = refs.get(DAY, persist=False)
            self.assertEqual(result['2330']['reference'], 100)
            self.assertEqual(result['2330']['limit_up'], 110)
            self.assertEqual(result['2330']['last_trade_date'], '2026-10-01')
            self.assertEqual(len(digest), 64)
            self.assertFalse((Path(folder) / (DAY + '.json')).exists())
            bad = replay.References(Path(folder), DAY, fetch=lambda day: official('2026-10-01'))
            with self.assertRaisesRegex(ValueError, 'official_date_or_status_mismatch'):
                bad.get(DAY)

    def test_corrupt_gzip_and_missing_kbar_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / DAY
            root.mkdir(parents=True)
            file = root / '2330.json.gz'
            file.write_bytes(b'not gzip')
            archive = replay.Archive(root.parent, DAY)
            with self.assertRaises((gzip.BadGzipFile, EOFError, OSError)):
                archive.read(file, DAY)
            bad = payload()
            bad.pop('kbars')
            file.write_bytes(gzip.compress(json.dumps(bad).encode()))
            with self.assertRaisesRegex(ValueError, 'missing_kbars'):
                archive.read(file, DAY)

    def test_minute_bar_convention_and_reference(self):
        reference = {'reference': 100, 'limit_up': 110, 'limit_down': 90,
                     'last_trade_date': '2026-10-01'}
        pack = replay.pack_bars(payload(), reference, DAY)
        self.assertEqual(pack['bars'][0]['at'], '2026-10-02T09:30:00+08:00')
        self.assertEqual(pack['previous_close'], {'date': '2026-10-01', 'price': 100})

    def test_future_tick_mutation_cannot_change_past_features(self):
        p = payload()
        p['ticks']['ts'] = [ns(9, 0), ns(9, 24), ns(9, 25), ns(9, 29, 2), ns(9, 30, 2), ns(9, 31)]
        p['ticks']['close'] = [100, 100, 100, 100, 101, 102]
        p['ticks']['volume'] = [10, 10, 10, 20, 30, 40]
        p['ticks']['tick_type'] = [1, 1, 1, 2, 1, 1]
        policy = {'stop_loss_pct': .008, 'take_profit_pct': .012}
        cutoff = datetime.fromisoformat(DAY + 'T09:30:03+08:00')
        stub = types.ModuleType('intraday_live')
        stub.compute_volume_surge_metrics = stub_radar
        stub.qualifies_volume_surge = lambda m: True
        stub.score_volume_surge = lambda m: 50
        with patch.dict(sys.modules, {'intraday_live': stub}):
            first = replay.sample_at(p, DAY, cutoff, {'reference': 100}, policy)
            self.assertIsNotNone(first)
            p['ticks']['close'][-1] = 999
            p['ticks']['volume'][-1] = 999999
            p['kbars']['Close'][-1] = 999
            second = replay.sample_at(p, DAY, cutoff, {'reference': 100}, policy)
        self.assertEqual(first['_features'], second['_features'])
        self.assertEqual(first['metrics'], second['metrics'])

    def test_live_observed_wins_duplicate_bucket_and_profile_isolated(self):
        base = {'symbol': '2330', 'date': DAY, 'at': DAY + 'T09:30:03+08:00',
                'profile': 'current', 'net_return_pct': -1}
        live = {**base, 'at': DAY + 'T09:30:02+08:00', 'net_return_pct': 1}
        old = {**base, 'profile': 'old', 'net_return_pct': 99}
        self.assertEqual(replay.merge_live([base, old], [live], 'current'), [live])

    def test_profile_hash_is_deterministic_for_same_semantics(self):
        costs = {'fee_rate': .0015, 'minimum_fee_twd': 20.0, 'sell_tax_rate': .003,
                 'slippage_bps': 10.0, 'shares': 1000.0, 'filters': {'min_price': 1,
                 'max_price': 2000, 'max_gain_pct': 8}}
        policy = {'stop_loss_pct': .008, 'take_profit_pct': .012}
        first = profile_hash(costs, policy)
        self.assertEqual(first, profile_hash(dict(reversed(list(costs.items()))), policy))
        self.assertNotEqual(first, profile_hash({**costs, 'slippage_bps': 20.0}, policy))
        self.assertNotEqual(first, profile_hash(costs, {**policy, 'stop_loss_pct': .01}))
        self.assertEqual(first, profile_hash(costs, {**policy, 'ui_label': 'unrelated'}))


if __name__ == '__main__':
    unittest.main()
