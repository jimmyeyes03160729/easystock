"""Offline regression coverage: no broker, Firebase, LINE or production SQLite."""
import ast
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from daytrade_learning.model_runtime import DaytradeModel, live_features
from daytrade_learning.features import FEATURES, SCHEMA_VERSION
from market_risk import premarket_context, snapshot_risk, combine
from position_manager import PositionManager
from easystock_admin.store import Store
import paper_account

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026,9,24,10,tzinfo=TPE)


def artifact(**overrides):
    return dict(dict(approved=True,deployment_allowed=True,schema_version=SCHEMA_VERSION,
                     features=list(FEATURES),mean=[0]*5,scale=[1]*5,coef=[0]*5,
                     intercept=0,threshold=.6,version='fixture',
                     trained_through=datetime.now(TPE).date().isoformat(),
                     profile='fixture-profile'),**overrides)


class ModelTests(unittest.TestCase):
    def model(self, **changes):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.json'; p.write_text(json.dumps(artifact(**changes)))
            return DaytradeModel(p)

    def test_unapproved_and_missing_models_block(self):
        for m in (DaytradeModel(path=''),self.model(approved=False),self.model(deployment_allowed=False)):
            self.assertFalse(m.evaluate(dict.fromkeys(FEATURES,0))['accepted'])

    def test_threshold_actually_rejects(self):
        self.assertFalse(self.model().evaluate(dict.fromkeys(FEATURES,0))['accepted'])
        self.assertTrue(self.model(threshold=.5).evaluate(dict.fromkeys(FEATURES,0))['accepted'])

    def test_schema_order_and_nan_rejected(self):
        for overrides in ({'features':list(reversed(FEATURES))},{'scale':[0]*5},{'intercept':float('nan')},{'coef':[0]*4}):
            self.assertFalse(self.model(**overrides).evaluate(dict.fromkeys(FEATURES,1))['active'])
        self.assertFalse(self.model(threshold=.4).evaluate({})['accepted'])
        self.assertFalse(self.model(threshold=.4).evaluate(dict.fromkeys(FEATURES,float('nan')))['accepted'])

    def test_live_features_no_imputed_zero(self):
        radar=dict(surge_60s=2,buy_ratio_60s=.6,amount_60s=1000000,classified_ratio_60s=.8,history_seconds=301)
        ticks=[(700,1,1,100,100),(1000,1,1,101,101)]
        args=dict(price=101,previous_close=100,now_ts=1000,ticks=ticks,radar=radar)
        self.assertAlmostEqual(live_features(**args)['return_5m_pct'],1)
        self.assertIsNone(live_features(**dict(args,ticks=[])))
        self.assertIsNone(live_features(**dict(args,radar=dict(radar,amount_60s=None))))
        self.assertIsNone(live_features(**dict(args,now_ts=1050)))


class RiskTests(unittest.TestCase):
    def test_ai_advisory_cannot_flip_gate(self):
        brief=dict(scan_date='2026-09-24',generated_at=NOW.isoformat(),base_risk_score=64,risk_score=69,market_level='RED')
        self.assertEqual(premarket_context(brief,NOW)[0],'YELLOW')
        brief['scan_date']='2026-09-23'
        self.assertEqual(premarket_context(brief,NOW)[0],'UNKNOWN')

    def test_live_index_stale_future_missing_and_crash(self):
        for seconds in (-91,1):
            q=dict(ts=(NOW.replace(tzinfo=timezone.utc).timestamp()+seconds)*1e9,change_rate=0)
            self.assertFalse(snapshot_risk(q,NOW)['valid'])
        self.assertFalse(snapshot_risk({},NOW)['valid'])
        q=dict(ts=NOW.replace(tzinfo=timezone.utc).timestamp()*1e9,change_rate=-2.1)
        self.assertEqual(combine('GREEN',snapshot_risk(q,NOW)['level']),'RED')


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=Path(self.folder.name)/'state.sqlite'
        self.env=patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.db)})
        self.env.start()
        Store(initial=dict(min_price=1,max_price=1000,max_gain_pct=5)).start_paper_trade(200000)

    def tearDown(self):
        self.env.stop();self.folder.cleanup()

    def manager(self, **kw):
        return PositionManager(before_open=paper_account.buy,
            before_close=lambda **a:paper_account.sell(a['symbol'],a['exit_price'],a['exit_reason'],a['trade_id']),**kw)

    def open(self,m,symbol='TEST',price=100):
        return m.open_position(symbol,symbol,price,NOW,90,['test'])

    def test_no_fill_means_no_signal_position(self):
        m=self.manager()
        self.assertIsNone(self.open(m,price=500))
        self.assertFalse(m.positions)
        self.assertFalse(m.traded_symbols)
        with sqlite3.connect(self.db) as db:db.execute("UPDATE paper_trade_settings SET status='stopped'")
        self.assertIsNone(self.open(m))

    def test_parallel_buys_reserve_cash(self):
        with ThreadPoolExecutor(2) as pool:
            fills=list(pool.map(lambda symbol:paper_account.buy(symbol,symbol,100),['A','B']))
        self.assertEqual(sum(x['status']=='bought' for x in fills),1)
        self.assertEqual(len(paper_account.open_positions()),1)

    def test_duplicate_exit_and_daily_aggregation(self):
        m=self.manager();self.open(m)
        with ThreadPoolExecutor(2) as pool:
            events=list(pool.map(lambda _:m.close_position('TEST',101,NOW,'test'),range(2)))
        self.assertEqual(sum(x is not None for x in events),1)
        with sqlite3.connect(self.db) as db:db.execute('UPDATE paper_trade_settings SET daily_buy_limit=400000')
        self.open(m,symbol='OTHER')
        m.close_position('OTHER',101,NOW,'test')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT trades_count FROM paper_trade_logs').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paper_trade_positions').fetchone()[0],0)

    def test_settlement_failure_keeps_both_positions(self):
        m=self.manager();self.open(m)
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_settle BEFORE INSERT ON paper_trade_fills WHEN NEW.side='SELL' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):m.close_position('TEST',101,NOW,'test')
        self.assertTrue(m.has_open_position('TEST'))
        self.assertEqual(len(paper_account.open_positions()),1)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT settlement_status FROM paper_trade_logs').fetchone()[0],'pending')

    def test_receipt_retry_does_not_settle_twice(self):
        fill=paper_account.buy('TEST','TEST',100)
        first=paper_account.sell('TEST',101,trade_id=fill['trade_id'])
        again=paper_account.sell('TEST',102,trade_id=fill['trade_id'])
        self.assertTrue(again['already_settled']);self.assertEqual(first['net_pnl'],again['net_pnl'])

    def test_trailing_mode_can_pass_fixed_target(self):
        m=self.manager(exit_mode='trailing');self.open(m)
        self.assertIsNone(m.on_tick('TEST',102,NOW))
        event=m.on_tick('TEST',101.5,NOW)
        self.assertEqual(event['trade']['exit_reason'],'移動停利')

    def test_hybrid_target_and_technical_policy(self):
        m=self.manager();self.open(m)
        self.assertEqual(m.on_tick('TEST',101.2,NOW)['trade']['exit_reason'],'固定停利')
        with sqlite3.connect(self.db) as db:db.execute('UPDATE paper_trade_settings SET daily_buy_limit=400000')
        m=self.manager(technical_exit_enabled=False);self.open(m,'OTHER')
        self.assertIsNone(m.on_strategy_result('OTHER',{'vetoes':['跌破VWAP'],'price':99.7},NOW))
        self.assertEqual(m.on_tick('OTHER',99,NOW)['trade']['exit_reason'],'固定停損')


class EngineTests(unittest.TestCase):
    """Execute the real orchestration method with inert external adapters."""
    def setUp(self):
        tree=ast.parse((ROOT/'intraday_live.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='IntradayLiveEngine')
        wanted=('evaluate_symbol','_entry_reject','log_entry_reject_summary','fresh_entry_quote')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
        result=dict(eligible=True,daytrade_score=90,vetoes=[],reasons=['one','two'],price=100)
        self.ns=dict(datetime=datetime,MIN_WARM_5M_BARS=1,MIN_WARM_15M_BARS=1,
            evaluate_daytrade=Mock(return_value=result),get_position_safe=lambda m,s:m.get_position(s),
            in_entry_window=lambda _:True,now_tpe=lambda:NOW,MAX_DAILY_ENTRIES=5,
            live_features=Mock(return_value=dict.fromkeys(FEATURES,1)),
            read_live_settings=lambda:dict(min_price=1,max_price=200,max_gain_pct=5),
            call_manager_strategy_result=lambda **kw: kw['manager'].on_strategy_result(kw['symbol'], kw['result'], kw['dt']),
            is_exit_event=lambda event: isinstance(event, dict) and event.get('type') == 'EXIT',
            push_line_text=Mock(),format_entry_message=Mock(return_value='entry'),
            time=types.SimpleNamespace(monotonic=lambda:self.mono),ENTRY_REJECT_LOG_SECONDS=300.0,
            ENTRY_REJECT_SUMMARY_SECONDS=60.0)
        self.mono=1000.0
        exec(compile(ast.Module(body=methods,type_ignores=[]),'<engine>','exec'),self.ns)
        self.manager=PositionManager(research_mode=True, before_open=Mock(return_value=dict(status='skipped',skip_reason='daily_buy_limit_exceeded',shares=0)))
        self.engine=types.SimpleNamespace(bars=types.SimpleNamespace(rows5=lambda _: [{}],rows15=lambda _:[{}]),
            candidates={'TEST':{}},market_level='GREEN',market_valid_until=NOW.timestamp()+30,
            entry_mode='rules',collect_only=False,last_prices={'TEST':100},manager=self.manager,scanner_top_symbols={'TEST'},
            fresh_entry_quote=Mock(return_value=(100,NOW)),_previous_closes={'TEST':(None,100)},
            _lock=threading.RLock(),radar_ticks={'TEST':[]},daytrade_model=DaytradeModel(path=''),
            entry_symbols=set(),_entry_limit_logged=False,learning=Mock(),store=Mock(),
            _entry_reject_counts={},_entry_reject_last={},_entry_reject_summary_at=0.0,_entry_reject_summary_logged={})
        for name in ('_entry_reject','log_entry_reject_summary'):
            setattr(self.engine,name,types.MethodType(self.ns[name],self.engine))

    def run_engine(self):self.ns['evaluate_symbol'](self.engine,'TEST',NOW)

    def captured(self,fn):
        from contextlib import redirect_stdout
        from io import StringIO
        output=StringIO()
        with redirect_stdout(output):
            fn()
        return output.getvalue()

    def test_market_block_logs_entry_reject_reason(self):
        self.engine.market_gate={'gate_action':'BLOCK','gate_reason':'market_data_unavailable'}
        self.engine._market_block_counts={'market_risk_red':0,'market_data_unavailable':0}
        out=self.captured(self.run_engine)
        self.assertIn('[ENTRY_REJECT] TEST reason=market_data_unavailable gate=BLOCK/market_data_unavailable',out)
        self.assertEqual(self.engine._entry_reject_counts,{'market_data_unavailable':1})

    def test_silent_exits_now_log_a_reason(self):
        self.engine.scanner_top_symbols=set()
        self.assertIn('reason=not_radar_top',self.captured(self.run_engine))
        self.engine.entry_mode='model'
        self.ns['evaluate_daytrade'].return_value['vetoes']=['5分K破短低']
        self.assertIn('reason=strategy_veto veto=5分K破短低',self.captured(self.run_engine))
        self.manager.before_open.assert_not_called()

    def test_repeated_reject_is_throttled_but_still_counted(self):
        self.engine.scanner_top_symbols=set()
        out=self.captured(lambda:[self.run_engine() for _ in range(5)])
        self.assertEqual(out.count('[ENTRY_REJECT]'),1)
        self.assertEqual(self.engine._entry_reject_counts['not_radar_top'],5)
        self.engine.scanner_top_symbols={'TEST'}
        self.ns['in_entry_window']=lambda _:False
        self.assertIn('reason=outside_entry_window',self.captured(self.run_engine))
        self.engine.scanner_top_symbols=set();self.ns['in_entry_window']=lambda _:True
        self.assertIn('reason=not_radar_top',self.captured(self.run_engine))
        self.assertNotIn('[ENTRY_REJECT]',self.captured(self.run_engine))
        self.mono+=301
        self.assertIn('reason=not_radar_top',self.captured(self.run_engine))

    def test_reject_summary_prints_only_when_counts_change(self):
        self.engine.scanner_top_symbols=set()
        self.captured(self.run_engine)
        out=self.captured(self.engine.log_entry_reject_summary)
        self.assertEqual(out.strip(),'[ENTRY_REJECT_SUMMARY] not_radar_top=1')
        self.assertEqual(self.captured(lambda:self.engine.log_entry_reject_summary(force=True)),'')
        self.captured(self.run_engine)
        self.assertEqual(self.captured(self.engine.log_entry_reject_summary),'')
        self.assertIn('not_radar_top=2',self.captured(lambda:self.engine.log_entry_reject_summary(force=True)))

    def test_incomplete_previous_day_bars_log_a_reason(self):
        bar=types.SimpleNamespace(start=NOW.replace(hour=13,minute=20)-timedelta(days=1),close=99.0)
        self.ns.update(timedelta=timedelta,kbars_to_1m=lambda payload:[bar],dtime=lambda h,m:NOW.replace(hour=h,minute=m).timetz().replace(tzinfo=None))
        self.engine.contracts={'TEST':object()};self.engine.api=Mock();self.engine._previous_closes={}
        self.engine._previous_close_retry={}
        out=self.captured(lambda:self.assertIsNone(self.ns['fresh_entry_quote'](self.engine,'TEST',allow_lookup=True)))
        self.assertIn('[ENTRY_REJECT] TEST reason=previous_close_incomplete bars=1',out)
        out=self.captured(lambda:self.ns['fresh_entry_quote'](self.engine,'TEST',allow_lookup=True))
        self.assertIn('reason=previous_close_retry_wait',out)

    def test_insufficient_cash_records_research_without_paper_fill(self):
        self.run_engine()
        self.engine.learning.entry.assert_called_once()
        self.engine.store.write_entry.assert_called_once()
        p = self.engine.learning.entry.call_args.args[0]['position']
        self.assertEqual(p['paper_execution'], 'SKIPPED')
        self.assertEqual(p['paper_skip_reason'], 'daily_buy_limit_exceeded')
        self.assertIsNone(p['paper_trade_id'])
        self.ns['push_line_text'].assert_not_called()
        self.assertFalse(self.engine.entry_symbols)

    def test_repeated_accepted_setup_cannot_repeat_paper_skip(self):
        self.run_engine()
        self.ns['call_manager_strategy_result'] = lambda **kw: None
        self.ns['is_exit_event'] = lambda _: False
        for _ in range(20):
            self.run_engine()
        self.manager.before_open.assert_called_once()
        self.engine.learning.entry.assert_called_once()

    def test_strategy_veto_and_user_price_limit_block_research(self):
        self.engine.entry_mode='model'
        self.ns['evaluate_daytrade'].return_value['vetoes']=['跌破VWAP']
        self.run_engine()
        self.assertFalse(self.manager.positions)
        self.ns['evaluate_daytrade'].return_value['vetoes']=[]
        self.engine.entry_mode='rules'
        self.ns['read_live_settings']=lambda:dict(min_price=1,max_price=90,max_gain_pct=5)
        self.run_engine()
        self.assertFalse(self.manager.positions)
        self.manager.before_open.assert_not_called()

    def test_model_mode_never_falls_back_to_rules(self):
        self.engine.entry_mode='model';self.run_engine()
        self.manager.before_open.assert_not_called()

    def test_collect_only_never_attempts_a_fill_even_when_rules_accept(self):
        self.engine.collect_only=True
        self.manager.before_open.return_value=dict(status='bought',shares=1000,trade_id='unexpected')
        self.run_engine()
        self.manager.before_open.assert_not_called()
        self.engine.learning.entry.assert_not_called()
        self.engine.store.write_entry.assert_not_called()
        self.assertFalse(self.engine.entry_symbols)

    def test_stale_risk_blocks_only_new_entries(self):
        self.engine.market_valid_until=NOW.timestamp()-1;self.run_engine()
        self.manager.before_open.assert_not_called()

    def test_accepted_model_can_replace_score_but_not_veto(self):
        self.engine.entry_mode='model'
        self.engine.daytrade_model=Mock(evaluate=Mock(return_value=dict(active=True,evaluated=True,approved=True,accepted=True,probability=.8,threshold=.6,model_version='test')))
        self.ns['evaluate_daytrade'].return_value.update(eligible=False,daytrade_score=10)
        self.run_engine();self.manager.before_open.assert_called_once()
        self.engine.daytrade_model.evaluate.assert_called_once()
        self.manager.before_open.reset_mock()
        self.ns['evaluate_daytrade'].return_value['vetoes']=['市場紅燈']
        self.run_engine();self.manager.before_open.assert_not_called()

    def test_rules_mode_still_requires_rule_eligibility(self):
        self.engine.entry_mode='rules'
        self.ns['evaluate_daytrade'].return_value.update(eligible=False,daytrade_score=61)
        self.run_engine()
        self.manager.before_open.assert_not_called()
        self.engine.daytrade_model = Mock()
        self.run_engine()
        self.engine.daytrade_model.evaluate.assert_not_called()

    def test_low_rule_score_reaches_model_and_logs_rejection(self):
        from contextlib import redirect_stdout
        from io import StringIO
        self.engine.entry_mode='model'
        self.ns['evaluate_daytrade'].return_value.update(eligible=False,daytrade_score=61)
        self.engine.daytrade_model=Mock(evaluate=Mock(return_value=dict(active=True,
            evaluated=True,approved=True,accepted=False,probability=.59,threshold=.6,
            reason='evaluated',model_version='fixture')))
        output=StringIO()
        with redirect_stdout(output):
            self.run_engine()
        self.engine.daytrade_model.evaluate.assert_called_once()
        self.manager.before_open.assert_not_called()
        self.assertIn('[MODEL_DECISION]',output.getvalue())
        self.assertIn('rule_eligible=False',output.getvalue())
        self.assertIn('accepted=False',output.getvalue())
        self.assertNotIn('[ENTRY_DECISION]',output.getvalue())

    def test_unknown_market_blocks_before_model_evaluation(self):
        self.engine.entry_mode='model'
        self.engine.market_level='UNKNOWN'
        self.engine.market_gate={'gate_action':'BLOCK','gate_reason':'market_data_unavailable'}
        self.engine._market_block_counts={'market_risk_red':0,'market_data_unavailable':0}
        self.engine.daytrade_model=Mock()
        self.run_engine()
        self.engine.daytrade_model.evaluate.assert_not_called()
        self.assertEqual(self.engine._market_block_counts['market_data_unavailable'],1)

    def test_real_red_is_counted_separately_from_missing_data(self):
        self.engine.entry_mode='model'
        self.engine.market_level='RED'
        self.engine.market_gate={'gate_action':'BLOCK','gate_reason':'market_risk_red'}
        self.engine._market_block_counts={'market_risk_red':0,'market_data_unavailable':0}
        self.engine.daytrade_model=Mock()
        self.run_engine()
        self.engine.daytrade_model.evaluate.assert_not_called()
        self.assertEqual(self.engine._market_block_counts,
                         {'market_risk_red':1,'market_data_unavailable':0})

    def test_market_pass_reaches_model_evaluation(self):
        self.engine.entry_mode='model'
        self.engine.market_gate={'gate_action':'PASS','gate_reason':'market_risk_pass'}
        self.engine.daytrade_model=Mock(evaluate=Mock(return_value=dict(active=True,evaluated=True,
            approved=True,accepted=False,probability=.4,threshold=.6,model_version='fixture')))
        self.run_engine()
        self.engine.daytrade_model.evaluate.assert_called_once()

    def test_successful_fill_emits_one_entry(self):
        self.manager.before_open.return_value=dict(status='bought',shares=1000,trade_id='test')
        self.run_engine()
        self.engine.learning.entry.assert_called_once()
        self.engine.store.write_entry.assert_called_once()
        self.ns['push_line_text'].assert_called_once()
        position=self.engine.learning.entry.call_args.args[0]['position']
        self.assertEqual(position['decision_mode'],'rules')
        self.assertIsNone(position['model_version'])

    def test_model_fill_records_actual_model_evidence(self):
        self.engine.entry_mode='model'
        self.engine.daytrade_model=Mock(evaluate=Mock(return_value=dict(active=True,evaluated=True,
            approved=True,accepted=True,probability=.8,threshold=.6,model_version='fixture',artifact_sha256='test-hash')))
        self.manager.before_open.return_value=dict(status='bought',shares=1000,trade_id='test')
        self.run_engine()
        position=self.engine.learning.entry.call_args.args[0]['position']
        self.assertEqual(position['decision_mode'],'model')
        self.assertEqual(position['model_artifact_sha256'],'test-hash')
        self.assertEqual(position['model_score'],.8)

class PublicFeedTests(unittest.TestCase):
    def test_wallet_balances_and_sizes_stay_private(self):
        tree=ast.parse((ROOT/'firebase_store.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='public_trade')
        ns={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<public>','exec'),ns)
        private=dict(symbol='TEST',entry_price=100,shares=1000,settlement={'end_balance':123456},trade_id='abc')
        public=ns['public_trade'](private)
        self.assertEqual(public,dict(symbol='TEST',entry_price=100,trade_id='abc'))
        self.assertIn('settlement',private)


class DeploymentTests(unittest.TestCase):
    def test_daily_limit_uses_actual_runtime_configuration(self):
        tree = ast.parse((ROOT/'intraday_live.py').read_text())
        assignment = next(n for n in tree.body if isinstance(n,ast.Assign)
                          and any(isinstance(t,ast.Name) and t.id=='MAX_DAILY_ENTRIES' for t in n.targets))
        code = compile(ast.Module(body=[assignment],type_ignores=[]),'<limit>','exec')
        for configured, expected in [('999',5),('5',5),('3',3),('0',1)]:
            with patch.dict(os.environ,{'LIVE_MAX_DAILY_ENTRIES':configured}):
                ns={'os':os};exec(code,ns)
                self.assertEqual(ns['MAX_DAILY_ENTRIES'],expected)

    def test_tracked_vm_entrypoint_matches_runtime(self):
        """A VM pull must not leave the scheduled root entrypoint on old code."""
        repo = ROOT.parent
        tree = ast.parse((repo/'deploy/install_intraday_runtime.py').read_text())
        files = next(ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FILES'
                                                          for t in n.targets))
        for rel in files:
            with self.subTest(file=rel):
                self.assertEqual((repo/rel).read_bytes(),(ROOT/rel).read_bytes())
        self.assertIn('PositionManager', (repo/'position_manager.py').read_text())

    def test_calendar_failure_keeps_engine_stopped(self):
        tree = ast.parse((ROOT/'intraday_live.py').read_text())
        main = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        engine = Mock()
        ns = {'os':os, 'IntradayLiveEngine':engine, '_ENGINE':None}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<intraday-main>','exec'),ns)
        calendar = types.ModuleType('market_calendar')
        calendar.is_market_open = Mock(side_effect=RuntimeError('calendar unavailable'))
        with patch.dict(sys.modules,{'market_calendar':calendar}), patch.dict(os.environ,{'FORCE_INTRADAY_LIVE':'0'}):
            ns['main']()
        engine.assert_not_called()
        self.assertIsNone(ns['_ENGINE'])

    def test_calendar_failure_keeps_premarket_stopped(self):
        tree = ast.parse((ROOT/'premarket_ai.py').read_text())
        main = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        build_brief = Mock()
        status = Mock()
        ns = {'os':os, 'sys':sys, 'build_brief':build_brief, 'write_premarket_status':status}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<premarket-main>','exec'),ns)
        calendar = types.ModuleType('market_calendar')
        calendar.is_market_open = Mock(side_effect=RuntimeError('calendar unavailable'))
        with patch.dict(sys.modules,{'market_calendar':calendar}), patch.dict(os.environ,{'FORCE_PREMARKET_AI':'0'}):
            with self.assertRaisesRegex(RuntimeError, 'premarket_calendar_error'):
                ns['main']()
        build_brief.assert_not_called()
        status.assert_called_once_with('failed', 'calendar_error')

    def test_premarket_publish_failure_reports_failure_not_success(self):
        tree = ast.parse((ROOT/'premarket_ai.py').read_text())
        main = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        status = Mock()
        ns = {'os':os, 'sys':sys, 'datetime':datetime,'TPE':TPE,'now_tpe':lambda:NOW,
              'build_brief':Mock(return_value={'scan_date':NOW.date().isoformat(),
                                              'generated_at':NOW.isoformat()}),
              'print_brief':Mock(), 'write_firebase':Mock(side_effect=RuntimeError('publish failed')),
              'write_premarket_status':status}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<premarket-main>','exec'),ns)
        calendar = types.ModuleType('market_calendar')
        calendar.is_market_open = Mock(return_value=(True,'open',{}))
        with patch.dict(sys.modules,{'market_calendar':calendar}), patch.object(sys,'argv',['premarket_ai.py']):
            with self.assertRaisesRegex(RuntimeError,'publish failed'):
                ns['main']()
        status.assert_called_once_with('failed','build_or_publish_error')

    def test_root_calendar_import_works_under_scheduled_runtime_path(self):
        script = ("import sys;sys.path.insert(0,"+repr(str(ROOT))+" );"
                  "from market_calendar import now_tpe,is_market_open;"
                  "assert callable(now_tpe) and callable(is_market_open)")
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT.parent,
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_premarket_rejects_wrong_day_before_publishing(self):
        tree=ast.parse((ROOT/'premarket_ai.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        publish=Mock();status=Mock()
        ns={'os':os,'sys':sys,'datetime':datetime,'TPE':TPE,'now_tpe':lambda:NOW,
            'build_brief':Mock(return_value={'scan_date':'2026-09-23','generated_at':NOW.isoformat()}),
            'write_firebase':publish,'write_premarket_status':status}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<premarket-main>','exec'),ns)
        calendar=types.ModuleType('market_calendar')
        calendar.is_market_open=Mock(return_value=(True,'open',{}))
        with patch.dict(sys.modules,{'market_calendar':calendar}),patch.object(sys,'argv',['premarket_ai.py']):
            with self.assertRaisesRegex(RuntimeError,'premarket_brief_date_mismatch'):
                ns['main']()
        publish.assert_not_called()
        status.assert_called_once_with('failed','build_or_publish_error')

    def test_premarket_dry_run_does_not_publish_status(self):
        tree=ast.parse((ROOT/'premarket_ai.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        status=Mock();build=Mock()
        ns={'os':os,'sys':sys,'write_premarket_status':status,'build_brief':build}
        exec(compile(ast.Module(body=[main],type_ignores=[]),'<premarket-main>','exec'),ns)
        calendar=types.ModuleType('market_calendar')
        calendar.is_market_open=Mock(return_value=(False,'holiday',{}))
        with patch.dict(sys.modules,{'market_calendar':calendar}),patch.object(sys,'argv',['premarket_ai.py','--no-firebase','--no-line']):
            ns['main']()
        status.assert_not_called();build.assert_not_called()

    def test_premarket_ai_exception_keeps_deterministic_brief(self):
        tree=ast.parse((ROOT/'premarket_ai.py').read_text())
        build=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_brief')
        ns={'now_tpe':lambda:NOW,'fetch_market_snapshot':lambda:{},
            'fetch_taiwan_futures':lambda:{},'fetch_news':lambda **_:[],
            'base_risk_score':lambda _:(50,[],[]),
            'call_ai':Mock(side_effect=RuntimeError('advisory failed')),
            'GEMINI_MODEL':'test','WEBSITE_URL':'https://example.test',
            'clamp':lambda value,low,high:max(low,min(high,value)),
            'num':lambda value:float(value) if value is not None else None,
            'market_level_from_score':lambda _:'YELLOW',
            'expected_volatility':lambda *_:'normal',
            'default_sector_bias':lambda _:{},
            'build_fallback_summary':lambda **_:'deterministic summary'}
        exec(compile(ast.Module(body=[build],type_ignores=[]),'<premarket-build>','exec'),ns)
        package=types.ModuleType('market_data');package.__path__=[]
        health=types.ModuleType('market_data.health');health.observe=Mock()
        with patch.dict(sys.modules,{'market_data':package,'market_data.health':health}):
            brief=ns['build_brief']()
        self.assertEqual(brief['scan_date'],NOW.date().isoformat())
        self.assertEqual(brief['summary'],'deterministic summary')
        self.assertEqual(brief['ai']['used'],False)
        health.observe.assert_called_once_with('gemini',ok=False,error_code='request_failed')


if __name__=='__main__':unittest.main()
