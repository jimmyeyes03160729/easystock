from datetime import datetime,date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import daily_history as h

class Tests(unittest.TestCase):
    def test_window_every_day_taipei(self):
        for day in (15,19,20):
            for hour,expected in [(8,False),(13,False),(14,True),(21,True),(22,False)]:
                self.assertEqual(h.allowed(datetime(2026,9,day,hour,tzinfo=h.core.TPE)),expected)
    def test_never_query_before_source_boundary_or_more_than_30_days(self):
        plan={'dates':['2026-09-01']}
        start,end=h.next_window(plan);self.assertEqual((end-start).days,29)
        self.assertEqual(h.next_window({'dates':['2020-03-15']}),(date(2020,3,2),date(2020,3,14)))
        self.assertIsNone(h.next_window({'dates':['2020-03-02']}))
    def test_retry_backoff_and_limit(self):
        self.assertTrue(h.eligible_failure({},100))
        self.assertFalse(h.eligible_failure({'attempts':1,'retry_after':101},100))
        self.assertTrue(h.eligible_failure({'attempts':30,'retry_after':1},100))
        self.assertFalse(h.eligible_failure({'attempts':3,'retry_after':1,'review_required':True},100))
    def test_quota_disk_and_stop_gates(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'DATA',Path(folder)),patch.object(h,'allowed',return_value=True),patch.object(h.shutil,'disk_usage',return_value=Mock(free=9*1024**3)):
            api=Mock();api.usage.return_value.remaining_bytes=10*h.core.MB
            with self.assertRaises(h.core.StopRun):h.Session(api).request('ticks')
            api.ticks.assert_not_called()
    def test_completed_part_survives_interruption(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'DATA',Path(folder)),patch.object(h.core,'contract',return_value='contract'),patch.object(h.core,'validate'):
            session=Mock();session.request.side_effect=[{'ts':[1]},RuntimeError('disconnect')]
            with self.assertRaises(RuntimeError):h.collect_pair(session,Mock(),'2330','2026-09-01','all')
            self.assertTrue((Path(folder)/'parts/2026-09-01/2330-ticks.json.gz').exists())
            session=Mock();session.request.return_value={'ts':[2]}
            with patch.object(h.core,'audit',return_value={}):h.collect_pair(session,Mock(),'2330','2026-09-01','all')
            session.request.assert_called_once()
            self.assertEqual(session.request.call_args.args[0],'kbars')
            self.assertTrue((Path(folder)/'raw/2026-09-01/2330.json.gz').exists())
    def test_calendar_extends_not_replaces_existing_dates(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'DATA',Path(folder)),patch.object(h.core,'contract',return_value='contract'),patch.object(h.core,'validate',return_value=[datetime(2026,8,3,10)]):
            plan={'dates':['2026-09-01'],'symbols':['2330']};session=Mock();session.request.return_value={'ts':[1]}
            self.assertTrue(h.extend_calendar(session,Mock(),plan))
            self.assertEqual(plan['dates'],['2026-08-03','2026-09-01'])
            self.assertEqual(plan['days'],2)

if __name__=='__main__':unittest.main()
