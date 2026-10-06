"""Build and send the daily paper-trading summary report.

The report is built exclusively from read-only sources:
- canonical paper ledger
- durable intraday logs via journalctl
- runtime-model-status.json / latest-approved.json

It never writes to the ledger, never modifies model artifacts, never logs in
to a broker, and never places orders.
"""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

from daytrade_summary_report import (
    TPE,
    journalctl_lines,
    parse_model_decisions,
    parse_market_risk,
    parse_market_data,
    parse_radar_peak,
    model_state_for_report,
    no_trade_reason,
    format_probability,
    format_threshold,
)


def _symbol_display(symbol, name_lookup):
    """Return '2303 聯電' when a safe name exists, otherwise '2303'."""
    if not symbol:
        return '--'
    name = name_lookup.get(symbol)
    return f'{symbol} {name}' if name else symbol


def build_daily_summary(path, day, intraday_state=None, model_state=None):
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
        if any(row['entry_date'] == day for row in paper_ledger.open_positions(db, pid)):
            return None
        if log and log['semantics_version'] is None:
            return '\n'.join(['📊 EasyStock 模擬當沖歷史結果（舊帳本）', f'日期：{day}',
                f'今日交易筆數：{log["trades_count"]}', f'今日淨損益：{log["net_pnl"]:+,.2f} 元',
                '當日額度與使用額度：--（舊紀錄未保存）'])
        metrics = paper_ledger.daily_metrics(db, pid, day)
        if log and log['daily_buy_limit'] is not None and day != paper_ledger.now().date().isoformat():
            metrics['daily_buy_limit'] = log['daily_buy_limit']
        rows = db.execute("SELECT realized_pnl, symbol, name, side FROM paper_trade_fills "
                          "WHERE period_id=? AND trade_date=? ORDER BY id", (pid, day)).fetchall()
        name_lookup = {row['symbol']: row['name'] for row in rows if row['name']}
        buy_count = sum(1 for row in rows if row['side'] == 'BUY')
        sell_count = sum(1 for row in rows if row['side'] == 'SELL')
        sell_rows = [row for row in rows if row['side'] == 'SELL']
        details = [f'{row["name"] or row["symbol"]} {row["realized_pnl"]:+,.0f}' for row in sell_rows]

    used, limit = metrics['daily_buy_used'], metrics['daily_buy_limit']
    rate = f'{metrics["return_pct"]:+.2f}%' if metrics['return_pct'] is not None else '--'

    if intraday_state is None:
        lines = journalctl_lines(day)
        intraday_state = {
            'model_decisions': parse_model_decisions(lines),
            'market_risk': parse_market_risk(lines),
            'market_data': parse_market_data(lines),
            'radar_peak': parse_radar_peak(lines),
        }
    if model_state is None:
        model_state = model_state_for_report()

    decisions = intraday_state.get('model_decisions') or {}
    market_risk = intraday_state.get('market_risk') or {}
    market_data = intraday_state.get('market_data') or {}
    radar_peak = intraday_state.get('radar_peak', 0)

    # Merge threshold into decisions so no_trade_reason can use it.
    decisions = {**decisions, 'threshold': model_state.get('threshold')}

    lines = ['📊 EasyStock 當沖日報', f'日期：{day}']

    lines += ['', '【市場】']
    effective = (market_risk.get('effective') or 'UNKNOWN').upper()
    gate = (market_risk.get('gate') or 'UNKNOWN').upper()
    lines.append(f'Market Risk：{effective} / {gate}')
    lines.append(f"Shioaji：{(market_data.get('shioaji') or 'UNKNOWN').upper()}")
    lines.append(f"玉山：{(market_data.get('esun') or 'UNKNOWN').upper()}")
    lines.append(f"Premarket：{(market_data.get('premarket') or 'UNKNOWN').upper()}")
    lines.append(f'Radar 最高候選數：{radar_peak}')

    lines += ['', '【AI 模型】']
    lines.append(f"Active Model：{model_state.get('version') or 'UNKNOWN'}")
    lines.append(f"Trained Through：{model_state.get('trained_through') or 'UNKNOWN'}")
    lines.append(f'Threshold：{format_threshold(model_state.get("threshold"))}')
    lines.append(f'今日模型評估：{decisions.get("evaluations", 0)} 次')
    lines.append(f'Accepted：{decisions.get("accepted_count", 0)} 次')
    lines.append(f'今日最高 Probability：{format_probability(decisions.get("max_probability"))}')
    lines.append(f'最高分股票：{_symbol_display(decisions.get("max_probability_symbol"), name_lookup)}')

    lines += ['', '【Paper 模擬】']
    lines.append(f'買進：{buy_count} 筆')
    lines.append(f'賣出：{sell_count} 筆')
    lines.append(f'勝 / 敗：{metrics["wins"]} / {metrics["losses"]}')
    lines.append(f'每日買進額度：{limit:,.2f} 元')
    lines.append(f'今日買進使用額度：{used:,.2f} 元')
    lines.append(f'今日剩餘買進額度：{max(0, limit-used):,.2f} 元')
    lines.append(f'今日已實現損益（費稅前）：{metrics["realized_pnl"]:+,.2f} 元')
    lines.append(f'今日手續費：{metrics["fees"]:,.2f} 元')
    lines.append(f'今日證交稅：{metrics["tax"]:,.2f} 元')
    lines.append(f'今日淨損益：{metrics["net_pnl"]:+,.2f} 元')
    lines.append(f'交易資金報酬率（淨損益／買進使用額度）：{rate}')
    lines.append(f'今日額度使用率：{used/limit*100:.1f}%' if limit else '今日額度使用率：--')
    lines.append(f'累積淨損益：{metrics["cumulative_net_pnl"]:+,.2f} 元')

    lines += ['', '【今日結果】']
    if details:
        lines.append('交易摘要：' + '；'.join(details[:8]))
    elif metrics['trades_count'] == 0:
        lines.append('今日模擬當沖 0 筆。')
    else:
        lines.append(f'今日模擬當沖 {metrics["trades_count"]} 筆。')

    reason = no_trade_reason(metrics, decisions, market_risk, radar_peak)
    if reason:
        lines += ['', '【無交易主因】', reason]

    return '\n'.join(lines)


def main():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
    from easystock_admin.store import Store, db_path
    from market_calendar import is_market_open
    from trade_notifications import send_daily_summary
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Send the report and record a receipt')
    parser.add_argument('--preview', action='store_true', help='Print the report without sending')
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
    if args.preview or not args.send:
        print(text)
        if not args.send:
            return
    send_daily_summary(text, day=day, store=Store())


if __name__ == '__main__':
    main()
