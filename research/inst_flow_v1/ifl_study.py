#!/usr/bin/env python3
"""INST_FLOW_V1 study (frozen preregistration): per-stock institutional net-buy ratio, next-open entry, DT / H5 / H20 exits."""
import hashlib, json, math, sqlite3, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT.parent / 'revenue_v1'), str(ROOT.parents[1]), '/home/ubuntu/easystock']
import rev_study as R  # noqa: E402  (frozen helpers: criteria, classify, FOLDS, COMMON, DAILY_DB, MIN_AMOUNT, MIN_PRICE)

CUTOFF = '2026-10-02'
FIRST_DAY = '2022-01-03'
INST_DB = ROOT / 'data' / 'inst.sqlite'
OUT = ROOT / 'output'
SIGNALS = ('FI5', 'IT5')
HORIZONS = (('DT', 1, 1), ('H5', 5, 5), ('H20', 20, 20))     # name, hold sessions, rebalance every n sessions
WINDOW, LOOK, SHARES, LIMIT_UP = 5, 20, 1000, 1.09
MIN_AMOUNT, MIN_PRICE = R.MIN_AMOUNT, R.MIN_PRICE
TOPK_QUOTA = 3


def fee_vec(amount):
    return np.maximum(20.0, np.floor(amount * 0.001425 * 0.28 + 0.5))


def tax_vec(amount, same_day):
    return np.floor(amount * (0.0015 if same_day else 0.003) + 0.5)


def cost_pct_vec(entry, exit_, same_day):
    ea, xa = entry * SHARES, exit_ * SHARES
    return (fee_vec(ea) + fee_vec(xa) + tax_vec(xa, same_day)) / ea * 100.0


def rolling_sum(m, k):
    """Sum of rows t-k+1..t; NaN unless all k rows exist. Rows before k-1 are NaN."""
    out = np.full(m.shape, np.nan)
    acc = m[k - 1:].copy()
    for j in range(1, k):
        acc = acc + m[k - 1 - j:m.shape[0] - j]
    out[k - 1:] = acc
    return out


def ratio_signal(net, vol, k=WINDOW):
    """k-day net buy divided by k-day volume; NaN when any day is missing or volume is 0."""
    with np.errstate(invalid='ignore', divide='ignore'):
        v = rolling_sum(vol, k)
        r = rolling_sum(net, k) / np.where(v > 0, v, np.nan)
    return r


def ranked(scores, mask):
    """Indices of masked symbols ordered by descending score, ties by column index (= symbol order)."""
    idx = np.flatnonzero(mask & np.isfinite(scores))
    return idx[np.lexsort((idx, -scores[idx]))]


def event_days(n_sessions, every):
    return [i for i in range(LOOK - 1, n_sessions - 1) if (i - (LOOK - 1)) % every == 0]


def load():
    daily = sqlite3.connect('file:%s?mode=ro' % R.DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute("SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? AND day <= ? ORDER BY day",
                                             (FIRST_DAY, CUTOFF))]
    dix = {d: i for i, d in enumerate(sessions)}
    symbols = sorted(s for (s,) in daily.execute('SELECT DISTINCT symbol FROM bars WHERE day >= ? AND day <= ?', (FIRST_DAY, CUTOFF)) if R.COMMON.match(s))
    six = {s: j for j, s in enumerate(symbols)}
    shape = (len(sessions), len(symbols))
    O, C, REF = (np.full(shape, np.nan) for _ in range(3))
    V, A, FN, TN = (np.full(shape, np.nan, dtype=np.float32) for _ in range(4))
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
    inst = sqlite3.connect('file:%s?mode=ro' % INST_DB, uri=True)
    for s, d, f, t in inst.execute('SELECT symbol, day, foreign_net, trust_net FROM inst'):
        i, j = dix.get(d), six.get(s)
        if i is not None and j is not None:
            FN[i, j], TN[i, j] = f, t
    inst.close()
    return sessions, symbols, O, C, REF, V, A, FN, TN, np.cumsum(logf, axis=0)


def main():
    OUT.mkdir(exist_ok=True)
    sessions, symbols, O, C, REF, V, A, FN, TN, L = load()
    CF = C.copy()
    for i in range(1, len(sessions)):
        miss = np.isnan(CF[i])
        CF[i, miss] = CF[i - 1, miss]
    sig = {'FI5': ratio_signal(FN, V), 'IT5': ratio_signal(TN, V)}
    amt20 = rolling_sum(A.astype(np.float64), LOOK) / LOOK
    cnt = Counter()
    series = {(sg, h): [] for sg in SIGNALS for h, _, _ in HORIZONS}
    quota = []
    for hname, n, every in HORIZONS:
        for i in event_days(len(sessions), every):
            e, x = i + 1, i + n
            if x >= len(sessions):
                cnt['DROP_EXIT_AFTER_CUTOFF:' + hname] += 1
                continue
            fillable = np.isfinite(O[e]) & (O[e] > 0) & ~(np.isfinite(REF[e]) & (O[e] >= LIMIT_UP * REF[e]))
            eligible = np.isfinite(amt20[i]) & (amt20[i] >= MIN_AMOUNT) & np.isfinite(C[i]) & (C[i] >= MIN_PRICE) & fillable
            ex_px = CF[x]
            ok = eligible & np.isfinite(ex_px)
            cnt['MISSING_EXIT:' + hname] += int((eligible & ~np.isfinite(ex_px)).sum())
            with np.errstate(invalid='ignore', divide='ignore'):
                gross = (ex_px * np.exp(L[x] - L[e]) / O[e] - 1) * 100.0
                net = gross - cost_pct_vec(O[e], ex_px, same_day=(hname == 'DT'))
            fold = int(sessions[e][:4])
            for sg in SIGNALS:
                order = ranked(sig[sg][i], ok)
                if len(order) < 100:
                    cnt['THIN_EVENT:%s:%s' % (sg, hname)] += 1
                    continue
                k = math.ceil(len(order) * 0.1)
                uni = float(np.mean(net[order]))
                top, bottom = float(np.mean(net[order[:k]])), float(np.mean(net[order[-k:]]))
                series[(sg, hname)].append({'date': sessions[i], 'entry': sessions[e], 'exit': sessions[x], 'fold': fold,
                                            'n_universe': len(order), 'n_top': k, 'top': top, 'bottom': bottom, 'universe': uni, 'excess': top - uni})
                if hname == 'DT':
                    quota.append((sg, fold, float(np.mean(net[order[:TOPK_QUOTA]])), uni))
    res, lines = {}, []
    for (sg, h), events in series.items():
        c, st = R.criteria(events)
        cls = R.classify(c)
        bot = [m['bottom'] - m['universe'] for m in events]
        st['mean_bottom_excess_pct'] = sum(bot) / len(bot) if bot else None
        st['mean_universe_net_pct'] = sum(m['universe'] for m in events) / len(events) if events else None
        st['per_1m_top_net_twd'] = None if st['mean_top_net_pct'] is None else st['mean_top_net_pct'] * 10000
        st['per_1m_excess_twd'] = None if st['mean_excess_pct'] is None else st['mean_excess_pct'] * 10000
        res['%s|%s' % (sg, h)] = {'classification': cls, 'criteria': c, 'stats': st, 'series': events}
        lines.append('%s %-3s %-13s events=%d top_net=%+.3f%% (%+.0f TWD/1M) universe=%+.3f%% excess=%+.3f%% (%+.0f TWD/1M) t=%s bottom_excess=%+.3f%% %s folds=%s' % (
            sg, h, cls, st['months'], st['mean_top_net_pct'] or 0, st['per_1m_top_net_twd'] or 0, st['mean_universe_net_pct'] or 0,
            st['mean_excess_pct'] or 0, st['per_1m_excess_twd'] or 0, 'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'],
            st['mean_bottom_excess_pct'] or 0, json.dumps(c), json.dumps({f: (v['months'], None if v['top'] is None else round(v['top'], 3),
                                                                                  None if v['excess'] is None else round(v['excess'], 3)) for f, v in st['folds'].items()})))
    for sg in SIGNALS:
        q = [t for s, _, t, _ in quota if s == sg]
        u = [t for s, _, _, t in quota if s == sg]
        if q:
            lines.append('QUOTA_TOP3_DT %s days=%d mean_net=%+.3f%% (%+.0f TWD per day on 1M) universe=%+.3f%%' % (
                sg, len(q), sum(q) / len(q), sum(q) / len(q) * 10000, sum(u) / len(u)))
    family = 'STRONG_CANDIDATE' if any(v['classification'] == 'STRONG' for v in res.values()) else 'NO_STRONG'
    lines += ['FAMILY %s' % family, 'COUNTS %s' % json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'INST_FLOW_DECISION.json').write_text(json.dumps(
        {'study': 'INST_FLOW_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'), 'family': family,
         'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_inst_flow_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'INST_FLOW_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
