from datetime import datetime,date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import daily_history as h

class Tests(unittest.TestCase):
    def test_frozen_pool_supports_200_unique_symbols(self):
        symbols=[str(1000+i) for i in range(200)]
        plan={'symbols':symbols,'dates':['2026-09-01']}
        self.assertEqual(h.validate_plan(plan)['symbols'],symbols)
        for invalid in (symbols+['2000'],symbols[:-1]+[symbols[0]],['ETF']):
            with self.assertRaises(ValueError):
                h.validate_plan(dict(plan,symbols=invalid))

    def test_progress_uses_actual_pool_size_without_resetting_archives(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'DATA',Path(folder)):
            plan={'dates':['2026-09-01'],'symbols':[str(1000+i) for i in range(100)]}
            cached=Path(folder)/'raw/2026-09-01/1000.json.gz'
            cached.parent.mkdir(parents=True);cached.write_bytes(b'keep-existing-archive')
            result=h.summarize(plan,'test')
            self.assertEqual(result['symbol_count'],100)
            self.assertEqual(result['target_stock_days'],100)
            self.assertEqual(result['archived_stock_days'],1)
            self.assertEqual(cached.read_bytes(),b'keep-existing-archive')

    def test_window_every_day_taipei(self):
        settings={'history_window_start':'14:00','history_window_end':'22:00','history_weekends':False}
        for day in (15,19,20):
            for hour,expected in [(8,False),(13,False),(14,True),(21,True),(22,False)]:
                if datetime(2026,9,day).weekday() >= 5: expected=False
                self.assertEqual(h.allowed(datetime(2026,9,day,hour,tzinfo=h.core.TPE),settings),expected)
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

    def test_recent_dates_append_without_changing_old_cursor(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(h,'DATA',Path(folder)),patch.object(h.core,'contract',return_value='contract'),patch.object(h.core,'validate',return_value=[datetime(2026,9,24,13,30)]):
            plan={'dates':['2023-09-04','2026-09-10'],'symbols':['2330'],'calendar_before':'2023-09-01'}
            session=Mock();session.request.return_value={'ts':[1]}
            self.assertTrue(h.extend_recent_calendar(session,Mock(),plan,date(2026,9,27)))
            self.assertEqual(plan['dates'],['2023-09-04','2026-09-10','2026-09-24'])
            self.assertEqual(plan['end'],'2026-09-24')
            self.assertEqual(plan['calendar_before'],'2023-09-01')
            self.assertEqual(session.request.call_args.kwargs['start'],'2026-09-11')

    def test_empty_or_out_of_range_calendar_does_not_invent_dates(self):
        plan={'dates':['2026-09-24'],'symbols':['2330']}
        with patch.object(h.core,'contract',return_value='contract'):
            session=Mock();session.request.return_value={'ts':[]}
            self.assertFalse(h.extend_recent_calendar(session,Mock(),plan,date(2026,9,27)))
            self.assertEqual(plan['dates'],['2026-09-24'])
            session.request.return_value={'ts':[1]}
            with patch.object(h.core,'validate',return_value=[datetime(2026,9,28,10)]):
                with self.assertRaises(ValueError):h.extend_recent_calendar(session,Mock(),plan,date(2026,9,27))

    def test_expansion_preserves_55_and_adds_top_45_normal_stocks(self):
        original=[str(1000+i) for i in range(55)]
        plan={'symbols':original,'dates':['2026-09-10'],'selection_snapshot_date':'old'}
        rows=[{'code':str(2000+i),'total_amount':100-i} for i in range(60)]
        rows += [{'code':'0050','total_amount':999999},{'code':'BAD','total_amount':999999}]
        expanded=h.expanded_pool(plan,rows,100,'2026-09-27')
        self.assertEqual(expanded['symbols'][:55],original)
        self.assertEqual(expanded['symbols'][55:],[str(2000+i) for i in range(45)])
        self.assertEqual(plan['symbols'],original)
        self.assertEqual(expanded['selection_snapshot_date'],'old')
        with self.assertRaises(ValueError):h.expanded_pool(plan,[],100,'now')

if __name__=='__main__':unittest.main()
