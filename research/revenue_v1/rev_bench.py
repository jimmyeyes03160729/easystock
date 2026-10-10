#!/usr/bin/env python3
"""REVENUE_BENCH_0050_V1: descriptive comparison of the sealed revenue event portfolios with 0050 over the same windows.

Reads the per-event series already written by REVENUE_DRIFT_V1 (S2_SUR decile H5/H20) and REVENUE_SHORT_V1 (decile and TOP10
H10/H15), and computes the open(E)-to-close(X) dividend- and split-adjusted net return of 0050 for each event window.
No signal, universe or horizon is changed; no price after 2026-10-02 is used. Post-hoc and descriptive, no pass/fail.
"""
import hashlib, json, math, sqlite3, sys, tarfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import etf0050 as E  # noqa: E402

OUT = ROOT / 'output_bench'
SOURCES = (('S2_SUR|H5', ROOT / 'output' / 'REVENUE_DRIFT_DECISION.json', 'DEC', 'H5'),
           ('S2_SUR|H20', ROOT / 'output' / 'REVENUE_DRIFT_DECISION.json', 'DEC', 'H20'),
           ('DEC|H10', ROOT / 'output_short' / 'REVENUE_SHORT_DECISION.json', 'DEC', 'H10'),
           ('DEC|H15', ROOT / 'output_short' / 'REVENUE_SHORT_DECISION.json', 'DEC', 'H15'),
           ('TOP10|H10', ROOT / 'output_short' / 'REVENUE_SHORT_DECISION.json', 'TOP10', 'H10'),
           ('TOP10|H15', ROOT / 'output_short' / 'REVENUE_SHORT_DECISION.json', 'TOP10', 'H15'))
CUTOFF = '2026-10-02'


def etf_net(days, exdiv, entry, exit_):
    """Net percent return of 0050 from the open of entry to the close of exit_ (fees + 0.1% ETF tax), or None."""
    g = E.open_to_close_return(days, exdiv, entry, exit_)
    if g is None:
        return None
    by = {d[0]: d for d in days}
    return g * 100 - E.cost_pct(by[entry][1], by[exit_][2])


def t_stat(xs):
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else None


def compare(events, days, exdiv):
    rows = []
    for ev in events:
        b = etf_net(days, exdiv, ev['entry'], ev['exit'])
        if b is not None and ev['exit'] <= CUTOFF:
            rows.append({'month': ev['month'], 'year': int(ev['entry'][:4]), 'net': ev['top'], 'etf': b, 'diff': ev['top'] - b, 'universe': ev['universe']})
    n = len(rows)
    if not n:
        return None
    mean = lambda k: sum(r[k] for r in rows) / n
    years = {}
    for y in sorted({r['year'] for r in rows}):
        sub = [r for r in rows if r['year'] == y]
        years[y] = {'n': len(sub), 'net': sum(r['net'] for r in sub) / len(sub), 'etf': sum(r['etf'] for r in sub) / len(sub), 'diff': sum(r['diff'] for r in sub) / len(sub)}
    cum = lambda k: (math.prod(1 + r[k] / 100 for r in rows) - 1) * 100
    return {'compounded_strategy_pct': cum('net'), 'compounded_etf_same_windows_pct': cum('etf'), 'events': n, 'mean_net_pct': mean('net'), 'mean_etf_pct': mean('etf'), 'mean_universe_pct': mean('universe'), 'mean_diff_pct': mean('diff'),
            't_diff': t_stat([r['diff'] for r in rows]), 'beat_etf': sum(1 for r in rows if r['diff'] > 0), 'years': years,
            'per_1m_net_twd': mean('net') * 10000, 'per_1m_etf_twd': mean('etf') * 10000, 'per_1m_diff_twd': mean('diff') * 10000}


def main():
    OUT.mkdir(exist_ok=True)
    days, exdiv = E.load()
    days = [d for d in days if d[0] <= CUTOFF]
    res, lines = {}, []
    for key, path, portfolio, hold in SOURCES:
        data = json.loads(path.read_text())['results']
        events = data.get(key, {}).get('series')
        if events is None:
            events = data['%s|%s' % (portfolio, hold)]['series']
        st = compare(events, days, exdiv)
        if not st:
            continue
        res['%s|%s' % (portfolio, hold)] = st
        lines.append('%-5s %-3s compounded over event windows: strategy %+.0f%% vs 0050 in the same windows %+.0f%%' % (portfolio, hold, st['compounded_strategy_pct'], st['compounded_etf_same_windows_pct']))
        lines.append('%-5s %-3s events=%d strategy=%+.2f%% (%+.0f TWD/1M) 0050=%+.2f%% (%+.0f TWD/1M) universe=%+.2f%% diff_vs_0050=%+.2f%% (%+.0f TWD/1M) t=%s beat_0050=%d/%d years=%s' % (
            portfolio, hold, st['events'], st['mean_net_pct'], st['per_1m_net_twd'], st['mean_etf_pct'], st['per_1m_etf_twd'], st['mean_universe_pct'],
            st['mean_diff_pct'], st['per_1m_diff_twd'], 'NA' if st['t_diff'] is None else '%.2f' % st['t_diff'], st['beat_etf'], st['events'],
            json.dumps({y: (v['n'], round(v['net'], 2), round(v['etf'], 2), round(v['diff'], 2)) for y, v in st['years'].items()})))
    first, last = next(d for d in days if d[0] >= '2022-02-01'), days[-1]
    bh = E.open_to_close_return(days, exdiv, first[0], last[0])
    lines.append('0050 buy-and-hold total return %s open -> %s close: %+.1f%% (adjusted for dividends and the split; no fees)' % (first[0], last[0], bh * 100))
    lines.append('FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false')
    (OUT / 'REVENUE_BENCH_DECISION.json').write_text(json.dumps({'study': 'REVENUE_BENCH_0050_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'),
                                                                 'buy_and_hold_0050_pct': bh * 100, 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_revenue_bench_0050_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'REVENUE_BENCH_DECISION.json', OUT / 'FINAL_LINES.txt', ROOT / 'rev_bench.py', ROOT / 'etf0050.py']:
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
