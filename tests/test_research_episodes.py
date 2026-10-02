"""Synthetic point-in-time 3189 scenarios; never evidence of actual October 1 exits."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from daytrade_learning.episodes import ResearchStore, read_trades, mirror_entry, mirror_exit
from easystock_admin.store import Store
from learning_status import trade_summary, _research_rows, compute
from position_manager import PositionManager
import paper_ledger
import paper_account

TPE = timezone(timedelta(hours=8))
ENTRY = datetime(2026, 10, 1, 10, 33, 43, tzinfo=TPE)
SECOND = ENTRY.replace(hour=12, minute=7, second=1)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    wallet = tmp_path / 'wallet.sqlite'
    monkeypatch.setenv('EASYSTOCK_ADMIN_DB', str(wallet))
    Store(initial={'min_price': 1, 'max_price': 2000, 'max_gain_pct': 5})
    with sqlite3.connect(wallet) as db:
        paper_ledger.init_schema(db)
        db.execute("INSERT INTO meta VALUES('paper_trade_period_current','fixture')")
        db.execute("INSERT INTO paper_trade_periods(id,created_at,starting_cash,archive_path) VALUES('fixture','2026-10-01',1000000,'fixture')")
        db.execute("INSERT INTO paper_trade_settings(id,initial_capital,current_capital,status,start_date,updated_at) VALUES(1,1000000,1000000,'running','2026-10-01',0)")
        paper_ledger.migrate(db)
    research = ResearchStore(tmp_path / 'research.sqlite')
    buy = Mock(side_effect=lambda **kw: paper_ledger.buy(**kw, path=wallet, timestamp=ENTRY))
    sell = Mock(side_effect=lambda symbol, exit_price, exit_reason, trade_id:
                paper_ledger.sell(symbol, exit_price, exit_reason, trade_id=trade_id,
                                  path=wallet, timestamp=ENTRY))
    manager = PositionManager(research_mode=True, research_store=research,
                              before_open=buy, before_close=sell)
    return SimpleNamespace(manager=manager, store=research, buy=buy, sell=sell,
                           wallet=wallet, folder=tmp_path)


def enter(setup, symbol='3189', price=1015, at=ENTRY):
    return setup.manager.open_position(symbol, '景碩' if symbol == '3189' else symbol,
        price, at, 61, ['fixture'], decision_evidence={'decision_mode':'model',
        'model_version':'synthetic', 'model_artifact_sha256':'fixture',
        'model_score':.7, 'model_threshold':.6,
        'entry_gate_evidence':{'market_gate':'PASS', 'radar_selected':True}})


def query(setup, sql):
    with sqlite3.connect(setup.wallet) as db:
        return db.execute(sql).fetchall()


def test_insufficient_cash_keeps_research_and_cash_unchanged(setup):
    event = enter(setup)
    p = event['position']
    assert p['research_execution'] == 'TRACKED'
    assert p['paper_execution'] == 'SKIPPED'
    assert p['paper_skip_reason'] == 'daily_buy_limit_exceeded'
    assert p['research_trade_id'] and p['episode_id']
    assert p['paper_trade_id'] is None and p['trade_id'] is None
    assert query(setup, 'SELECT current_capital FROM paper_trade_settings') == [(1000000,)]
    assert query(setup, 'SELECT COUNT(*) FROM paper_trade_fills') == [(0,)]
    assert len(setup.store.trades()) == 1


def test_twenty_accepted_ticks_and_second_window_are_one_open_episode(setup):
    identity = enter(setup)['position']['episode_id']
    for index in range(20):
        at = ENTRY + timedelta(seconds=4*(index+1))
        assert enter(setup, price=1020, at=at) is None
        assert setup.manager.on_tick('3189', 1020 if index%2 else 1015, at) is None
    assert enter(setup, at=SECOND) is None
    assert setup.manager.get_position('3189')['episode_id'] == identity
    setup.buy.assert_called_once()
    assert query(setup, "SELECT COUNT(*) FROM paper_trade_events WHERE action='略過'") == [(1,)]
    assert setup.manager.get_position('3189')['highest_price'] == 1020
    assert setup.manager.get_position('3189')['lowest_price'] == 1015


@pytest.mark.parametrize('exit_kind', ['stop','profit','trailing','technical','force','breakeven'])
def test_research_only_all_exit_rules_never_settle_wallet(setup, exit_kind):
    enter(setup)
    at = ENTRY + timedelta(minutes=1)
    if exit_kind == 'stop':
        event = setup.manager.on_tick('3189', 1000, at)
    elif exit_kind == 'profit':
        event = setup.manager.on_tick('3189', 1030, at)
    elif exit_kind == 'trailing':
        setup.manager.exit_mode = 'trailing'
        setup.manager.on_tick('3189', 1030, at)
        event = setup.manager.on_tick('3189', 1024, at+timedelta(seconds=1))
    elif exit_kind == 'technical':
        event = setup.manager.on_strategy_result('3189', {'price':1010,'vetoes':['跌破VWAP']}, at)
    elif exit_kind == 'force':
        event = setup.manager.on_tick('3189', 1020, at.replace(hour=12,minute=55))
    else:
        setup.manager.on_tick('3189', 1022, at)
        event = setup.manager.on_tick('3189', 1018, at+timedelta(seconds=1))
    assert event['trade']['status'] == 'CLOSED'
    for key in ('pnl_pct','mfe_pct','mae_pct','exit_reason','exit_time','research_net_pnl_pct'):
        assert event['trade'][key] is not None
    setup.sell.assert_not_called()
    assert query(setup, 'SELECT current_capital FROM paper_trade_settings') == [(1000000,)]
    assert query(setup, 'SELECT COUNT(*) FROM paper_trade_fills') == [(0,)]


def test_closed_episode_requires_false_then_true_before_second_entry(setup):
    first = enter(setup)['position']
    close_at = ENTRY + timedelta(minutes=2)
    setup.manager.on_tick('3189', 1000, close_at)
    assert enter(setup, at=SECOND) is None
    setup.manager.observe_entry_predicate('3189', True, SECOND)
    assert enter(setup, at=SECOND+timedelta(seconds=1)) is None
    setup.manager.observe_entry_predicate('3189', False, ENTRY)  # delayed pre-close observation
    assert enter(setup, at=SECOND+timedelta(seconds=2)) is None
    setup.manager.observe_entry_predicate('3189', False, SECOND+timedelta(seconds=3))
    second = enter(setup, at=SECOND+timedelta(seconds=4))['position']
    assert first['research_trade_id'] != second['research_trade_id']
    assert first['episode_id'] != second['episode_id']
    assert setup.buy.call_count == 2
    assert query(setup, "SELECT COUNT(*) FROM paper_trade_events WHERE action='略過'") == [(2,)]


def test_filled_trade_one_episode_one_settlement_and_separate_ids(setup):
    p = enter(setup, symbol='2303', price=100)['position']
    assert p['paper_execution'] == 'FILLED'
    assert p['paper_trade_id'] != p['research_trade_id']
    assert p['trade_id'] == p['paper_trade_id']
    assert len(setup.store.trades()) == 1
    assert query(setup, "SELECT SUM(gross) FROM paper_trade_fills WHERE side='BUY'") == [(1000000,)]
    event = setup.manager.on_tick('2303', 102, ENTRY+timedelta(minutes=1))
    assert event['trade']['settlement']['status'] == 'sold'
    assert setup.manager.close_position('2303', 102, ENTRY, 'duplicate') is None
    setup.sell.assert_called_once()
    assert query(setup, 'SELECT COUNT(*) FROM paper_trade_fills') == [(2,)]
    setup.manager.observe_entry_predicate('2303', False, SECOND)
    second = enter(setup, symbol='2303', price=100, at=SECOND+timedelta(seconds=1))['position']
    assert second['paper_execution'] == 'SKIPPED'
    assert second['paper_skip_reason'] == 'reentry_disabled'
    setup.buy.assert_called_once()


def test_paper_daily_limit_does_not_remove_research(setup):
    setup.manager.paper_traded_symbols.update({'1','2','3','4','5'})
    p = enter(setup)['position']
    assert p['paper_execution'] == 'SKIPPED'
    assert p['paper_skip_reason'] == 'daily_entry_limit'
    setup.buy.assert_not_called()


@pytest.mark.parametrize('increase_limit',[False,True])
def test_second_research_episode_checks_cumulative_buy_limit(setup,increase_limit):
    setup.manager.allow_reentry=True
    first=enter(setup,symbol='2303',price=100)['position']
    setup.manager.on_tick('2303',102,ENTRY+timedelta(minutes=1))
    if increase_limit:
        with sqlite3.connect(setup.wallet) as db:
            db.execute('UPDATE paper_trade_settings SET daily_buy_limit=2000000')
    setup.manager.observe_entry_predicate('2303',False,SECOND)
    second=enter(setup,symbol='2303',price=100,at=SECOND+timedelta(seconds=1))['position']
    assert first['episode_id'] != second['episode_id']
    assert second['paper_execution']==('FILLED' if increase_limit else 'SKIPPED')
    if not increase_limit:
        assert second['paper_skip_reason']=='daily_buy_limit_exceeded'
    assert query(setup,"SELECT SUM(gross) FROM paper_trade_fills WHERE side='BUY'")==[(2000000 if increase_limit else 1000000,)]
    assert setup.buy.call_count == 2


def test_restart_keeps_research_only_extrema_and_does_not_retry_buy(setup):
    enter(setup)
    setup.manager.on_tick('3189', 1020, ENTRY+timedelta(seconds=10))
    restored = PositionManager(research_mode=True, research_store=setup.store,
                               before_open=setup.buy, before_close=setup.sell)
    restored.restore_research('2026-10-01')
    assert restored.get_position('3189')['highest_price'] == 1020
    assert restored.open_position('3189','景碩',1015,SECOND,61,[]) is None
    restored.on_tick('3189',1000,SECOND)
    assert len(setup.store.trades()) == 1
    assert setup.store.trades()[0]['status'] == 'CLOSED'
    setup.buy.assert_called_once()
    setup.sell.assert_not_called()


def test_rearm_state_survives_restart(setup):
    enter(setup)
    setup.manager.on_tick('3189',1000,ENTRY+timedelta(seconds=10))
    restored = PositionManager(research_mode=True, research_store=setup.store,
                               before_open=setup.buy, before_close=setup.sell)
    restored.restore_research('2026-10-01')
    assert restored.open_position('3189','景碩',1015,SECOND,61,[]) is None
    restored.observe_entry_predicate('3189',False,SECOND)
    again = PositionManager(research_mode=True, research_store=setup.store,
                            before_open=setup.buy, before_close=setup.sell)
    again.restore_research('2026-10-01')
    assert again.open_position('3189','景碩',1015,SECOND+timedelta(seconds=1),61,[]) is not None


def test_research_close_persists_when_paper_settlement_temporarily_fails(setup):
    enter(setup, symbol='2303', price=100)
    with sqlite3.connect(setup.wallet) as db:
        db.execute("CREATE TRIGGER fail_sell BEFORE INSERT ON paper_trade_fills WHEN NEW.side='SELL' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    event = setup.manager.on_tick('2303',102,ENTRY+timedelta(minutes=1))
    assert event['trade']['status'] == 'CLOSED'
    assert event['trade']['paper_settlement_pending']
    assert setup.store.trades()[0]['status'] == 'CLOSED'
    assert query(setup,'SELECT COUNT(*) FROM paper_trade_fills') == [(1,)]
    with sqlite3.connect(setup.wallet) as db:
        db.execute('DROP TRIGGER fail_sell')
    restored = PositionManager(research_mode=True,research_store=setup.store,
        before_open=setup.buy,before_close=setup.sell)
    restored.restore_research('2026-10-01')
    restored.retry_paper_settlements()
    restored.retry_paper_settlements()
    assert query(setup,'SELECT COUNT(*) FROM paper_trade_fills') == [(2,)]
    assert len(restored.closed_trades) == 1
    assert setup.store.trades()[0]['paper_settlement_pending'] is False


def test_summary_contains_research_only_and_filled_without_wallet_fields(setup):
    enter(setup)
    enter(setup, symbol='2303', price=100)
    setup.manager.on_tick('3189',1000,ENTRY+timedelta(minutes=1))
    setup.manager.on_tick('2303',102,ENTRY+timedelta(minutes=1))
    summary = trade_summary({},'2026-10-01',_research_rows(setup.folder,'2026-10-01'))
    assert summary['source'] == 'research_store'
    assert summary['research_trades'] == summary['research_closed'] == 2
    assert summary['paper_filled'] == 1
    assert summary['paper_skipped'] == summary['paper_skipped_daily_buy_limit'] == 1
    assert summary['paper_skipped_insufficient_cash'] == 0
    assert (summary['wins'],summary['losses']) == (1,1)
    assert summary['net_pnl_pct'] is not None
    assert summary['avg_mfe_pct'] is not None and summary['avg_mae_pct'] is not None
    assert sum(summary['exit_reasons'].values()) == 2
    assert not {'shares','current_capital','start_balance','end_balance','settlement'} & summary.keys()


def test_read_only_source_does_not_create_missing_database(tmp_path):
    path = tmp_path/'research.sqlite'
    assert read_trades(path,'2026-10-01') == []
    assert not path.exists()


def test_core_root_vm_files_do_not_drift():
    root = Path(__file__).resolve().parents[1]
    for name in ('position_manager.py','intraday_live.py','paper_account.py','paper_ledger.py',
                 'firebase_store.py','learning_status.py','daytrade_learning/runtime.py',
                 'daytrade_learning/episodes.py','daytrade_learning/research.py'):
        assert (root/name).read_bytes() == (root/'vm_runtime'/name).read_bytes(), name


def test_late_exit_does_not_erase_next_episode_or_reopen_old_entry():
    first = {'symbol':'3189','research_trade_id':'first','entry_time':ENTRY.isoformat()}
    second = {'symbol':'3189','research_trade_id':'second','entry_time':SECOND.isoformat()}
    state = mirror_entry({'scan_date':'2026-10-01'}, second)
    state = mirror_exit(state, {**first,'status':'CLOSED'}, 'first')
    assert state['open_positions']['3189']['research_trade_id'] == 'second'
    assert state['closed_trades']['first']['status'] == 'CLOSED'
    assert mirror_entry(state, first) == state


def test_late_entry_cannot_restore_stale_price_or_previous_day():
    entry = {'symbol':'3189','research_trade_id':'first','entry_time':ENTRY.isoformat(),
             'last_update_at':(ENTRY+timedelta(seconds=10)).isoformat(),'highest_price':1020}
    state = mirror_entry({'scan_date':'2026-10-01'}, entry)
    assert mirror_entry(state,{**entry,'last_update_at':ENTRY.isoformat(),'highest_price':1015}) == state
    assert mirror_entry(state,{**entry,'entry_time':'2026-09-30T10:33:43+08:00'}) == state


def test_research_report_uses_store_even_if_journal_exit_is_missing(setup):
    from daytrade_learning.research import build
    enter(setup)
    setup.manager.on_tick('3189',1000,ENTRY+timedelta(minutes=1))
    assert not (setup.folder/'journal-2026-10-01.jsonl').exists()
    result = build(setup.folder,'2026-10-01',{},persist_report=False)
    tracking = result['existing_signal_tracking']
    assert tracking['source'] == 'research_store'
    assert tracking['accepted_count'] == tracking['closed_count'] == 1
    assert tracking['paper_filled'] == 0
    assert tracking['paper_skipped_daily_buy_limit'] == 1


def test_summary_selects_durable_research_date_without_journal(setup):
    enter(setup)
    result = compute(setup.folder,ENTRY+timedelta(days=1),{},'',[])
    assert result['research_summary']['date'] == '2026-10-01'
    assert result['research_summary']['trades']['research_trades'] == 1
    assert result['research_summary']['trades']['research_open'] == 1


def test_execution_exception_never_discards_research_or_retries_episode(setup):
    setup.buy.side_effect = RuntimeError('fixture adapter failure')
    p = enter(setup)['position']
    assert p['paper_execution'] == 'SKIPPED'
    assert p['paper_skip_reason'] == 'execution_unconfirmed'
    assert enter(setup, at=SECOND) is None
    setup.buy.assert_called_once()
    assert len(setup.store.trades()) == 1


def test_research_wins_and_average_include_hypothetical_costs(setup):
    enter(setup)
    setup.manager.close_position('3189',1016,ENTRY+timedelta(minutes=1),'fixture exit')
    summary = trade_summary({},'2026-10-01',setup.store.trades())
    assert summary['gross_pnl_pct'] > 0
    assert summary['net_pnl_pct'] < 0
    assert summary['wins'] == 0 and summary['losses'] == 1
    assert summary['avg_pnl_pct'] == summary['net_pnl_pct']


def test_verified_existing_paper_close_survives_research_upgrade_without_cash_writes(setup):
    enter(setup,symbol='2303',price=100)
    closed = setup.manager.on_tick('2303',102,ENTRY+timedelta(minutes=1))['trade']
    legacy = {key:value for key,value in closed.items() if key not in ('research_trade_id','episode_id')}
    imported = ResearchStore(setup.folder/'imported.sqlite')
    manager = PositionManager(research_mode=True,research_store=imported)
    before = setup.wallet.read_bytes()
    manager.migrate_closed_paper([legacy], '2026-10-01', paper_account.settlement_receipt)
    manager.migrate_closed_paper([legacy], '2026-10-01', paper_account.settlement_receipt)
    assert setup.wallet.read_bytes() == before
    assert len(imported.trades()) == 1
    assert imported.trades()[0]['research_trade_id'] == 'legacy-paper-'+closed['paper_trade_id']
    assert imported.trades()[0]['paper_execution'] == 'FILLED'
    assert imported.trades()[0]['research_net_pnl_pct'] is not None


def test_unverified_mirror_or_insufficient_cash_cannot_create_legacy_research(setup):
    legacy = dict(symbol='3189',trade_id='no-fill',execution_kind='paper_fill',
                  entry_time=ENTRY.isoformat(),exit_time=SECOND.isoformat(),status='CLOSED')
    setup.manager.migrate_closed_paper([legacy],'2026-10-01',lambda _: None)
    assert setup.store.trades() == []
