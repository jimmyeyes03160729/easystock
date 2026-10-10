#!/usr/bin/env python3
"""BUYBACK_V1 study (frozen preregistration): buy the open after the planned buyback period starts, hold 5 / 20 / 60 sessions."""
import hashlib, json, math, sqlite3, sys, tarfile
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT.parent / 'inst_flow_v1'), str(ROOT.parent / 'revenue_v1'), str(ROOT.parents[1]), '/home/ubuntu/easystock']
import ifl_study as IFL  # noqa: E402  (frozen loaders and vectorised paper_execution costs)

CUTOFF = '2026-10-02'
DB = ROOT / 'data' / 'buyback.sqlite'
OUT = ROOT / 'output'
FIRST_BOARD, LAST_BOARD = '2022-01-01', '2026-09-30'
HOLDS = (('H20', 20), ('H5', 5), ('H60', 60))
MIN_AMOUNT, MIN_AMOUNT_ALL, MIN_PRICE, LIMIT_UP, LOOK = 50_000_000, 20_000_000, 10.0, 1.09, 20
COUNTED_YEAR_MIN, MIN_COUNTED_YEARS, MIN_EVENTS = 8, 3, 60


def entry_index(sessions, start_date):
    """E = first session strictly after the planned buyback period start date."""
    return bisect_right(sessions, start_date)


def cluster_t(xs, groups):
    """t statistic of the mean with a standard error clustered by group (here the entry month)."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    acc = defaultdict(float)
    for x, g in zip(xs, groups):
        acc[g] += x - m
    se = math.sqrt(sum(v * v for v in acc.values())) / n
    return m / se if se > 0 else None


def summarize(events):
    n = len(events)
    if not n:
        return None
    net, exc = [e['net'] for e in events], [e['excess'] for e in events]
    years = {}
    for y in sorted({e['year'] for e in events}):
        ev = [e for e in events if e['year'] == y]
        years[y] = {'n': len(ev), 'net': sum(e['net'] for e in ev) / len(ev), 'excess': sum(e['excess'] for e in ev) / len(ev)}
    counted = {y: v for y, v in years.items() if v['n'] >= COUNTED_YEAR_MIN}
    need = math.ceil(0.75 * len(counted)) if counted else 0
    mean_net, mean_exc = sum(net) / n, sum(exc) / n
    t = cluster_t(exc, [e['month'] for e in events])
    c = {'A': mean_net > 0,
         'B': bool(counted) and sum(1 for v in counted.values() if v['net'] > 0) >= need,
         'C': mean_exc > 0 and t is not None and t >= 2.0,
         'D': bool(counted) and sum(1 for v in counted.values() if v['excess'] > 0) >= need,
         'G': len(counted) >= MIN_COUNTED_YEARS and n >= MIN_EVENTS}
    return c, {'events': n, 'mean_net_pct': mean_net, 'mean_excess_pct': mean_exc, 't_excess_cluster_month': t,
               'median_net_pct': float(np.median(net)), 'per_1m_net_twd': mean_net * 10000, 'per_1m_excess_twd': mean_exc * 10000,
               'win_rate': sum(1 for x in net if x > 0) / n, 'years': years, 'months': len({e['month'] for e in events})}


def classify(c):
    if not c['G']:
        return 'INSUFFICIENT'
    if all(c[k] for k in 'ABCD'):
        return 'STRONG'
    if c['C'] and c['D']:
        return 'RELATIVE_ONLY'
    if not c['A'] and not c['C']:
        return 'NO_EDGE'
    return 'WEAK'


def main():
    OUT.mkdir(exist_ok=True)
    sessions, symbols, O, C, REF, V, A, FN, TN, L = IFL.load()
    six = {s: j for j, s in enumerate(symbols)}
    CF = C.copy()
    for i in range(1, len(sessions)):
        miss = np.isnan(CF[i])
        CF[i, miss] = CF[i - 1, miss]
    amt20 = IFL.rolling_sum(A.astype(np.float64), LOOK) / LOOK
    db = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    progs = db.execute('SELECT symbol, board_date, purpose, start_date, market FROM programs WHERE board_date >= ? AND board_date <= ? ORDER BY board_date, symbol',
                       (FIRST_BOARD, LAST_BOARD)).fetchall()
    db.close()
    cache, cnt = {}, Counter()

    def net_row(e, x):
        if (e, x) not in cache:
            with np.errstate(invalid='ignore', divide='ignore'):
                gross = (CF[x] * np.exp(L[x] - L[e]) / O[e] - 1) * 100.0
                cache[(e, x)] = gross - IFL.cost_pct_vec(O[e], CF[x], same_day=False)
        return cache[(e, x)]

    def universe_mask(e, floor):
        d = e - 1
        fill = np.isfinite(O[e]) & (O[e] > 0) & ~(np.isfinite(REF[e]) & (O[e] >= LIMIT_UP * REF[e]))
        return np.isfinite(amt20[d]) & (amt20[d] >= floor) & np.isfinite(C[d]) & (C[d] >= MIN_PRICE) & fill

    groups = {}
    for sym, board, purpose, start, market in progs:
        j = six.get(sym)
        if j is None:
            cnt['NO_PRICE_SYMBOL'] += 1
            continue
        e = entry_index(sessions, start)
        if e >= len(sessions) or e <= LOOK:
            cnt['NO_ENTRY_SESSION_OR_HISTORY'] += 1
            continue
        for hname, n in HOLDS:
            x = e + n - 1
            if x >= len(sessions):
                cnt['DROP_EXIT_AFTER_CUTOFF:' + hname] += 1
                continue
            for floor_name, floor in (('LIQ50', MIN_AMOUNT), ('LIQ20', MIN_AMOUNT_ALL)):
                mask = universe_mask(e, floor)
                row = net_row(e, x)
                ok = mask & np.isfinite(row)
                if not mask[j] or not np.isfinite(row[j]) or ok.sum() < 100:
                    cnt['NOT_ELIGIBLE:%s:%s' % (floor_name, hname)] += 1
                    continue
                ev = {'symbol': sym, 'board': board, 'entry': sessions[e], 'exit': sessions[x], 'year': int(sessions[e][:4]), 'month': sessions[e][:7],
                      'net': float(row[j]), 'base': float(row[ok].mean()), 'excess': float(row[j] - row[ok].mean()), 'market': market}
                groups.setdefault((purpose, floor_name, hname), []).append(ev)
    res, lines = {}, []
    for (purpose, floor_name, hname), events in sorted(groups.items()):
        out = summarize(events)
        if not out:
            continue
        c, st = out
        cls = classify(c)
        res['%s|%s|%s' % (purpose, floor_name, hname)] = {'classification': cls, 'criteria': c, 'stats': st, 'events': events}
        lines.append('purpose=%s %s %-3s %-13s events=%d months=%d net=%+.2f%% (%+.0f TWD/1M) median=%+.2f%% win=%.0f%% excess=%+.2f%% (%+.0f TWD/1M) t=%s %s years=%s' % (
            purpose, floor_name, hname, cls, st['events'], st['months'], st['mean_net_pct'], st['per_1m_net_twd'], st['median_net_pct'], st['win_rate'] * 100,
            st['mean_excess_pct'], st['per_1m_excess_twd'], 'NA' if st['t_excess_cluster_month'] is None else '%.2f' % st['t_excess_cluster_month'],
            json.dumps(c), json.dumps({y: (v['n'], round(v['net'], 2), round(v['excess'], 2)) for y, v in st['years'].items()})))
    primary = res.get('3|LIQ50|H20', {}).get('classification', 'NO_EVENTS')
    lines += ['PRIMARY (purpose 3, LIQ50, H20): ' + primary, 'COUNTS ' + json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'BUYBACK_DECISION.json').write_text(json.dumps({'study': 'BUYBACK_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'),
                                                           'primary': primary, 'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_buyback_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'BUYBACK_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
