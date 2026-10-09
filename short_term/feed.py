"""短期持股（15 天內）首頁資料：月營收驚喜（S2_SUR）凍結名單的紙上追蹤。

選股不在這裡做：REVENUE_FORWARD_V1（research/revenue_v1/rev_fwd.py）在每月營收截止日晚上凍結名單。
本模組只讀凍結名單、日線與營收，算進場價、目前損益與已結束批次，發布到 /market_data/public_feed/short_term。
不下單。持有天數與顯示檔數依 REVENUE_SHORT_V1 事先凍結的首頁規則決定。
"""
import json
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'research' / 'revenue_v1'))
import rev_study as R  # noqa: E402  (same signal and cost definitions as the research)

TPE = timezone(timedelta(hours=8))
RULES_VERSION = 'revenue-sur-short-v1'
PICKS_DIR = Path(os.environ.get('SHORT_TERM_PICKS_DIR', '/home/ubuntu/easystock-research/revenue_v1/forward'))
DAILY_DB = os.environ.get('SHORT_TERM_DAILY_DB', R.DAILY_DB)
OUT_DIR = Path(os.environ.get('SHORT_TERM_OUT_DIR', '/home/ubuntu/easystock-short-term'))
FIRST_DAY = '2026-10-01'
HOLD_SESSIONS = 10
LIST_MODE = 'TOP10'
TOP_N = 10
LIMIT_UP = 1.09
CAPITAL = 1_000_000
# REVENUE_SHORT_V1 (sealed 2026-10-09): per monthly batch, net of fees and 0.3% tax, limit-up opens unfillable.
BACKTEST = {'study': 'REVENUE_SHORT_V1', 'period': '2022-02..2026-09', 'events': 56,
            'top10_h10': {'net_pct': 1.28, 'excess_pct': 0.57, 't': 1.24, 'win_events': 35, 'worst_pct': -8.24, 'twd_per_1m': 12834},
            'decile_h10': {'net_pct': 1.62, 'excess_pct': 0.90, 't': 4.17, 'win_events': 38, 'worst_pct': -9.19, 'twd_per_1m': 16170}}


def add_sessions(sessions, start, n, is_closed):
    """The n-th session on or after start: recorded sessions first, then weekdays the calendar does not close."""
    days = [d for d in sessions if d >= start]
    cur = date.fromisoformat(days[-1]) if days else date.fromisoformat(start) - timedelta(days=1)
    while len(days) < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and not is_closed(cur.isoformat()):
            days.append(cur.isoformat())
    return days[n - 1]


def next_session(sessions, day, is_closed):
    return add_sessions(sessions, (date.fromisoformat(day) + timedelta(days=1)).isoformat(), 1, is_closed)


def deadline_session(month, sessions, is_closed):
    """Picks for revenue month M are frozen on the first session on or after the 10th of month M+1."""
    return add_sessions(sessions, R.add_months(month, 1) + '-10', 1, is_closed)


def position_returns(symbols, bars, ex, entry_day, mark_day):
    """Net % per fillable symbol from the entry open to the last close on or before mark_day; limit-up opens are unfilled."""
    out, unfilled = {}, []
    for s in symbols:
        by = bars.get(s, {})
        bar = by.get(entry_day)
        if not bar or not bar['open'] or bar['open'] <= 0 or (bar['reference'] and bar['open'] >= LIMIT_UP * bar['reference']):
            unfilled.append(s)
            continue
        last = max(d for d in by if entry_day <= d <= mark_day)
        factor = math.prod(f for d, f in ex.get(s, ()) if entry_day < d <= last)
        mark = by[last]['close']
        out[s] = {'entry': bar['open'], 'mark': mark, 'mark_day': last,
                  'net_pct': (mark * factor / bar['open'] - 1) * 100 - R.cost_pct(bar['open'], mark, same_day=False)}
    return out, unfilled


def last_close(by, day):
    days = [d for d in by if d <= day]
    return by[max(days)]['close'] if days else None


def build_batch(picks, revenue, names, sessions, bars, ex, is_closed, hold=HOLD_SESSIONS, list_mode=LIST_MODE):
    """One monthly batch: planned dates, positions and, once entered, portfolio net, baseline and excess."""
    month, D = picks['month'], picks['deadline_session']
    s2 = picks['signals']['S2_SUR']
    chosen = s2['top'][:TOP_N] if list_mode == 'TOP10' else s2['top']
    per_name = CAPITAL / max(1, len(chosen))
    E = next_session(sessions, D, is_closed)
    X = add_sessions(sessions, E, hold, is_closed)
    last = sessions[-1] if sessions else ''
    sur = R.signals_for(revenue, month)['S2_SUR']
    rows = []
    for rank, s in enumerate(chosen, 1):
        r, ly = revenue.get(s, {}).get(month, (None, None))
        y = R.yoy(r, ly)
        ref = last_close(bars.get(s, {}), D)
        rows.append({'rank': rank, 'symbol': s, 'name': names.get(s, ''),
                     'sur': None if sur.get(s) is None else round(sur[s], 2),
                     'rev_yoy_pct': None if y is None else round(y * 100, 1),
                     'deadline_close': ref, 'shares_est': int(per_name // ref) if ref else None})
    batch = {'month': month, 'deadline_session': D, 'entry_day': E, 'exit_day': X, 'hold_sessions': hold,
             'list_mode': list_mode, 'universe_size': s2['n_scored'], 'decile_size': len(s2['top']),
             'capital_per_name': round(per_name), 'positions': rows}
    if last < E:
        batch['status'] = 'waiting_entry'
        return batch
    mark_day = min(last, X)
    rets, unfilled = position_returns(chosen, bars, ex, E, mark_day)
    base, _ = position_returns(s2['scored'], bars, ex, E, mark_day)
    for row in rows:
        p = rets.get(row['symbol'])
        row.update(filled=p is not None, entry=p and p['entry'], mark=p and p['mark'],
                   net_pct=None if p is None else round(p['net_pct'], 2),
                   shares=None if p is None else int(per_name // p['entry']))
    if list_mode == 'TOP10':
        net = sum(p['net_pct'] for p in rets.values()) / TOP_N     # an unfilled name leaves its tenth in cash
    else:
        net = sum(p['net_pct'] for p in rets.values()) / len(rets) if rets else None
    uni = sum(p['net_pct'] for p in base.values()) / len(base) if base else None
    batch.update(status='closed' if last >= X else 'holding', mark_day=mark_day, n_filled=len(rets), n_unfilled=len(unfilled),
                 net_pct=None if net is None else round(net, 2),
                 universe_net_pct=None if uni is None else round(uni, 2),
                 excess_pct=None if net is None or uni is None else round(net - uni, 2),
                 twd_per_1m=None if net is None else round(net * 10000))
    return batch


def build_feed(batches, today, next_deadline, next_entry, generated_at):
    ordered = sorted(batches, key=lambda b: b['month'], reverse=True)
    current = next((b for b in ordered if b['status'] != 'closed'), None)
    closed = [b for b in ordered if b['status'] == 'closed']
    keys = ('month', 'entry_day', 'exit_day', 'n_filled', 'net_pct', 'universe_net_pct', 'excess_pct', 'twd_per_1m')
    return {'schema_version': 1, 'rules_version': RULES_VERSION, 'generated_at': generated_at, 'as_of': today,
            'strategy': {'hold_sessions': HOLD_SESSIONS, 'list_mode': LIST_MODE, 'top_n': TOP_N, 'capital': CAPITAL,
                         'limit_up_ratio': LIMIT_UP, 'backtest': BACKTEST},
            'current': current, 'last_closed': closed[0] if closed else None,
            'history': [{k: b.get(k) for k in keys} for b in closed],
            'record': {'batches': len(closed), 'wins': sum(1 for b in closed if (b['net_pct'] or 0) > 0),
                       'twd_per_1m_total': sum(b['twd_per_1m'] or 0 for b in closed)},
            'next': {'deadline_session': next_deadline, 'entry_day': next_entry}}


def load_inputs(months):
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? ORDER BY day", (FIRST_DAY,))]
    bars, ex = {}, {}
    for s, d, o, c, rf in daily.execute('SELECT symbol, day, open, close, reference FROM bars WHERE day >= ?', (FIRST_DAY,)):
        bars.setdefault(s, {})[d] = {'open': o, 'close': c, 'reference': rf}
    for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day >= ?', (FIRST_DAY,)):
        if ref and ref > 0 and pc and pc > 0:
            ex.setdefault(s, []).append((d, pc / ref))
    daily.close()
    revenue, names = {}, {}
    db_path = PICKS_DIR / 'revenue.sqlite'
    if db_path.exists() and months:
        db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
        for s, m, r, ly, name in db.execute('SELECT symbol, month, revenue, last_year, name FROM revenue WHERE month >= ? ORDER BY month',
                                            (R.add_months(min(months), -13),)):
            revenue.setdefault(s, {})[m] = (r, ly)
            if name:
                names[s] = name
        db.close()
    return sessions, bars, ex, revenue, names


def calendar_closed():
    sys.path.insert(0, str(REPO))
    from market_calendar import fetch_twse_calendar
    cache = {}

    def is_closed(day):
        y = int(day[:4])
        if y not in cache:
            cache[y] = fetch_twse_calendar(y)
        return day in cache[y]
    return is_closed


def upcoming(today, months_frozen, sessions, is_closed):
    """The next deadline evening that has not frozen its picks yet, and its entry session."""
    month = R.add_months(today[:7], -1)
    D = deadline_session(month, sessions, is_closed)
    if D < today or month in months_frozen:
        D = deadline_session(R.add_months(month, 1), sessions, is_closed)
    return D, next_session(sessions, D, is_closed)


def main(publish=True):
    now = datetime.now(TPE)
    today = now.date().isoformat()
    is_closed = calendar_closed()
    picks = [json.loads(p.read_text()) for p in sorted(PICKS_DIR.glob('picks_*.json'))]
    sessions, bars, ex, revenue, names = load_inputs([p['month'] for p in picks])
    batches = [build_batch(p, revenue, names, sessions, bars, ex, is_closed) for p in picks]
    D, E = upcoming(today, {p['month'] for p in picks}, sessions, is_closed)
    feed = build_feed(batches, today, D, E, now.isoformat(timespec='seconds'))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT_DIR / 'short-term-latest.tmp'
    tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(OUT_DIR / 'short-term-latest.json')
    if publish:
        sys.path.insert(0, str(REPO))
        from firebase_store import FirebaseStore
        FirebaseStore().root.child('public_feed').child('short_term').set(feed)
    print(json.dumps({'batches': len(batches), 'current': feed['current'] and feed['current']['status'], 'next': feed['next']}))


if __name__ == '__main__':
    main(publish='--no-publish' not in sys.argv)
