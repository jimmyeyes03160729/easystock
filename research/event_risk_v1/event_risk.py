#!/usr/bin/env python3
"""EVENT_RISK_V1: are investor-conference / earnings days abnormal for a long-at-open day trade?

Implements docs/research_governance/preregistrations/EVENT_RISK_V1.yaml exactly. Run once on the VM:
  python research/event_risk_v1/event_risk.py --bars <market-daily.sqlite> --events <events.sqlite> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

FIRST_DAY = '2025-01-06'
LAST_DAY = '2026-10-02'          # hard ceiling: nothing after this day may be read
RANK_MAX = 0.15
COMMON = re.compile(r'^[1-9][0-9]{3}$')
EVENTS = ('POST_REPORT', 'CONF_START', 'POST_CONF', 'BOARD_DAY')
REPORT_CATEGORIES = ('financial_report_approved', 'self_reported_earnings')
MIN_EVENT_DAYS = 300


# ---------------------------------------------------------------- event tagging

def tag_events(days: list[str], announcements: list[tuple], conferences: list[tuple], board: list[tuple]) -> dict:
    """{(symbol, day): set(events)} for trading days `days` (sorted, starting with the session before the first).

    announcements: (symbol, spoke_date, spoke_time) of REPORT_CATEGORIES
    conferences:   (symbol, start_date, end_date)
    board:         (symbol, spoke_date, meeting_date)
    """
    tags: dict[tuple, set] = defaultdict(set)
    prev = {d: p for p, d in zip(days, days[1:])}
    # POST_REPORT: spoke in (P 13:30:00, D 09:00:00]
    windows = [(p + ' 13:30:00', d + ' 09:00:00', d) for d, p in prev.items()]
    by_symbol = defaultdict(list)
    for symbol, spoke_date, spoke_time in announcements:
        by_symbol[symbol].append('%s %s' % (spoke_date, spoke_time or '00:00:00'))
    for symbol, stamps in by_symbol.items():
        for stamp in stamps:
            for lo, hi, d in windows:
                if lo < stamp <= hi:
                    tags[(symbol, d)].add('POST_REPORT')
    for symbol, start, end in conferences:
        if start in prev:
            tags[(symbol, start)].add('CONF_START')
        for d, p in prev.items():
            if p <= end < d:
                tags[(symbol, d)].add('POST_CONF')
    for symbol, spoke_date, meeting in board:
        if meeting in prev and spoke_date < meeting:
            tags[(symbol, meeting)].add('BOARD_DAY')
    return tags


# ---------------------------------------------------------------- statistics

def clustered_mean(values: list[tuple[str, float]]) -> tuple[float, float, int]:
    """(mean, day-clustered SE, n) for (day, x) pairs."""
    n = len(values)
    if n == 0:
        return float('nan'), float('nan'), 0
    mean = sum(x for _, x in values) / n
    per_day = defaultdict(float)
    for day, x in values:
        per_day[day] += x - mean
    se = math.sqrt(sum(v * v for v in per_day.values())) / n
    return mean, se, n


def summarize(rows: list[dict]) -> dict:
    out = {}
    for metric in ('gap', 'abs_gap', 'oc', 'range'):
        mean, se, n = clustered_mean([(r['day'], r[metric]) for r in rows])
        out[metric] = {'mean': mean, 'se': se}
    out['n'] = len(rows)
    out['days'] = len({r['day'] for r in rows})
    out['oc_sd'] = statistics.pstdev([r['oc'] for r in rows]) if len(rows) > 1 else float('nan')
    out['per_1m'] = out['oc']['mean'] * 1_000_000 if rows else float('nan')
    return out


def compare(event: dict, control: dict) -> dict:
    ex = event['oc']['mean'] - control['oc']['mean']
    se = math.sqrt(event['oc']['se'] ** 2 + control['oc']['se'] ** 2)
    return {'excess_oc_bps': ex * 1e4, 't': ex / se if se > 0 else float('nan'),
            'excess_per_1m': ex * 1_000_000,
            'sd_ratio': event['oc_sd'] / control['oc_sd'] if control['oc_sd'] else float('nan'),
            'abs_gap_ratio': event['abs_gap']['mean'] / control['abs_gap']['mean'] if control['abs_gap']['mean'] else float('nan')}


def classify(n: int, cmp_all: dict, cmp_halves: list[dict]) -> str:
    if n < MIN_EVENT_DAYS:
        return 'INSUFFICIENT'
    if cmp_all['excess_oc_bps'] <= -20 and cmp_all['t'] <= -2.0 and all(h['excess_oc_bps'] < 0 for h in cmp_halves):
        return 'SKIP_SUPPORTED'
    if cmp_all['sd_ratio'] >= 1.3 or cmp_all['abs_gap_ratio'] >= 1.5:
        return 'SIZE_DOWN_CANDIDATE'
    return 'NO_EFFECT'


# ---------------------------------------------------------------- loading

def load(bars_path: str, events_path: str):
    bars = sqlite3.connect('file:%s?mode=ro' % bars_path, uri=True)
    days = [r[0] for r in bars.execute('SELECT DISTINCT day FROM bars WHERE day <= ? AND day >= ? ORDER BY day',
                                       (LAST_DAY, '2025-01-01'))]
    first = days.index(FIRST_DAY) if FIRST_DAY in days else next(i for i, d in enumerate(days) if d >= FIRST_DAY)
    days = days[first - 1:]                               # keep one previous session
    assert days[-1] <= LAST_DAY
    prev = {d: p for p, d in zip(days, days[1:])}
    liquid = {(s, d) for s, d in bars.execute('SELECT symbol, day FROM amount_ranks WHERE rank <= ? AND day >= ? AND day <= ?',
                                              (RANK_MAX, days[0], LAST_DAY))}
    rows = []
    for symbol, day, o, h, l, c, ref in bars.execute(
            'SELECT symbol, day, open, high, low, close, reference FROM bars WHERE day > ? AND day <= ?', (days[0], LAST_DAY)):
        if not COMMON.match(symbol) or (symbol, prev.get(day)) not in liquid:
            continue
        if not (o and h and l and c and ref) or min(o, h, l, c, ref) <= 0:
            continue
        rows.append({'symbol': symbol, 'day': day, 'gap': o / ref - 1, 'abs_gap': abs(o / ref - 1),
                     'oc': c / o - 1, 'range': (h - l) / ref})
    ev = sqlite3.connect('file:%s?mode=ro' % events_path, uri=True)
    hi = LAST_DAY + ' 09:00:00'
    announcements = [r for r in ev.execute(
        'SELECT symbol, spoke_date, spoke_time FROM announcements WHERE category IN (?,?) AND spoke_date <= ?',
        (*REPORT_CATEGORIES, LAST_DAY)) if '%s %s' % (r[1], r[2] or '') <= hi]
    conferences = ev.execute('SELECT symbol, start_date, end_date FROM conferences WHERE start_date <= ?', (LAST_DAY,)).fetchall()
    board = ev.execute("SELECT symbol, spoke_date, meeting_date FROM announcements WHERE category='board_meeting_scheduled' "
                       "AND meeting_date IS NOT NULL AND meeting_date <= ?", (LAST_DAY,)).fetchall()
    return days, rows, announcements, conferences, board


def run(days, rows, announcements, conferences, board) -> dict:
    tags = tag_events(days, announcements, conferences, board)
    for r in rows:
        r['events'] = tags.get((r['symbol'], r['day']), set())
    control = [r for r in rows if not r['events']]
    halves = {'2025': lambda r: r['day'] < '2026-01-01', '2026': lambda r: r['day'] >= '2026-01-01'}
    result = {'universe_stock_days': len(rows), 'trading_days': len({r['day'] for r in rows}),
              'control': summarize(control), 'events': {}}
    for e in EVENTS:
        group = [r for r in rows if e in r['events']]
        s = summarize(group)
        cmp_all = compare(s, result['control']) if group else {}
        cmp_halves = []
        half_out = {}
        for name, keep in halves.items():
            g = [r for r in group if keep(r)]
            c = [r for r in control if keep(r)]
            if g and c:
                ch = compare(summarize(g), summarize(c))
                cmp_halves.append(ch)
                half_out[name] = {'n': len(g), **ch}
        decision = classify(len(group), cmp_all, cmp_halves) if group else 'INSUFFICIENT'
        result['events'][e] = {'summary': s, 'vs_control': cmp_all, 'halves': half_out, 'decision': decision}
    return result


def final_lines(res: dict) -> list[str]:
    c = res['control']
    lines = ['EVENT_RISK_V1 universe_stock_days=%d trading_days=%d' % (res['universe_stock_days'], res['trading_days']),
             'CONTROL n=%d oc=%+.1fbps per1M=%+.0f abs_gap=%.2f%% range=%.2f%% oc_sd=%.2f%%' % (
                 c['n'], c['oc']['mean'] * 1e4, c['per_1m'], c['abs_gap']['mean'] * 100, c['range']['mean'] * 100, c['oc_sd'] * 100)]
    for e, v in res['events'].items():
        s, k = v['summary'], v['vs_control']
        if not k:
            lines.append('%s n=0 decision=%s' % (e, v['decision']))
            continue
        lines.append('%s n=%d oc=%+.1fbps excess=%+.1fbps t=%.2f excess_per1M=%+.0f sd_ratio=%.2f abs_gap_ratio=%.2f '
                     'halves=%s decision=%s' % (
                         e, s['n'], s['oc']['mean'] * 1e4, k['excess_oc_bps'], k['t'], k['excess_per_1m'], k['sd_ratio'],
                         k['abs_gap_ratio'], ','.join('%s:%+.1f' % (h, x['excess_oc_bps']) for h, x in v['halves'].items()),
                         v['decision']))
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--bars', required=True)
    ap.add_argument('--events', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res = run(*load(args.bars, args.events))
    (out / 'EVENT_RISK_V1.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    lines = final_lines(res)
    (out / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
