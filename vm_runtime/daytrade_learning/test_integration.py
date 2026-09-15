import ast
import copy
from datetime import datetime,timedelta,timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from daytrade_learning.research import dt,normalize_bars,simulate,build,save,train_candidate
from daytrade_learning.daily_state import prepare_rollover
TPE=timezone(timedelta(hours=8))
COSTS=json.loads((ROOT/'daytrade_learning/settings.json').read_text())

def fixture():
    day='2026-09-10'
    sample={'symbol':'TEST','observed_at':day+'T09:30:00+08:00','quote_at':day+'T09:30:00+08:00',
        'price':100,'return_5m_pct':.2,'metrics':{'surge_60s':2,'buy_ratio_60s':.6,'classified_ratio_60s':.8,'amount_60s':5000000,'history_seconds':350},
        'radar_selected':True,'policy':{'stop_loss_pct':.008,'take_profit_pct':.012}}
    pack={'date':day,'previous_close':{'price':100,'date':'2026-09-09'},'limit_up':110,'limit_down':90,
        'bars':[{'at':day+'T09:31:00+08:00','open':100,'high':103,'low':98,'close':101,'volume':100}]}
    return sample,pack

class ResearchTests(unittest.TestCase):
    def test_timezone_right_edge(self):
        payload={'ts':[1779094860000000000],'Open':[100],'High':[101],'Low':[99],'Close':[100],'Volume':[10]}
        got=normalize_bars(payload,'2026-05-18')
        self.assertEqual(got['bars'][0]['at'],'2026-05-18T09:00:00+08:00')
    def test_previous_close_requires_full_day(self):
        payload={'ts':['2026-09-09T13:29:00','2026-09-10T09:01:00'],'Open':[100,100],'High':[101,101],'Low':[99,99],'Close':[100,100],'Volume':[10,10]}
        self.assertIsNone(normalize_bars(payload,'2026-09-10')['previous_close'])
    def test_ambiguous_bar_stop_first_and_costs(self):
        s,p=fixture(); row,why=simulate(s,p,COSTS)
        self.assertIsNone(why);self.assertLess(row['net_return_pct'],0)
        self.assertEqual(row['reason'],'stop_or_ambiguous_bar');self.assertGreater(row['cost_twd'],0)
    def test_missing_bar_not_profitable(self):
        s,p=fixture();p['bars']=[]
        self.assertEqual(simulate(s,p,COSTS)[1],'no_entry_bar')
    def test_missing_limits_blocks(self):
        s,p=fixture();p.pop('limit_up')
        self.assertEqual(simulate(s,p,COSTS)[1],'missing_price_limits')
    def test_locked_exit_not_filled(self):
        s,p=fixture();p['bars'][0]['low']=90
        self.assertEqual(simulate(s,p,COSTS)[1],'possible_locked_exit')
    def test_future_quote_rejected(self):
        s,p=fixture();s['quote_at']='2026-09-10T09:31:00+08:00'
        self.assertEqual(simulate(s,p,COSTS)[1],'stale_quote')
    def test_fill_gain_rechecked(self):
        s,p=fixture();p['bars'][0]['open']=106
        self.assertEqual(simulate(s,p,COSTS)[1],'fill_filter')
    def test_corrupt_and_duplicate_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            s,p=fixture();data=Path(folder)
            save(data/'bars/2026-09-10/TEST.json',p)
            row=json.dumps({'kind':'sample','data':s})
            (data/'journal-2026-09-10.jsonl').write_text(row+'\n'+row+'\n'+'bad line\n')
            result=build(data,'2026-09-10',COSTS)
            self.assertEqual(result['labeled_count'],1);self.assertEqual(result['corrupt_journal_lines'],1)
    def test_training_dates_and_no_deploy(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(101):
                day=(datetime(2025,1,1)+timedelta(days=i)).date().isoformat()
                rows=[{'date':day,'at':day+f'T09:{30+j}:00+08:00','symbol':str(j),'profile':'p1',
                       'features':[j,j%3,2,.6,5000000],'net_return_pct':1 if j%2 else -1,'radar_selected':j<3} for j in range(10)]
                save(Path(folder)/'labels'/(day+'.json'),rows)
            result=train_candidate(folder)
            if result['status']=='blocked':self.skipTest(result['reason'])
            self.assertFalse(result['deployment_allowed']);self.assertEqual(len(result['folds']),3)
            for fold in result['folds']:
                self.assertLess(fold['train_through'],fold['gap_date']);self.assertLess(fold['gap_date'],fold['test_from'])

class StateTests(unittest.TestCase):
    def test_rollover_drops_old_closed_keeps_history_source(self):
        old={'scan_date':'2026-09-09','closed_trades':{'a':{'entry_time':'2026-09-09T10:00:00+08:00'}}}
        before=copy.deepcopy(old)
        new=prepare_rollover(old,{'scan_date':'2026-09-10'})
        self.assertEqual(new['closed_trades'],{});self.assertEqual(old,before)
    def test_no_silent_previous_open_deletion(self):
        with self.assertRaises(RuntimeError):
            prepare_rollover({'open_positions':{'a':{'entry_time':'2026-09-09T10:00:00+08:00'}}},{'scan_date':'2026-09-10'})
    def test_same_day_preserved(self):
        old={'scan_date':'2026-09-10','open_positions':{'a':{'entry_time':'2026-09-10T10:00:00+08:00'}}}
        self.assertEqual(prepare_rollover(old,{'scan_date':'2026-09-10'})['open_positions'],old['open_positions'])
    def test_report_counts_zero_and_all_four_closed(self):
        spec=importlib.util.spec_from_file_location('report_under_test',ROOT/'line_hub_service.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        day=datetime.now(TPE).date().isoformat()
        closed={str(i):{'name':str(i),'entry_time':day+'T10:00:00+08:00','status':'CLOSED','pnl_pct':p} for i,p in enumerate([0,1,-1,2])}
        root={'scan_date':day,'closed_trades':closed,'open_positions':{'p':{'entry_time':day+'T10:00:00+08:00','pnl_pct':99}}}
        mod._read=lambda _:root
        text=mod.latest_daytrade_text()
        self.assertIn('推薦 5 筆',text);self.assertIn('50.0%（2/4）',text);self.assertNotIn('99.00',text)
        self.assertIn('0.00%',text)
    def test_live_ticks_create_and_complete_minute_bar(self):
        import threading
        from collections import defaultdict
        tree=ast.parse((ROOT/'intraday_live.py').read_text(encoding='utf-8'))
        names={'Bar','LiveBarBook','floor_minute'}
        selected=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
        self.assertEqual({n.name for n in selected},names)
        ctx={'datetime':datetime,'threading':threading,'defaultdict':defaultdict,'TPE':TPE}
        source='from __future__ import annotations\n'+ '\n'.join(ast.unparse(n) for n in selected)
        exec(compile(source,'<live-bars>','exec'),ctx)
        book=ctx['LiveBarBook']()
        start=datetime(2026,9,11,9,0,tzinfo=TPE)
        book.on_tick('TEST',100,2,start)
        book.on_tick('TEST',102,3,start+timedelta(seconds=20))
        book.on_tick('TEST',99,1,start+timedelta(seconds=40))
        book.on_tick('TEST',101,4,start+timedelta(minutes=1))
        finished=book.completed_1m['TEST']
        self.assertEqual(len(finished),1)
        self.assertEqual((finished[0].open,finished[0].high,finished[0].low,finished[0].close,finished[0].volume),(100,102,99,99,6))
        self.assertEqual(book.current_1m['TEST'].start,start+timedelta(minutes=1))

    def test_fresh_entry_uses_quote_not_stale_metadata(self):
        tree=ast.parse((ROOT/'intraday_live.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='IntradayLiveEngine')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='fresh_entry_quote')
        module=ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[]))
        now=datetime(2026,9,10,10,0,tzinfo=TPE)
        import threading,time
        ctx={'now_tpe':lambda:now,'time':time,'timedelta':timedelta,'dtime':datetime.min.time().__class__,
             'math':math,'os':os,'in_entry_window':lambda _:True,
             'read_live_settings':lambda:{'min_price':float(os.environ.get('DAYTRADE_MIN_PRICE','1')),
                                         'max_price':float(os.environ.get('DAYTRADE_MAX_PRICE','200')),
                                         'max_gain_pct':float(os.environ.get('DAYTRADE_MAX_GAIN_PCT','5'))}}
        exec(compile(module,'<extracted>','exec'),ctx)
        engine=SimpleNamespace(_previous_closes={'TEST':('2026-09-10',100)},_previous_close_retry={},
            _lock=threading.RLock(),radar_ticks={'TEST':[(now.timestamp(),1,1,106,1)]})
        with patch.dict(os.environ,{'DAYTRADE_MAX_GAIN_PCT':'5','DAYTRADE_MIN_PRICE':'1','DAYTRADE_MAX_PRICE':'200'}):
            self.assertIsNone(ctx['fresh_entry_quote'](engine,'TEST'))
            engine.radar_ticks['TEST']=[(now.timestamp(),1,1,105,1)]
            self.assertEqual(ctx['fresh_entry_quote'](engine,'TEST')[0],105)
            engine.radar_ticks['TEST']=[(now.timestamp()-31,1,1,100,1)]
            self.assertIsNone(ctx['fresh_entry_quote'](engine,'TEST'))

if __name__=='__main__':unittest.main()
