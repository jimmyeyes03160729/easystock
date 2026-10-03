"""Daily notional limits, old-schema preservation, retries and concurrency."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import os
import sqlite3

import pytest
import paper_ledger as ledger
from easystock_admin.store import Store, read_paper_trade_settings
from daytrade_summary_push import build_daily_summary

AT=datetime(2026,10,1,10,0,tzinfo=timezone(timedelta(hours=8)))
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('limit_migration',ROOT/'deploy/migrate_paper_daily_limit.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)


@pytest.fixture
def account(tmp_path,monkeypatch):
    path=tmp_path/'wallet.sqlite'
    monkeypatch.setenv('EASYSTOCK_ADMIN_DB',str(path))
    monkeypatch.setattr(ledger,'now',lambda:AT)
    store=Store(path,{'min_price':1,'max_price':2000,'max_gain_pct':5})
    store.start_paper_trade(1000000)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE paper_trade_settings SET start_date='2026-10-01'")
    return store,path


def metrics(path,day='2026-10-01'):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory=sqlite3.Row
        return ledger.daily_metrics(db,ledger.period(db),day)


def old_database(path):
    """Actual old six/eight/ten-column shape, with immutable history evidence."""
    with sqlite3.connect(path) as db:
        db.executescript('''
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE paper_trade_settings(id INTEGER PRIMARY KEY,initial_capital REAL NOT NULL,current_capital REAL NOT NULL,status TEXT NOT NULL,start_date TEXT NOT NULL,updated_at REAL NOT NULL);
        CREATE TABLE paper_trade_positions(symbol TEXT PRIMARY KEY,name TEXT NOT NULL,entry_price REAL NOT NULL,shares INTEGER NOT NULL,entry_time TEXT NOT NULL,period_id TEXT,entry_date TEXT,buy_fee REAL NOT NULL DEFAULT 0);
        CREATE TABLE paper_trade_logs(date TEXT PRIMARY KEY,start_balance REAL NOT NULL,end_balance REAL NOT NULL,net_pnl REAL NOT NULL,symbols TEXT NOT NULL,costs REAL NOT NULL,trades_count INTEGER NOT NULL,created_at REAL NOT NULL,period_id TEXT,settlement_status TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE paper_trade_events(id INTEGER PRIMARY KEY,date TEXT NOT NULL,time_str TEXT NOT NULL,symbol TEXT NOT NULL,name TEXT NOT NULL,price REAL NOT NULL,action TEXT NOT NULL,reason TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE paper_trade_periods(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,starting_cash REAL NOT NULL,archive_path TEXT NOT NULL);
        CREATE TABLE paper_trade_fills(id INTEGER PRIMARY KEY,period_id TEXT NOT NULL,transaction_id TEXT NOT NULL UNIQUE,trade_date TEXT NOT NULL,event_time TEXT NOT NULL,side TEXT NOT NULL,symbol TEXT NOT NULL,name TEXT NOT NULL,price REAL NOT NULL,shares INTEGER NOT NULL,gross REAL NOT NULL,fee REAL NOT NULL,tax REAL NOT NULL,realized_pnl REAL NOT NULL,cash_after REAL NOT NULL,reason TEXT NOT NULL DEFAULT '');
        INSERT INTO meta VALUES('paper_trade_period_current','old');
        INSERT INTO paper_trade_periods VALUES('old','2026-09-30',200000,'private-old-backup');
        INSERT INTO paper_trade_settings VALUES(1,200000,199652,'running','2026-09-30',0);
        INSERT INTO paper_trade_logs VALUES('2026-09-30',200000,199652,-348,'2330',348,1,0,'old','settled');
        INSERT INTO paper_trade_fills VALUES(1,'old','old-buy','2026-09-30','2026-09-30T10:00:00+08:00','BUY','2330','fixture',100,1000,100000,40,0,0,99960,'old buy');
        INSERT INTO paper_trade_fills VALUES(2,'old','old-sell','2026-09-30','2026-09-30T11:00:00+08:00','SELL','2330','fixture',100,1000,100000,40,150,-348,199652,'old sell');
        ''')


def test_old_migration_preserves_every_original_field_and_repeated_configuration(tmp_path):
    path=tmp_path/'old.sqlite';old_database(path)
    with closing(sqlite3.connect(path)) as db:
        report=migration.migrate_verified(db)
        assert report['before_counts']==report['after_counts']
        row=db.execute('SELECT daily_buy_limit,performance_base,current_capital,legacy_pnl_adjustment FROM paper_trade_settings').fetchone()
        assert tuple(row)==(200000,200000,199652,0)
        assert metrics(path)['cumulative_net_pnl']==-348
        # Legacy balances remain migration evidence only; product metrics expose
        # cumulative net PnL, never a Paper equity account.
        assert 'equity' not in metrics(path)
        assert 'performance_base' not in metrics(path)
        db.execute('UPDATE paper_trade_settings SET daily_buy_limit=2000000');db.commit()
        again=migration.migrate_verified(db)
        assert again['existing_rows_unchanged']
        assert db.execute('SELECT daily_buy_limit FROM paper_trade_settings').fetchone()[0]==2000000


def test_probe_is_read_only_and_apply_creates_backup(tmp_path):
    path=tmp_path/'old.sqlite';old_database(path)
    before=path.read_bytes()
    assert migration.run(path)['source_read_only']
    assert path.read_bytes()==before
    report=migration.run(path,True,tmp_path/'backups')
    assert report['applied'] and report['existing_rows_unchanged']
    backup=Path(report['backup'])
    assert backup.is_file()
    if os.name != 'nt':
        assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as db:
        assert 'daily_buy_limit' not in [r[1] for r in db.execute('PRAGMA table_info(paper_trade_settings)')]


def test_incomplete_today_legacy_usage_cannot_be_reset_by_migration(tmp_path,monkeypatch):
    path=tmp_path/'old.sqlite';old_database(path)
    monkeypatch.setattr(ledger,'now',lambda:AT)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO paper_trade_events VALUES(1,'2026-10-01','10:00:00','2303','fixture',100,'買進','legacy event',0)")
    with closing(sqlite3.connect(path)) as db:
        with pytest.raises(RuntimeError,match='daily usage requires reconciliation'):
            migration.migrate_verified(db)
        assert 'daily_buy_limit' not in [r[1] for r in db.execute('PRAGMA table_info(paper_trade_settings)')]


def test_buy_exact_limit_includes_fee_without_consuming_extra_limit(account):
    store,path=account;store.start_paper_trade(100000)
    result=ledger.buy('2303','fixture',100,path=path,timestamp=AT)
    assert result['shares']==1000 and result['buy_fee']==40
    assert metrics(path)['daily_buy_used']==100000
    assert metrics(path)['daily_buy_remaining']==0
    assert metrics(path)['net_pnl']==-40


def test_sell_never_restores_limit_or_counts_fees_and_tax_as_usage(account):
    store,path=account;store.start_paper_trade(100000)
    fill=ledger.buy('2303','fixture',100,path=path,timestamp=AT)
    sell=ledger.sell('2303',101,path=path,timestamp=AT,trade_id=fill['trade_id'])
    result=metrics(path)
    assert result['daily_buy_used']==100000 and result['daily_buy_remaining']==0
    assert result['fees']==80 and result['tax']==152
    assert result['realized_pnl']==1000 and result['net_pnl']==768
    assert sell['daily_buy_remaining']==0
    assert ledger.buy('2317','fixture',10,path=path,timestamp=AT)['skip_reason']=='daily_buy_limit_exceeded'


def test_same_day_more_buys_accumulate_and_owner_change_preserves_usage(account):
    store,path=account;store.start_paper_trade(100000)
    fill=ledger.buy('2303','fixture',100,path=path,timestamp=AT)
    ledger.sell('2303',101,path=path,timestamp=AT,trade_id=fill['trade_id'])
    store.start_paper_trade(500000)
    ledger.buy('2317','fixture',100,path=path,timestamp=AT)
    store.start_paper_trade(1000000)
    result=metrics(path)
    assert result['daily_buy_used']==500000 and result['daily_buy_remaining']==500000
    store.start_paper_trade(2000000)
    assert metrics(path)['daily_buy_remaining']==1500000
    store.start_paper_trade(200000)
    assert metrics(path)['daily_buy_used']==500000 and metrics(path)['daily_buy_remaining']==0
    assert len(ledger.snapshot(path)['positions'])==1
    assert ledger.buy('2408','fixture',1,path=path,timestamp=AT)['skip_reason']=='daily_buy_limit_exceeded'


@pytest.mark.parametrize('exit_price',[90,110])
def test_next_taipei_day_resets_usage_not_limit_or_cumulative_pnl(account,exit_price):
    store,path=account;store.start_paper_trade(100000)
    fill=ledger.buy('2303','fixture',100,path=path,timestamp=AT)
    ledger.sell('2303',exit_price,path=path,timestamp=AT,trade_id=fill['trade_id'])
    cumulative=metrics(path)['cumulative_net_pnl']
    following=metrics(path,'2026-10-02')
    assert following['daily_buy_used']==0 and following['daily_buy_remaining']==100000
    assert following['daily_buy_limit']==100000 and following['cumulative_net_pnl']==cumulative
    ledger.buy('2317','fixture',100,path=path,timestamp='2026-10-01T16:01:00+00:00')
    assert metrics(path,'2026-10-02')['daily_buy_used']==100000


@pytest.mark.parametrize('remaining,price,shares',[(350000,100,3000),(250000,120,2000),(150000,100,1000)])
def test_maximum_whole_lots_without_eighty_percent_cap(account,remaining,price,shares):
    store,path=account;store.start_paper_trade(remaining)
    fill=ledger.buy('2303','fixture',price,path=path,timestamp=AT)
    assert fill['shares']==shares
    assert metrics(path)['daily_buy_remaining']==remaining-price*shares


def test_concurrent_buys_and_duplicate_execution_id_cannot_double_count(account):
    _,path=account
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda s:ledger.buy(s,s,100,path=path,timestamp=AT),['2303','2317']))
    assert sum(r['status']=='bought' for r in results)==1
    assert metrics(path)['daily_buy_used']==1000000


def test_two_concurrent_retries_return_one_buy_receipt(account):
    _,path=account
    with ThreadPoolExecutor(2) as pool:
        fills=list(pool.map(lambda _:ledger.buy('2303','fixture',100,path=path,timestamp=AT,execution_id='same-episode'),range(2)))
    assert fills[0]['trade_id']==fills[1]['trade_id']
    assert metrics(path)['daily_buy_used']==1000000
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM paper_trade_fills WHERE side='BUY'").fetchone()[0]==1


def test_retry_same_buy_after_sell_is_same_fill_and_restart_keeps_usage(account):
    store,path=account;store.start_paper_trade(100000)
    first=ledger.buy('2303','fixture',100,path=path,timestamp=AT,execution_id='episode-one')
    ledger.sell('2303',101,path=path,timestamp=AT,trade_id=first['trade_id'])
    retry=ledger.buy('2303','fixture',100,path=path,timestamp=AT,execution_id='episode-one')
    assert retry['trade_id']==first['trade_id'] and retry['already_bought']
    Store(path)
    assert read_paper_trade_settings()['daily_buy_used']==100000
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM paper_trade_fills').fetchone()[0]==2


def test_same_symbol_second_fill_has_distinct_settlement_identity(account):
    store,path=account;store.start_paper_trade(100000)
    first=ledger.buy('2303','fixture',100,path=path,timestamp=AT,execution_id='first')
    ledger.sell('2303',101,path=path,timestamp=AT,trade_id=first['trade_id'])
    store.start_paper_trade(200000)
    second=ledger.buy('2303','fixture',100,path=path,timestamp=AT,execution_id='second')
    ledger.sell('2303',101,path=path,timestamp=AT,trade_id=second['trade_id'])
    assert first['trade_id'] != second['trade_id']
    assert metrics(path)['daily_buy_used']==200000
    assert metrics(path)['trades_count']==2
    assert metrics(path)['net_pnl']==1536


def test_summary_has_usage_fees_tax_net_return_and_zero_denominator(account):
    store,path=account
    assert '交易資金報酬率（淨損益／買進使用額度）：--' in build_daily_summary(path,'2026-10-01')
    store.start_paper_trade(100000)
    fill=ledger.buy('2303','fixture',100,path=path,timestamp=AT)
    assert build_daily_summary(path,'2026-10-01') is None
    ledger.sell('2303',101,path=path,timestamp=AT,trade_id=fill['trade_id'])
    text=build_daily_summary(path,'2026-10-01')
    for content in ('每日買進額度：100,000.00','今日買進使用額度：100,000.00','今日手續費：80.00',
                    '今日證交稅：152.00','今日淨損益：+768.00','累積淨損益：+768.00','0.77%','今日額度使用率：100.0%'):
        assert content in text
    assert '目前模擬帳戶資金' not in text
    assert '模擬累積權益' not in text


def test_public_paper_snapshot_excludes_legacy_equity_fields(account):
    _, path = account
    snapshot = ledger.snapshot(path)
    assert 'equity' not in snapshot['settings']
    assert 'performance_base' not in snapshot['settings']
    assert all('equity_start' not in row and 'equity_end' not in row for row in snapshot['logs'])


def test_core_and_admin_root_vm_sources_match():
    for name in ('paper_ledger.py','paper_account.py','position_manager.py','daytrade_summary_push.py',
                 'easystock_admin/store.py','easystock_admin/web.py','easystock_admin/health.py',
                 'easystock_admin/static/paper-trade.js','easystock_admin/static/index.html'):
        assert (ROOT/name).read_bytes()==(ROOT/'vm_runtime'/name).read_bytes(),name
