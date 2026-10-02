#!/usr/bin/env python3
"""Verify an actual SQLite snapshot using temporary simulated fills; source is read-only."""
import argparse
from contextlib import closing
import importlib
from pathlib import Path
import sqlite3
import sys
import tempfile


def verify(database, runtime):
    sys.path.insert(0,str(runtime.resolve()))
    account = importlib.import_module('paper_account')
    source = database.resolve()
    with tempfile.TemporaryDirectory(prefix='easystock-ledger-check-') as folder:
        copy = Path(folder)/'state.sqlite'
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)) as src, closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from migrate_paper_daily_limit import migrate_verified
        with closing(sqlite3.connect(copy)) as con:
            migrate_verified(con)
        original_path = account.db_path
        account.db_path = lambda:copy
        try:
            kind = account.ledger_kind()
            if account.open_positions():
                raise RuntimeError('open positions require reconciliation before deployment')
            with sqlite3.connect(copy) as con:
                if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('SQLite integrity check failed')
                # Only the temporary copy is resumed. The source account is unchanged.
                import paper_ledger
                con.row_factory=sqlite3.Row
                metrics=paper_ledger.daily_metrics(con,paper_ledger.period(con),paper_ledger.now().date().isoformat())
                used=metrics['daily_buy_used']
                equity=metrics['equity']
                con.execute("UPDATE paper_trade_settings SET status='running',daily_buy_limit=? WHERE id=1",(used+100000,))
                before_fills = con.execute('SELECT COUNT(*) FROM paper_trade_fills').fetchone()[0]
            price = 100
            buy = account.buy('TEST','offline fixture',price)
            assert buy['status']=='bought', 'temporary buy failed'
            sell = account.sell('TEST',price*1.01,trade_id=buy['trade_id'])
            assert sell['status']=='sold', 'temporary sell failed'
            retry = account.sell('TEST',price*1.02,trade_id=buy['trade_id'])
            assert retry['already_settled'], 'settlement retry not idempotent'
            assert not account.open_positions(), 'temporary position remained'
            with sqlite3.connect(copy) as con:
                con.row_factory=sqlite3.Row
                after=paper_ledger.daily_metrics(con,paper_ledger.period(con),paper_ledger.now().date().isoformat())
                assert abs(after['equity']-equity-sell['net_pnl']) < .011, 'equity reconciliation failed'
                assert after['daily_buy_used']==used+100000 and after['daily_buy_remaining']==0, 'SELL replenished daily limit'
                assert con.execute('SELECT COUNT(*) FROM paper_trade_fills').fetchone()[0] == before_fills+2
            print('PASS: '+kind+' ledger; daily usage, equity, duplicate settlement; original DB unchanged')
        finally:
            account.db_path = original_path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=Path('/home/ubuntu/easystock-admin/state.sqlite'))
    parser.add_argument('--runtime',type=Path,default=Path(__file__).resolve().parents[1]/'vm_runtime')
    args=parser.parse_args()
    verify(args.database,args.runtime)
