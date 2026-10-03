"""Regression for daily BUY limits and additive cash-era migration, offline only."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easystock_admin.store import Store
import paper_account as account
import paper_ledger as ledger

class CashLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'state.sqlite'
        self.env=patch.dict(os.environ,{'EASYSTOCK_ADMIN_DB':str(self.path)});self.env.start()
        Store(initial={'min_price':1,'max_price':1000,'max_gain_pct':5})
        with sqlite3.connect(self.path) as db:
            ledger.init_schema(db)
            db.execute("INSERT INTO meta VALUES('paper_trade_period_current','fixture')")
            db.execute("INSERT INTO paper_trade_periods(id,created_at,starting_cash,archive_path) VALUES('fixture','2026-09-01',100000,'fixture')")
            db.execute("INSERT INTO paper_trade_settings(id,initial_capital,current_capital,status,start_date,updated_at) VALUES(1,100000,100000,'running','2026-09-01',0)")
            ledger.migrate(db)

    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def query(self,sql):
        with sqlite3.connect(self.path) as db:return db.execute(sql).fetchall()

    def test_deployment_probe_leaves_source_database_unchanged(self):
        import subprocess
        before = self.path.read_bytes()
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable,str(root/'deploy/verify_paper_ledger.py'),
                                 '--database',str(self.path),'--runtime',str(root/'vm_runtime')],
                                text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.path.read_bytes(),before)

    def test_cash_roundtrip_and_receipt(self):
        self.assertEqual(len(self.query('PRAGMA table_info(paper_trade_positions)')),8)
        self.assertIn('daily_buy_used',[r[1] for r in self.query('PRAGMA table_info(paper_trade_logs)')])
        buy=account.buy('2330','fixture',100)
        self.assertEqual(buy['shares'],1000)
        self.assertEqual(ledger.snapshot(self.path)['settings']['daily_buy_remaining'],0)
        self.assertEqual(account.open_positions()[0]['trade_id'],buy['trade_id'])
        sell=account.sell('2330',101,trade_id=buy['trade_id'])
        self.assertEqual(sell['net_pnl'],768)
        self.assertEqual(self.query('SELECT end_balance FROM paper_trade_logs')[0][0],100768)
        self.assertEqual(sell['daily_buy_remaining'],0)
        self.assertEqual(self.query('SELECT net_pnl,costs,trades_count,settlement_status FROM paper_trade_logs'),[(768,232,1,'settled')])
        again=account.sell('2330',102,trade_id=buy['trade_id'])
        self.assertTrue(again['already_settled'])
        self.assertEqual(len(self.query('SELECT * FROM paper_trade_fills')),2)

    def test_parallel_buy_cannot_spend_cash_twice(self):
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda s:account.buy(s,s,100),['2330','2317']))
        self.assertEqual(sum(r['status']=='bought' for r in results),1)
        self.assertEqual(ledger.snapshot(self.path)['settings']['daily_buy_used'],100000)

    def test_failed_sell_rolls_back_fills_cash_and_position(self):
        buy=account.buy('2330','fixture',100)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER fail_sell BEFORE INSERT ON paper_trade_fills WHEN NEW.side='SELL' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):account.sell('2330',101,trade_id=buy['trade_id'])
        self.assertEqual(ledger.snapshot(self.path)['settings']['daily_buy_used'],100000)
        self.assertEqual(len(account.open_positions()),1)
        self.assertEqual(self.query('SELECT settlement_status FROM paper_trade_logs'),[('pending',)])
        self.assertEqual(len(self.query('SELECT * FROM paper_trade_fills')),1)

    def test_missing_period_and_old_receipt_cannot_close_new_position(self):
        first=account.buy('2330','fixture',100)
        account.sell('2330',101,trade_id=first['trade_id'])
        with sqlite3.connect(self.path) as db:db.execute('UPDATE paper_trade_settings SET daily_buy_limit=200000')
        second=account.buy('2330','fixture',100)
        account.sell('2330',105,trade_id=first['trade_id'])
        self.assertEqual(account.open_positions()[0]['trade_id'],second['trade_id'])
        with self.assertRaises(ValueError):account.sell('2330',101,trade_id='wrong')
        with sqlite3.connect(self.path) as db:db.execute("DELETE FROM meta WHERE key='paper_trade_period_current'")
        with self.assertRaises(RuntimeError):account.buy('2317','fixture',10)

    def test_existing_ledger_position_identity_recovered_from_fill(self):
        buy=account.buy('2330','fixture',100)
        with sqlite3.connect(self.path) as db:db.execute("DELETE FROM meta WHERE key='paper-position:2330'")
        self.assertEqual(account.open_positions()[0]['trade_id'],buy['trade_id'])
        self.assertEqual(account.sell('2330',101,trade_id=buy['trade_id'])['status'],'sold')

    def test_overnight_position_blocks_buy_and_sell(self):
        account.buy('2330','fixture',100)
        with sqlite3.connect(self.path) as db:db.execute("UPDATE paper_trade_positions SET entry_date='2020-01-01'")
        self.assertEqual(account.buy('2317','fixture',10)['status'],'skipped')
        with self.assertRaises(RuntimeError):account.sell('2330',101)

if __name__=='__main__':unittest.main()
