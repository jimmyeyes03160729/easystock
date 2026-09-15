import copy
import io
from datetime import datetime,timezone,timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from daytrade_learning import research as r
from daytrade_learning.eod_support import ai_input,review_once,report_status
DAY='2026-09-11'
OBS=[{'kind':'sample','data':{'symbol':'6696','observed_at':DAY+'T10:00:00+08:00'}}]
RAW={'ts':[DAY+'T13:30:00+08:00'],'Open':[100],'High':[101],'Low':[99],'Close':[100],'Volume':[1]}

class FixTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
        self.sj=SimpleNamespace(ScannerType=SimpleNamespace(ChangePercentRank=1,DayRangeRank=2,AmountRank=3))
        contract=SimpleNamespace(update_date=DAY,limit_up=110,limit_down=90)
        self.api=SimpleNamespace(Contracts=SimpleNamespace(Stocks=SimpleNamespace(TSE={'6696':contract},OTC={})),scanners=Mock(return_value=[]),kbars=Mock(return_value=RAW))
    def tearDown(self):self.tmp.cleanup()
    def collect(self):
        with patch.dict(sys.modules,{'shioaji':self.sj}),patch('time.sleep'):
            return r.collect(self.api,self.data,DAY,OBS)
    def test_no_today_bars_reason_once(self):
        self.api.kbars.return_value={}
        c=self.collect();self.assertEqual(c['failure_details']['6696']['reason'],'no_today_bars');self.assertEqual(self.api.kbars.call_count,1)
    def test_contract_missing_without_kbars(self):
        self.api.Contracts.Stocks.TSE={}
        c=self.collect();self.assertEqual(c['failure_details']['6696']['reason'],'contract_missing');self.api.kbars.assert_not_called()
    def test_bad_ohlcv_not_retried(self):
        self.api.kbars.return_value={**RAW,'Low':[200]}
        c=self.collect();self.assertEqual(c['failure_details']['6696']['reason'],'bad_ohlcv');self.assertEqual(self.api.kbars.call_count,1)
    def test_transient_then_success(self):
        self.api.kbars.side_effect=[TimeoutError('private error'),RAW]
        c=self.collect();self.assertEqual(c['downloaded'],1);self.assertEqual(self.api.kbars.call_count,2)
    def test_transient_bounded_and_private(self):
        self.api.kbars.side_effect=TimeoutError('secret-token-in-sdk')
        c=self.collect();self.assertEqual(self.api.kbars.call_count,2);self.assertNotIn('secret-token',json.dumps(c));self.assertEqual(c['failure_details']['6696']['attempts'],2)
    def test_cached_success_not_downloaded_again(self):
        self.collect();self.api.kbars.reset_mock()
        c=self.collect();self.api.kbars.assert_not_called();self.assertEqual(c['cached'],1)
    def test_corrupt_cache_is_replaced_by_success(self):
        p=self.data/'bars'/DAY/'6696.json';p.parent.mkdir(parents=True);p.write_text('{bad')
        c=self.collect();self.assertEqual(c['downloaded'],1);self.assertEqual(json.loads(p.read_text())['date'],DAY)
    def test_scanner_retries_are_bounded_and_named(self):
        self.api.scanners.side_effect=ConnectionError('secret')
        c=self.collect();self.assertEqual(self.api.scanners.call_count,6);self.assertEqual(len(c['scanner_error_details']),3);self.assertNotIn('secret',json.dumps(c))
    def test_disk_error_not_hidden_as_partial(self):
        with patch.object(r,'save',side_effect=PermissionError('disk')):
            with self.assertRaises(PermissionError):self.collect()
    def report(self):return {'date':DAY,'version':'research2','status':'ready','sample_count':5,'bars_symbols':1,'labeled_count':2,'collection':{'requested':2,'downloaded':1,'failed':{'6696':'ValueError'},'scanner_errors':[],'omitted_by_cap':0,'scope':'test'}}
    def test_legacy_review_preserved_and_new_cache_reused(self):
        prior=self.report();prior['ai']={'status':'ok','model':'test-model','review':{'summary':'old'}}
        current=self.report();current['collection'].update(cached=1,failure_details={'6696':{'reason':'no_today_bars'}})
        reviewer=Mock()
        with patch.dict(os.environ,{'GEMINI_REVIEW_MODEL':'test-model'}):
            answer,meta=review_once(self.data,DAY,current,prior,reviewer)
            self.assertEqual(answer,prior['ai']);self.assertEqual(meta['source'],'previous_report')
            answer,meta=review_once(self.data,DAY,current,{},reviewer);self.assertEqual(meta['source'],'cache')
        reviewer.assert_not_called()
    def test_changed_data_and_model_invalidate_cache(self):
        reviewer=Mock(return_value={'status':'ok','model':'a'})
        report=self.report()
        with patch.dict(os.environ,{'GEMINI_REVIEW_MODEL':'a'}):
            review_once(self.data,DAY,report,{},reviewer)
            report['labeled_count']+=1;review_once(self.data,DAY,report,{},reviewer)
        with patch.dict(os.environ,{'GEMINI_REVIEW_MODEL':'b'}):review_once(self.data,DAY,report,{},reviewer)
        self.assertEqual(reviewer.call_count,3)
    def test_ai_failures_bounded_across_runs_and_explicit_reset(self):
        reviewer=Mock(return_value={'status':'failed','error_type':'HTTPError'})
        with patch.dict(os.environ,{'GEMINI_REVIEW_MODEL':'test'}):
            for _ in range(4):answer,meta=review_once(self.data,DAY,self.report(),{},reviewer)
            self.assertEqual(reviewer.call_count,2);self.assertEqual(answer['reason'],'ai_attempt_limit')
            review_once(self.data,DAY,self.report(),{},reviewer,reset=True);self.assertEqual(reviewer.call_count,3)
    def test_partial_and_total_failure_are_distinct(self):
        report=self.report();self.assertEqual(report_status(report),'partial')
        report['collection']['downloaded']=0;self.assertEqual(report_status(report),'failed')
    def test_build_does_not_overwrite_successful_report_mid_run(self):
        p=self.data/'reports'/(DAY+'.json');r.save(p,{'ai':{'status':'ok'}})
        costs=json.loads((ROOT/'daytrade_learning/settings.json').read_text())
        r.build(self.data,DAY,costs,persist_report=False)
        self.assertEqual(json.loads(p.read_text()),{'ai':{'status':'ok'}})
    def test_main_partial_saves_and_returns_success_total_failure_does_not(self):
        from daytrade_learning import runtime,core
        spec=importlib.util.spec_from_file_location('eod_test',ROOT/'learning_eod.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,9,11,14,30,tzinfo=timezone(timedelta(hours=8)))
        self.api.login=Mock();self.api.logout=Mock();self.sj.Shioaji=Mock(return_value=self.api)
        for count in (1,0):
            report=self.report();report['collection']['downloaded']=count
            with patch.object(mod,'datetime',Clock),patch.object(runtime,'DATA',self.data),patch.object(r,'journal',return_value=(OBS,0)),patch.object(r,'collect',return_value=report['collection']),patch.object(r,'build',return_value=copy.deepcopy(report)),patch.object(core,'gemini_review',return_value={'status':'ok','model':'test'}),patch.dict(sys.modules,{'shioaji':self.sj}),patch.dict(os.environ,{'SJ_API_KEY':'test','SJ_SECRET_KEY':'test','GEMINI_REVIEW_MODEL':'test'}),patch.object(sys,'argv',['learning_eod.py','--collect','--gemini','--date',DAY]),patch('sys.stdout',new_callable=io.StringIO):
                if count==0:
                    with self.assertRaises(SystemExit):mod.main()
                else:mod.main()
            saved=json.loads((self.data/'reports'/(DAY+'.json')).read_text())
            self.assertEqual(saved['status'],'partial' if count else 'failed')

if __name__=='__main__':unittest.main()
