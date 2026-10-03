"""Build the personal daily result exclusively from the canonical paper ledger."""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

TPE = timezone(timedelta(hours=8))


def build_daily_summary(path, day):
    import paper_ledger
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        account = db.execute('SELECT * FROM paper_trade_settings WHERE id=1').fetchone()
        if not account or not account['start_date'] or account['start_date'] > day:
            return None
        pid = paper_ledger.period(db)
        log = db.execute('SELECT * FROM paper_trade_logs WHERE date=?', (day,)).fetchone()
        if log and log['settlement_status'] != 'settled':
            return None
        if any(row['entry_date'] == day for row in paper_ledger.open_positions(db,pid)):
            return None
        if log and log['semantics_version'] is None:
            return '\n'.join(['📊 EasyStock 模擬當沖歷史結果（舊帳本）',f'日期：{day}',
                f'今日交易筆數：{log["trades_count"]}',f'今日淨損益：{log["net_pnl"]:+,.2f} 元',
                '當日額度與使用額度：--（舊紀錄未保存）'])
        metrics = paper_ledger.daily_metrics(db,pid,day)
        if log and log['daily_buy_limit'] is not None and day != paper_ledger.now().date().isoformat():
            metrics['daily_buy_limit'] = log['daily_buy_limit']
        rows = db.execute("SELECT realized_pnl,symbol,name FROM paper_trade_fills WHERE period_id=? AND trade_date=? AND side='SELL' ORDER BY id", (pid,day)).fetchall()
        details = [f'{row["name"] or row["symbol"]} {row["realized_pnl"]:+,.0f}' for row in rows]
    used,limit = metrics['daily_buy_used'],metrics['daily_buy_limit']
    rate = f'{metrics["return_pct"]:+.2f}%' if metrics['return_pct'] is not None else '--'
    lines = ['📊 EasyStock 模擬當沖盤後結果',f'日期：{day}',
        f'今日交易筆數：{metrics["trades_count"]}',
        f'勝 / 敗：{metrics["wins"]} / {metrics["losses"]}',
        f'每日買進額度：{limit:,.2f} 元',
        f'今日買進使用額度：{used:,.2f} 元',
        f'今日剩餘買進額度：{max(0,limit-used):,.2f} 元',
        f'今日已實現損益（費稅前）：{metrics["realized_pnl"]:+,.2f} 元',
        f'今日手續費：{metrics["fees"]:,.2f} 元',
        f'今日證交稅：{metrics["tax"]:,.2f} 元',
        f'今日淨損益：{metrics["net_pnl"]:+,.2f} 元',
        f'交易資金報酬率（淨損益／買進使用額度）：{rate}',
        f'今日額度使用率：{used/limit*100:.1f}%' if limit else '今日額度使用率：--',
        f'累積淨損益：{metrics["cumulative_net_pnl"]:+,.2f} 元']
    if details:
        lines += ['', '交易摘要：' + '；'.join(details[:8])]
    elif metrics['trades_count'] == 0:
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
            if paper_account.ledger_kind() == 'daily_limit':
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
