#!/usr/bin/env python3
"""DEALER_HEDGE_V1 study (frozen preregistration): per-stock dealer hedging / proprietary net-buy ratio, next-open entry,
DT / H5 / H20 exits; plus a TX-futures foreign open-interest gate on the equal-weight liquid universe."""
import hashlib, json, math, sqlite3, statistics, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT.parent / 'inst_flow_v1'), str(ROOT.parent / 'revenue_v1'), str(ROOT.parents[1]), '/home/ubuntu/easystock']
import ifl_study as I  # noqa: E402  (frozen INST_FLOW_V1 helpers: costs, rolling ratio, ranking, event schedule)
import rev_study as R  # noqa: E402  (frozen criteria / classify / folds)

CUTOFF, FIRST_DAY = I.CUTOFF, I.FIRST_DAY
DEALER_DB = ROOT / 'data' / 'dealer.sqlite'
FUT_DB = ROOT / 'data' / 'futures.sqlite'
OUT = ROOT / 'output'
SIGNALS = ('DH5', 'DS5')
HORIZONS = I.HORIZONS
GATE_LAG, GATE_MIN_SIDE = 5, 15


def load():
    daily = sqlite3.connect('file:%s?mode=ro' % R.DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute("SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? AND day <= ? ORDER BY day",
                                             (FIRST_DAY, CUTOFF))]
    dix = {d: i for i, d in enumerate(sessions)}
    symbols = sorted(s for (s,) in daily.execute('SELECT DISTINCT symbol FROM bars WHERE day >= ? AND day <= ?', (FIRST_DAY, CUTOFF)) if R.COMMON.match(s))
    six = {s: j for j, s in enumerate(symbols)}
    shape = (len(sessions), len(symbols))
    O, C, REF = (np.full(shape, np.nan) for _ in range(3))
    V, A, HN, SN = (np.full(shape, np.nan, dtype=np.float32) for _ in range(4))
    for s, d, o, c, v, a, rf in daily.execute('SELECT symbol, day, open, close, volume, amount, reference FROM bars WHERE day >= ? AND day <= ?', (FIRST_DAY, CUTOFF)):
        i, j = dix.get(d), six.get(s)
        if i is None or j is None:
            continue
        O[i, j], C[i, j], V[i, j], A[i, j] = o, c, v, a
        REF[i, j] = rf if rf else np.nan
    logf = np.zeros(shape)
    for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day >= ? AND day <= ?', (FIRST_DAY, CUTOFF)):
        i, j = dix.get(d), six.get(s)
        if i is not None and j is not None and ref and ref > 0 and pc and pc > 0:
            logf[i, j] += math.log(pc / ref)
    daily.close()
    dl = sqlite3.connect('file:%s?mode=ro' % DEALER_DB, uri=True)
    for s, d, sf, hg in dl.execute('SELECT symbol, day, self_net, hedge_net FROM dealer WHERE consistent = 1 AND day <= ?', (CUTOFF,)):
        i, j = dix.get(d), six.get(s)
        if i is not None and j is not None:
            HN[i, j], SN[i, j] = hg, sf
    dl.close()
    fx = np.full(len(sessions), np.nan)
    fu = sqlite3.connect('file:%s?mode=ro' % FUT_DB, uri=True)
    for d, lo, so in fu.execute("SELECT day, long_oi, short_oi FROM tx_inst WHERE investor = 'foreign' AND day <= ?", (CUTOFF,)):
        i = dix.get(d)
        if i is not None:
            fx[i] = lo - so
    fu.close()
    return sessions, symbols, O, C, REF, V, A, HN, SN, np.cumsum(logf, axis=0), fx


def gate_series(net_oi, lag=GATE_LAG):
    """Change of foreign TX net open interest over `lag` sessions; NaN when either end is missing."""
    g = np.full(net_oi.shape, np.nan)
    g[lag:] = net_oi[lag:] - net_oi[:-lag]
    return g


def welch_t(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    return None if se == 0 else (sum(a) / len(a) - sum(b) / len(b)) / se


def gate_criteria(events):
    """events: dicts with fold, on (bool), universe (net %)."""
    on = [m['universe'] for m in events if m['on']]
    off = [m['universe'] for m in events if not m['on']]
    mon = sum(on) / len(on) if on else None
    moff = sum(off) / len(off) if off else None
    diff = None if mon is None or moff is None else mon - moff
    t = welch_t(on, off)
    folds = {}
    for f in R.FOLDS:
        a = [m['universe'] for m in events if m['fold'] == f and m['on']]
        b = [m['universe'] for m in events if m['fold'] == f and not m['on']]
        folds[f] = {'on': len(a), 'off': len(b), 'diff': (sum(a) / len(a) - sum(b) / len(b)) if a and b else None}
    c = {'GA': mon is not None and mon > 0,
         'GC': diff is not None and diff > 0 and t is not None and t >= 2.0,
         'GD': sum(1 for v in folds.values() if v['diff'] is not None and v['diff'] > 0) >= 4,
         'GG': len(on) >= GATE_MIN_SIDE and len(off) >= GATE_MIN_SIDE}
    return c, {'events': len(events), 'on': len(on), 'off': len(off), 'mean_on_pct': mon, 'mean_off_pct': moff,
               'diff_pct': diff, 't_diff': t, 'folds': folds}


def gate_classify(c):
    if not c['GG']:
        return 'INSUFFICIENT'
    if c['GA'] and c['GC'] and c['GD']:
        return 'STRONG'
    if c['GC'] and c['GD']:
        return 'RELATIVE_ONLY'
    if not c['GA'] and not c['GC']:
        return 'NO_EDGE'
    return 'WEAK'


def main():
    OUT.mkdir(exist_ok=True)
    sessions, symbols, O, C, REF, V, A, HN, SN, L, fx = load()
    CF = C.copy()
    for i in range(1, len(sessions)):
        miss = np.isnan(CF[i])
        CF[i, miss] = CF[i - 1, miss]
    sig = {'DH5': I.ratio_signal(HN, V), 'DS5': I.ratio_signal(SN, V)}
    gate = gate_series(fx)
    amt20 = I.rolling_sum(A.astype(np.float64), I.LOOK) / I.LOOK
    cnt = Counter()
    series = {(sg, h): [] for sg in SIGNALS for h, _, _ in HORIZONS}
    gates = {h: [] for h, _, _ in HORIZONS}
    quota = []
    for hname, n, every in HORIZONS:
        for i in I.event_days(len(sessions), every):
            e, x = i + 1, i + n
            if x >= len(sessions):
                cnt['DROP_EXIT_AFTER_CUTOFF:' + hname] += 1
                continue
            fillable = np.isfinite(O[e]) & (O[e] > 0) & ~(np.isfinite(REF[e]) & (O[e] >= I.LIMIT_UP * REF[e]))
            eligible = np.isfinite(amt20[i]) & (amt20[i] >= I.MIN_AMOUNT) & np.isfinite(C[i]) & (C[i] >= I.MIN_PRICE) & fillable
            ex_px = CF[x]
            ok = eligible & np.isfinite(ex_px)
            cnt['MISSING_EXIT:' + hname] += int((eligible & ~np.isfinite(ex_px)).sum())
            with np.errstate(invalid='ignore', divide='ignore'):
                gross = (ex_px * np.exp(L[x] - L[e]) / O[e] - 1) * 100.0
                net = gross - I.cost_pct_vec(O[e], ex_px, same_day=(hname == 'DT'))
            fold = int(sessions[e][:4])
            if ok.sum() >= 100 and np.isfinite(gate[i]):
                gates[hname].append({'date': sessions[i], 'fold': fold, 'on': bool(gate[i] > 0), 'gate': float(gate[i]),
                                     'n_universe': int(ok.sum()), 'universe': float(np.mean(net[ok]))})
            else:
                cnt['GATE_SKIPPED:' + hname] += 1
            for sg in SIGNALS:
                order = I.ranked(sig[sg][i], ok)
                if len(order) < 100:
                    cnt['THIN_EVENT:%s:%s' % (sg, hname)] += 1
                    continue
                k = math.ceil(len(order) * 0.1)
                uni = float(np.mean(net[order]))
                top, bottom = float(np.mean(net[order[:k]])), float(np.mean(net[order[-k:]]))
                series[(sg, hname)].append({'date': sessions[i], 'entry': sessions[e], 'exit': sessions[x], 'fold': fold,
                                            'n_universe': len(order), 'n_top': k, 'top': top, 'bottom': bottom, 'universe': uni, 'excess': top - uni})
                if hname == 'DT':
                    quota.append((sg, float(np.mean(net[order[:I.TOPK_QUOTA]])), uni))
    res, lines = {}, []
    for (sg, h), events in series.items():
        c, st = R.criteria(events)
        cls = R.classify(c)
        bot = [m['bottom'] - m['universe'] for m in events]
        st['mean_bottom_excess_pct'] = sum(bot) / len(bot) if bot else None
        st['mean_bottom_net_pct'] = sum(m['bottom'] for m in events) / len(events) if events else None
        st['mean_universe_net_pct'] = sum(m['universe'] for m in events) / len(events) if events else None
        st['per_1m_top_net_twd'] = None if st['mean_top_net_pct'] is None else st['mean_top_net_pct'] * 10000
        st['per_1m_excess_twd'] = None if st['mean_excess_pct'] is None else st['mean_excess_pct'] * 10000
        res['%s|%s' % (sg, h)] = {'classification': cls, 'criteria': c, 'stats': st, 'series': events}
        lines.append('%s %-3s %-13s events=%d top_net=%+.3f%% (%+.0f TWD/1M) universe=%+.3f%% excess=%+.3f%% (%+.0f TWD/1M) t=%s bottom_net=%+.3f%% bottom_excess=%+.3f%% %s folds=%s' % (
            sg, h, cls, st['months'], st['mean_top_net_pct'] or 0, st['per_1m_top_net_twd'] or 0, st['mean_universe_net_pct'] or 0,
            st['mean_excess_pct'] or 0, st['per_1m_excess_twd'] or 0, 'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'],
            st['mean_bottom_net_pct'] or 0, st['mean_bottom_excess_pct'] or 0, json.dumps(c),
            json.dumps({f: (v['months'], None if v['top'] is None else round(v['top'], 3), None if v['excess'] is None else round(v['excess'], 3))
                        for f, v in st['folds'].items()})))
    for sg in SIGNALS:
        q = [t for s, t, _ in quota if s == sg]
        u = [t for s, _, t in quota if s == sg]
        if q:
            lines.append('QUOTA_TOP3_DT %s days=%d mean_net=%+.3f%% (%+.0f TWD per day on 1M) universe=%+.3f%%' % (
                sg, len(q), sum(q) / len(q), sum(q) / len(q) * 10000, sum(u) / len(u)))
    for h, events in gates.items():
        c, st = gate_criteria(events)
        cls = gate_classify(c)
        res['FX5_GATE|%s' % h] = {'classification': cls, 'criteria': c, 'stats': st, 'series': events}
        lines.append('FX5_GATE %-3s %-13s events=%d on=%d off=%d on_net=%+.3f%% (%+.0f TWD/1M) off_net=%+.3f%% diff=%+.3f%% t=%s %s folds=%s' % (
            h, cls, st['events'], st['on'], st['off'], st['mean_on_pct'] or 0, (st['mean_on_pct'] or 0) * 10000, st['mean_off_pct'] or 0,
            st['diff_pct'] or 0, 'NA' if st['t_diff'] is None else '%.2f' % st['t_diff'], json.dumps(c),
            json.dumps({f: (v['on'], v['off'], None if v['diff'] is None else round(v['diff'], 3)) for f, v in st['folds'].items()})))
    family = 'STRONG_CANDIDATE' if any(v['classification'] == 'STRONG' for v in res.values()) else 'NO_STRONG'
    lines += ['FAMILY %s' % family, 'COUNTS %s' % json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'DEALER_HEDGE_DECISION.json').write_text(json.dumps(
        {'study': 'DEALER_HEDGE_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'), 'family': family,
         'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_dealer_hedge_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'DEALER_HEDGE_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
