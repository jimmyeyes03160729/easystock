"""Offline regression coverage: no broker, Firebase, LINE or production SQLite."""
import ast
import json
import os
from pathlib import Path
import sqlite3
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
                     intercept=0,threshold=.6,version='fixture'),**overrides)


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
        brief=dict(scan_date='2026-09-24',base_risk_score=64,risk_score=69,market_level='RED')
        self.assertEqual(premarket_context(brief,NOW)[0],'YELLOW')
        brief['scan_date']='2026-09-23'
        self.assertEqual(premarket_context(brief,NOW)[0],'RED')

    def test_live_index_stale_future_missing_and_crash(self):
        for seconds in (-91,1):
            q=dict(ts=(NOW.timestamp()+seconds)*1e9,change_rate=0)
            self.assertFalse(snapshot_risk(q,NOW)['valid'])
        self.assertFalse(snapshot_risk({},NOW)['valid'])
        q=dict(ts=NOW.timestamp()*1e9,change_rate=-2.1)
        self.assertEqual(combine('GREEN',snapshot_risk(q,NOW)['level']),'RED')


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=Path(self.folder.name)/'state.sqlite'
        self.env=patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.db)})
        self.env.start()
        Store(initial=dict(min_price=1,max_price=1000,max_gain_pct=5))
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT OR REPLACE INTO paper_trade_settings VALUES(1,200000,200000,\'running\',\'2026-09-24\',0)')

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
        self.open(m,symbol='OTHER')
        m.close_position('OTHER',101,NOW,'test')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT trades_count FROM paper_trade_logs').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM paper_trade_positions').fetchone()[0],0)

    def test_settlement_failure_keeps_both_positions(self):
        m=self.manager();self.open(m)
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TRIGGER fail_settle BEFORE UPDATE ON paper_trade_settings BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):m.close_position('TEST',101,NOW,'test')
        self.assertTrue(m.has_open_position('TEST'))
        self.assertEqual(len(paper_account.open_positions()),1)
        with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM paper_trade_logs').fetchone()[0],0)

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
        m=self.manager(technical_exit_enabled=False);self.open(m,'OTHER')
        self.assertIsNone(m.on_strategy_result('OTHER',{'vetoes':['跌破VWAP'],'price':99.7},NOW))
        self.assertEqual(m.on_tick('OTHER',99,NOW)['trade']['exit_reason'],'固定停損')


class EngineTests(unittest.TestCase):
    """Execute the real orchestration method with inert external adapters."""
    def setUp(self):
        tree=ast.parse((ROOT/'intraday_live.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='IntradayLiveEngine')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='evaluate_symbol')
        result=dict(eligible=True,daytrade_score=90,vetoes=[],reasons=['one','two'],price=100)
        self.ns=dict(datetime=datetime,MIN_WARM_5M_BARS=1,MIN_WARM_15M_BARS=1,
            evaluate_daytrade=Mock(return_value=result),get_position_safe=lambda m,s:m.get_position(s),
            in_entry_window=lambda _:True,now_tpe=lambda:NOW,MAX_DAILY_ENTRIES=5,
            live_features=Mock(return_value=dict.fromkeys(FEATURES,1)),
            read_live_settings=lambda:dict(min_price=1,max_price=200,max_gain_pct=5),
            register_signal=Mock(),push_line_text=Mock(),format_entry_message=Mock(return_value='entry'))
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<engine>','exec'),self.ns)
        self.manager=PositionManager(before_open=Mock(return_value=dict(status='insufficient_cash',shares=0)))
        self.engine=types.SimpleNamespace(bars=types.SimpleNamespace(rows5=lambda _: [{}],rows15=lambda _:[{}]),
            candidates={'TEST':{}},market_level='GREEN',market_valid_until=NOW.timestamp()+30,
            entry_mode='rules',last_prices={'TEST':100},manager=self.manager,scanner_top_symbols={'TEST'},
            fresh_entry_quote=Mock(return_value=(100,NOW)),_previous_closes={'TEST':(None,100)},
            _lock=threading.RLock(),radar_ticks={'TEST':[]},daytrade_model=DaytradeModel(path=''),
            entry_symbols=set(),_entry_limit_logged=False,learning=Mock(),store=Mock())

    def run_engine(self):self.ns['evaluate_symbol'](self.engine,'TEST',NOW)

    def test_insufficient_cash_does_not_record_or_publish_entry(self):
        self.run_engine()
        self.engine.learning.entry.assert_not_called()
        self.engine.store.write_entry.assert_not_called()
        self.ns['push_line_text'].assert_not_called()
        self.assertFalse(self.engine.entry_symbols)

    def test_model_mode_never_falls_back_to_rules(self):
        self.engine.entry_mode='model';self.run_engine()
        self.manager.before_open.assert_not_called()

    def test_stale_risk_blocks_only_new_entries(self):
        self.engine.market_valid_until=NOW.timestamp()-1;self.run_engine()
        self.manager.before_open.assert_not_called()

    def test_accepted_model_can_replace_score_but_not_veto(self):
        self.engine.entry_mode='model'
        self.engine.daytrade_model=Mock(evaluate=Mock(return_value=dict(active=True,evaluated=True,approved=True,accepted=True,probability=.8,threshold=.6,model_version='test')))
        self.ns['evaluate_daytrade'].return_value.update(eligible=False,daytrade_score=10)
        self.run_engine();self.manager.before_open.assert_called_once()
        self.manager.before_open.reset_mock()
        self.ns['evaluate_daytrade'].return_value['vetoes']=['市場紅燈']
        self.run_engine();self.manager.before_open.assert_not_called()

    def test_successful_fill_emits_one_entry(self):
        self.manager.before_open.return_value=dict(status='bought',shares=1000,trade_id='test')
        self.run_engine()
        self.engine.learning.entry.assert_called_once()
        self.engine.store.write_entry.assert_called_once()
        self.ns['push_line_text'].assert_called_once()

if __name__=='__main__':unittest.main()
