"""Shared paper valuation/calendar helpers. No module publisher or strategy entrypoint."""
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / 'research' / 'revenue_v1'))
import rev_study as R
REVENUE_DIR = Path(os.environ.get('REVENUE_FORWARD_DIR', '/home/ubuntu/easystock-research/revenue_v1/forward'))
LIMIT_UP = 1.09
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

def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
