"""Build the personal daily result exclusively from the canonical paper ledger."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

TPE = timezone(timedelta(hours=8))


def build_daily_summary(path, day):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        account = db.execute('SELECT initial_capital,current_capital,status,start_date FROM paper_trade_settings WHERE id=1').fetchone()
        if not account or not account['start_date'] or account['start_date'] > day:
            return None
        columns = {row[1] for row in db.execute('PRAGMA table_info(paper_trade_logs)')}
        log = db.execute('SELECT * FROM paper_trade_logs WHERE date=?', (day,)).fetchone()
        if log and 'settlement_status' in columns and log['settlement_status'] != 'settled':
            return None
        start = float(log['start_balance']) if log else float(account['current_capital'])
        end = float(log['end_balance']) if log else float(account['current_capital'])
        pnl = float(log['net_pnl']) if log else 0.0
        count = int(log['trades_count']) if log else 0
        symbols = str(log['symbols'] or '').strip() if log else ''
        wins = losses = None
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_trade_fills'").fetchone():
            period = db.execute("SELECT value FROM meta WHERE key='paper_trade_period_current'").fetchone()
            if not period:
                return None
            rows = db.execute("SELECT realized_pnl,symbol,name FROM paper_trade_fills WHERE period_id=? AND trade_date=? AND side='SELL' ORDER BY id", (period[0], day)).fetchall()
            wins = sum(float(row['realized_pnl']) > 0 for row in rows)
            losses = sum(float(row['realized_pnl']) <= 0 for row in rows)
            details = [f"{row['name'] or row['symbol']} {float(row['realized_pnl']):+,.0f}" for row in rows]
        else:
            details = [item.strip() for item in symbols.split(',') if item.strip()]
    rate = (pnl / start * 100) if start else 0.0
    lines = [
        '📊 EasyStock 模擬當沖盤後結果',
        f'日期：{day}',
        f'今日交易筆數：{count}',
        f"勝 / 敗：{wins} / {losses}" if wins is not None else '勝 / 敗：-- / --',
        f'今日已實現損益：{pnl:+,.2f} 元',
        f'今日報酬率：{rate:+.2f}%',
        f'目前模擬帳戶資金：{end:,.2f} 元',
    ]
    if details:
        lines += ['', '交易摘要：' + '；'.join(details[:8])]
    elif count == 0:
        lines += ['', '今日模擬當沖 0 筆。']
    return '\n'.join(lines)


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
    from easystock_admin.store import Store, db_path
    from market_calendar import is_market_open
    from trade_notifications import send_daily_summary
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    now = datetime.now(TPE)
    day = now.date().isoformat()
    if args.send and not time(13, 25) <= now.time().replace(tzinfo=None) <= time(20, 30):
        print('Outside scheduled summary window; skipped')
        return
    if args.send and not is_market_open(day)[0]:
        print('Not a trading day; skipped')
        return
    if args.send:
        try:
            import paper_account
            if paper_account.ledger_kind() == 'cash':
                import paper_ledger
                paper_ledger.finalize_today(path=db_path())
        except Exception as exc:
            print('[SUMMARY] canonical ledger finalization unavailable:', type(exc).__name__)
            return
    text = build_daily_summary(db_path(), day)
    if not text:
        print('No valid paper session/result; skipped')
        return
    if not args.send:
        print(text)
        return
    send_daily_summary(text, day=day, store=Store())


if __name__ == '__main__':
    main()
