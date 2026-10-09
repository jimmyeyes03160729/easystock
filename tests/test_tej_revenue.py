import json
import tempfile
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from market_events.tej_revenue import collect, connect, merge_recent, normalize, save_rows
from market_events.tracker import TPE


NOW = datetime(2026, 10, 9, 17, tzinfo=TPE)


def row(**updates):
    values = dict(coid='2330', mdate='2026-09-01', annd_s='2026-10-08',
                  d0001=100, d0003=20, d0004=10)
    values.update(updates)
    return values


class RevenueTests(unittest.TestCase):
    def test_mapping_and_consolidated_preference(self):
        result = normalize(row(t8100m=200, mfr2=30, mfr3=15), NOW.isoformat(), 'TRAIL/TASALE')
        self.assertEqual((result['rev_yoy'], result['rev_mom']), (30, 15))
        self.assertEqual(result['revenue_announcement_day'], '2026-10-08')
        self.assertEqual(result['revenue_thousand_twd'], 200)

    def test_reject_missing_date_invalid_growth_and_future_announcement(self):
        for changes in [dict(annd_s=None), dict(d0003=float('nan')),
                        dict(annd_s='2026-10-10'), dict(coid='0930.0')]:
            self.assertIsNone(normalize(row(**changes), NOW.isoformat(), 'TRAIL/TASALE'))

    def test_history_not_used_live_and_official_ties_win(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'tej.sqlite'
            db = connect(path)
            save_rows(db, [row(), row(coid='2317', mdate='2025-12-01', annd_s='2026-01-10')], NOW, 'TRAIL/TASALE')
            db.close()
            official = {'2330': {'revenue_period':'11509', 'rev_yoy':99}}
            merged = merge_recent(official, path, NOW)
            self.assertEqual(merged, official)
            merged = merge_recent({'2330':{'revenue_period':'11508'}}, path, NOW)
            self.assertEqual(merged['2330']['revenue_source'], 'TEJ')
            self.assertNotIn('2317', merged)

    def test_future_observation_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tej.sqlite'
            db=connect(path)
            save_rows(db,[row()], datetime(2026,10,10,tzinfo=TPE),'TRAIL/TASALE')
            db.close()
            self.assertEqual(merge_recent({},path,NOW),{})

    def fake_api(self, records, remaining=50000, incomplete=False):
        class Frame:
            def __len__(self):return len(records)
            def to_dict(self, orient):return records
        def get(*args, **kwargs):
            if incomplete:warnings.warn('page limit exceeded')
            return Frame()
        return SimpleNamespace(ApiConfig=SimpleNamespace(info=lambda:dict(rowsDayLimit=remaining,todayRows=0,
            reqDayLimit=500,todayReqCount=0)),get=get)

    def test_empty_response_is_not_recent_success(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_text('private-key')
            status=collect(Path(folder),key,'TRAIL/TASALE',NOW,self.fake_api([]))
            self.assertEqual(status['state'],'no_recent_data')
            self.assertEqual(status['recent_rows'],0)
            self.assertNotIn('private-key',json.dumps(status))

    def test_quota_reserve_and_incomplete_page(self):
        for api, expected in [(self.fake_api([row()],remaining=14000),'quota_reserve'),
                              (self.fake_api([row()],incomplete=True),'incomplete_page')]:
            with tempfile.TemporaryDirectory() as folder:
                key=Path(folder)/'key';key.write_text('private-key')
                status=collect(Path(folder),key,'TRAIL/TASALE',NOW,api)
                self.assertIn(expected,status['errors'])
                self.assertEqual(status['stored_rows'],0)

    def test_provider_ignoring_date_filter_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_text('private-key')
            old=row(mdate='2025-12-01',annd_s='2026-01-10')
            status=collect(Path(folder),key,'TRAIL/TASALE',NOW,self.fake_api([old]))
            self.assertIn('out_of_range_response',status['errors'])
            self.assertEqual(status['stored_rows'],0)


if __name__ == '__main__':
    unittest.main()
