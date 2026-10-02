#!/usr/bin/env python3
"""Offline deployment probe. All research and cash writes use disposable fixtures."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daytrade_learning.episodes import ResearchStore
from easystock_admin.store import Store
from learning_status import trade_summary
from position_manager import PositionManager
import paper_ledger


def main():
    with tempfile.TemporaryDirectory(prefix='easystock-research-probe-') as directory:
        wallet = Path(directory)/'wallet.sqlite'
        research = ResearchStore(Path(directory)/'research.sqlite')
        at = datetime(2026,10,1,10,33,43,tzinfo=timezone(timedelta(hours=8)))
        with patch.dict(os.environ, {'EASYSTOCK_ADMIN_DB':str(wallet)}):
            Store(initial={'min_price':1,'max_price':2000,'max_gain_pct':5})
            with sqlite3.connect(wallet) as db:
                paper_ledger.init_schema(db)
                db.execute("INSERT INTO meta VALUES('paper_trade_period_current','probe')")
                db.execute("INSERT INTO paper_trade_periods(id,created_at,starting_cash,archive_path) VALUES('probe','2026-10-01',1000000,'probe')")
                db.execute("INSERT INTO paper_trade_settings(id,initial_capital,current_capital,status,start_date,updated_at) VALUES(1,1000000,1000000,'running','2026-10-01',0)")
                paper_ledger.migrate(db)
            def sell(symbol,exit_price,exit_reason,trade_id):
                return paper_ledger.sell(symbol,exit_price,exit_reason,trade_id=trade_id,
                                         path=wallet,timestamp=at)
            manager = PositionManager(research_mode=True,research_store=research,
                before_open=lambda **kw: paper_ledger.buy(**kw,path=wallet,timestamp=at),
                before_close=sell)
            first = manager.open_position('3189','景碩',1015,at,61,['synthetic probe'])
            assert first['position']['paper_skip_reason'] == 'daily_buy_limit_exceeded'
            for index in range(20):
                assert manager.open_position('3189','景碩',1020,at+timedelta(seconds=index),61,[]) is None
            manager.on_tick('3189',1000,at+timedelta(minutes=1))
            assert manager.open_position('3189','景碩',1015,at+timedelta(minutes=2),61,[]) is None
            with sqlite3.connect(wallet) as db:
                assert db.execute("SELECT COALESCE(SUM(gross),0) FROM paper_trade_fills WHERE side='BUY'").fetchone()[0] == 0
                assert db.execute("SELECT COUNT(*) FROM paper_trade_events WHERE action='略過'").fetchone()[0] == 1
                assert db.execute('SELECT COUNT(*) FROM paper_trade_fills').fetchone()[0] == 0
            manager.open_position('2303','fixture',100,at+timedelta(minutes=3),90,[])
            manager.on_tick('2303',102,at+timedelta(minutes=4))
            summary = trade_summary({},'2026-10-01',research.trades('2026-10-01'))
            assert summary['research_closed'] == 2
            assert summary['paper_filled'] == summary['paper_skipped_daily_buy_limit'] == 1
            assert summary['net_pnl_pct'] is not None
            assert summary['avg_mfe_pct'] is not None and summary['avg_mae_pct'] is not None
    print('PASS: research=2 closed=2 paper_filled=1 daily_buy_limit_exceeded=1; Research-only usage unchanged; fixture databases only')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
