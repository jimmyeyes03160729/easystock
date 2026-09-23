import copy
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import common
from common import TPE, classify, permitted_actions
import live
import worker
import supervisor

CAL={'year':2026,'closed':['2026-09-25','2026-09-28']}
def stamp(day='2026-09-23',time='10:00:00'):
    return dt.datetime.fromisoformat(day+'T'+time+'+08:00')
def healthy():
    return {'scan_date':'2026-09-23','last_update_at':'2026-09-23T09:59:30+08:00','radar_at':'2026-09-23T09:59:30+08:00',
            'session':'daytrade','service_active':'active','ledger_positions':0,'remote_positions':0,'valid_remote_positions':0,
            'ledger_mismatch':False,'ghost_symbols':[],'syntax_errors':[],'orders_enabled':False}

class Policy(unittest.TestCase):
    def test_oneshot_worker_blocks_second_incident(self):
        for state in ('active','activating','deactivating'):
            with patch.object(supervisor.subprocess,'run',lambda *a,**kw:type('R',(),{'stdout':state})()):
                self.assertTrue(supervisor.worker_running())
        with patch.object(supervisor.subprocess,'run',lambda *a,**kw:type('R',(),{'stdout':'inactive'})()):
            self.assertFalse(supervisor.worker_running())
    def test_healthy(self):self.assertEqual(classify(healthy(),stamp(),CAL),[])
    def test_holiday(self):self.assertEqual(classify({},stamp('2026-09-25'),CAL),[])
    def test_weekend(self):self.assertEqual(classify({},stamp('2026-09-26'),CAL),[])
    def test_calendar_failure(self):self.assertEqual(permitted_actions(healthy(),stamp(),None),['investigate'])
    def test_after_hours_no_restart(self):self.assertNotIn('restart_intraday',permitted_actions(healthy(),stamp(time='14:00:00'),CAL))
    def test_preopen_grace(self):self.assertEqual(classify({},stamp(time='08:56:00'),CAL),[])
    def test_stale(self):
        s=healthy();s['last_update_at']='2026-09-22T13:00:00+08:00'
        self.assertIn('snapshot_stale',classify(s,stamp(),CAL))
    def test_future_clock(self):
        s=healthy();s['last_update_at']='2026-09-23T10:02:00+08:00'
        self.assertIn('snapshot_stale',classify(s,stamp(),CAL))
    def test_quotes_stale(self):
        s=healthy();s['radar_at']='2026-09-23T09:00:00+08:00'
        self.assertIn('quotes_stale',classify(s,stamp(),CAL))
    def test_missing_session_after_close(self):
        s=healthy();s['scan_date']='2026-09-22'
        self.assertIn('session_missing',classify(s,stamp(time='13:10:00'),CAL))
    def test_open_blocks_restart(self):
        s=healthy();s['ledger_positions']=1
        self.assertNotIn('restart_intraday',permitted_actions(s,stamp(),CAL))
    def test_mismatch_blocks_restart(self):
        s=healthy();s['ledger_mismatch']=True
        self.assertNotIn('restart_intraday',permitted_actions(s,stamp(),CAL))
    def test_mode_change_blocks_restart(self):
        s=healthy();s['orders_enabled']=True
        self.assertNotIn('restart_intraday',permitted_actions(s,stamp(),CAL))
    def test_cutoff_blocks_restart(self):
        self.assertNotIn('restart_intraday',permitted_actions(healthy(),stamp(time='12:30:00'),CAL))
    def test_empty_paper_allows_restart(self):self.assertIn('restart_intraday',permitted_actions(healthy(),stamp(),CAL))
    def test_active_blocks_quarantine(self):
        s=healthy();s['ghost_symbols']=['2327']
        self.assertNotIn('quarantine_unfilled_ghosts',permitted_actions(s,stamp(),CAL))
    def test_known_ghost_stopped_allows_quarantine(self):
        s=healthy();s.update(ghost_symbols=['2327'],service_active='failed',remote_positions=1)
        self.assertIn('quarantine_unfilled_ghosts',permitted_actions(s,stamp(),CAL))
    def test_restart_loop_allows_guarded_quarantine(self):
        s=healthy();s.update(ghost_symbols=['2327'],service_active='activating',service_substate='auto-restart',remote_positions=1)
        self.assertIn('quarantine_unfilled_ghosts',permitted_actions(s,stamp(),CAL))
    def test_read_error_blocks_actions(self):self.assertEqual(permitted_actions({'read_error':'error'},stamp(),CAL),['investigate'])

class Ref:
    def __init__(self,state,path=()):self.state=state;self.path=path
    def child(self,key):return Ref(self.state,self.path+(key,))
    def get(self):
        v=self.state
        for k in self.path:v=v.get(k,{})
        return copy.deepcopy(v)
    def set(self,value):
        p=self.state
        for k in self.path[:-1]:p=p.setdefault(k,{})
        p[self.path[-1]]=copy.deepcopy(value)
    def transaction(self,fn):self.set(fn(self.get()))

class DataRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.state={'intraday_live':{'scan_date':'2026-09-22','closed_trades':{'old':{'status':'CLOSED'}},'open_positions':{'2327':{'status':'OPEN','current_price':570,'last_update_at':'2026-09-22T09:57:16+08:00'}}}}
        self.reference=Ref(self.state)
        self.db=self.base/'test.sqlite'
        c=sqlite3.connect(self.db)
        c.executescript('create table paper_trade_positions(symbol text,entry_date text,entry_price real,shares integer); create table paper_trade_fills(symbol text,trade_date text); create table paper_trade_events(symbol text,date text,action text);')
        c.execute('insert into paper_trade_events values(?,?,?)',('2327','2026-09-22','略過'));c.commit();c.close()
        for name in ('firebase_store.py','intraday_live.py','position_manager.py'):(self.base/name).write_text('x=1\n')
        (self.base/'baseline').mkdir();common.write_json(self.base/'baseline/manifest.json',{})
        self.patches=[patch.object(live,'APP',self.base),patch.object(live,'ROOT',self.base),patch.object(live,'STATE',self.base/'state'),patch.object(live,'database',lambda:self.reference),patch.object(live,'ledger',self.connection),patch.object(live,'active',lambda:'failed'),patch.object(live.subprocess,'run',lambda *a,**kw:type('R',(),{'stdout':'AI_PAPER_MODE=1'})())]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def connection(self):
        c=sqlite3.connect(self.db);c.row_factory=sqlite3.Row;return c
    def test_identifies_proven_unfilled_ghost(self):self.assertEqual(live.inspect_state()[0]['ghost_symbols'],['2327'])
    def test_any_fill_blocks_quarantine(self):
        with self.connection() as c:c.execute('insert into paper_trade_fills values(?,?)',('2327','2026-09-22'))
        self.assertEqual(live.inspect_state()[0]['ghost_symbols'],[])
        with self.assertRaises(RuntimeError):live.quarantine()
    def test_complete_entry_is_not_ghost(self):
        self.state['intraday_live']['open_positions']['2327']['entry_time']='2026-09-22T09:57:16+08:00'
        self.assertEqual(live.inspect_state()[0]['ghost_symbols'],[])
    def test_no_skip_evidence_blocks(self):
        with self.connection() as c:c.execute('delete from paper_trade_events')
        self.assertEqual(live.inspect_state()[0]['ghost_symbols'],[])
    def test_archive_and_preserve_closed_trades(self):
        original=copy.deepcopy(self.state['intraday_live']);result=live.quarantine()
        self.assertEqual(self.state['intraday_archive'][result['archive_key']],original)
        self.assertNotIn('open_positions',self.state['intraday_live'])
        self.assertEqual(self.state['intraday_live']['closed_trades'],original['closed_trades'])
        self.assertEqual(self.state['intraday_live']['scan_date'],'2026-09-22')
    def test_running_service_blocks(self):
        with patch.object(live,'active',lambda:'active'):
            with self.assertRaises(RuntimeError):live.quarantine()

class Deployment(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        (self.base/'baseline').mkdir();(self.base/'app').mkdir()
        self.baseline=self.base/'baseline/firebase_store.py';self.baseline.write_text('value=1\n')
        self.target=self.base/'app/firebase_store.py';self.target.write_text('broken = (\n')
        common.write_json(self.base/'baseline/manifest.json',{'firebase_store.py':common.digest(self.baseline.read_bytes())})
        self.s=healthy();self.s.update(service_active='failed',syntax_errors=['firebase_store.py'],restorable_syntax_error=True,source_hashes={'firebase_store.py':common.digest(self.target.read_bytes())})
        self.patches=[patch.object(worker,'ROOT',self.base),patch.object(worker,'APP',self.base/'app'),patch.object(worker,'STATE',self.base/'state'),patch.object(worker,'now',lambda:stamp()),patch.object(worker,'calendar',lambda:CAL),patch.object(worker.subprocess,'run',lambda *a,**kw:type('R',(),{'returncode':0})()),patch.object(worker.os,'chown',lambda *a:None)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def test_restore_and_backup(self):
        before=self.target.read_bytes();result=worker.restore_adapter(self.s,'test')
        self.assertEqual(self.target.read_bytes(),self.baseline.read_bytes())
        self.assertEqual((Path(result['backup'])/'firebase_store.py').read_bytes(),before)
    def test_external_edit_blocks_deployment(self):
        self.target.write_text('external=2\n')
        with self.assertRaises(RuntimeError):worker.restore_adapter(self.s,'test')
        self.assertEqual(self.target.read_text(),'external=2\n')
    def test_invalid_deployment_rolls_back(self):
        before=self.target.read_bytes();self.baseline.write_text('bad = (\n')
        common.write_json(self.base/'baseline/manifest.json',{'firebase_store.py':common.digest(self.baseline.read_bytes())})
        with self.assertRaises(SyntaxError):worker.restore_adapter(self.s,'test')
        self.assertEqual(self.target.read_bytes(),before)
    def test_open_position_blocks_deployment(self):
        self.s['ledger_positions']=1
        with self.assertRaises(RuntimeError):worker.restore_adapter(self.s,'test')

if __name__=='__main__':unittest.main()
