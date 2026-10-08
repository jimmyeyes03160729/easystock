#!/usr/bin/env python3
"""REVENUE_DRIFT_V1 study (frozen preregistration): top-decile revenue surprise, post-deadline LONG returns."""
import hashlib, json, math, re, sqlite3, statistics, sys, tarfile
from bisect import bisect_left
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT.parents[1]), '/home/ubuntu/easystock']
import paper_execution as pe  # noqa: E402

CUTOFF = '2026-10-02'
DAILY_DB = '/home/ubuntu/easystock-learning-data/rebound/market-daily.sqlite'
REV_DB = ROOT / 'data' / 'revenue.sqlite'
OUT = ROOT / 'output'
FIRST_EVENT, LAST_EVENT = '2022-01', '2026-08'
HORIZONS = (('DT', 1), ('H5', 5), ('H20', 20))
SIGNALS = ('S1_YOY', 'S2_SUR')
LOOKBACK, MIN_AMOUNT, MIN_PRICE, SHARES = 20, 50_000_000, 10.0, 1000
FOLDS = (2022, 2023, 2024, 2025, 2026)
COMMON = re.compile(r'^[1-9]\d{3}$')


def add_months(month, k):
    y, m = map(int, month.split('-'))
    n = y * 12 + (m - 1) + k
    return '%04d-%02d' % (n // 12, n % 12 + 1)


def entry_session(sessions, month):
    """E(M): the session after the first session on or after the 10th of month M+1."""
    i = bisect_left(sessions, add_months(month, 1) + '-10')
    return sessions[i + 1] if i + 1 < len(sessions) else None


def growth(rev, last_year):
    return math.log(rev / last_year) if rev and last_year and rev > 0 and last_year > 0 else None


def yoy(rev, last_year):
    return rev / last_year - 1 if rev and last_year and rev > 0 and last_year > 0 else None


def sur(history, g):
    """Standardized unexpected revenue vs the previous 12 monthly log growths (population std)."""
    if g is None or len(history) != 12 or any(x is None for x in history):
        return None
    m = sum(history) / 12
    sd = math.sqrt(sum((x - m) ** 2 for x in history) / 12)
    return (g - m) / sd if sd > 1e-9 else None


def cost_pct(entry, exit_, same_day):
    e, x = Decimal(str(entry)) * SHARES, Decimal(str(exit_)) * SHARES
    return float((pe.fee(e) + pe.fee(x) + pe.tax(x, same_day=same_day)) / e * 100)


def deciles(scores):
    """scores: {symbol: value}. Returns (top, bottom) symbol lists of ceil(10%) each, ties broken by symbol."""
    ranked = sorted(scores, key=lambda s: (-scores[s], s))
    k = math.ceil(len(ranked) * 0.1)
    return ranked[:k], ranked[-k:] if k else []


def classify(c):
    if not c['G']:
        return 'INSUFFICIENT'
    if c['A'] and c['B'] and c['C'] and c['D']:
        return 'STRONG'
    if c['C'] and c['D']:
        return 'RELATIVE_ONLY'
    if not c['A'] and not c['C']:
        return 'NO_EDGE'
    return 'WEAK'


def criteria(months):
    """months: list of dicts with fold, top, excess, n_top."""
    n = len(months)
    top = [m['top'] for m in months]
    exc = [m['excess'] for m in months]
    mean_top = sum(top) / n if n else None
    mean_exc = sum(exc) / n if n else None
    sd = statistics.stdev(exc) if n > 1 else 0.0
    t = mean_exc / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None
    fold = {}
    for f in FOLDS:
        ms = [m for m in months if m['fold'] == f]
        fold[f] = {'months': len(ms), 'top': sum(m['top'] for m in ms) / len(ms) if ms else None,
                   'excess': sum(m['excess'] for m in ms) / len(ms) if ms else None}
    c = {'A': bool(n) and mean_top > 0,
         'B': sum(1 for f in FOLDS if fold[f]['top'] is not None and fold[f]['top'] > 0) >= 4,
         'C': bool(n) and mean_exc > 0 and t is not None and t >= 2.0,
         'D': sum(1 for f in FOLDS if fold[f]['excess'] is not None and fold[f]['excess'] > 0) >= 4,
         'G': n >= 40 and (sum(m['n_top'] for m in months) / n) >= 20}
    return c, {'months': n, 'mean_top_net_pct': mean_top, 'mean_excess_pct': mean_exc, 't_excess': t, 'folds': fold}


def load_revenue():
    db = sqlite3.connect('file:%s?mode=ro' % REV_DB, uri=True)
    rows = db.execute('SELECT symbol, month, revenue, last_year FROM revenue WHERE month <= ?', (LAST_EVENT,)).fetchall()
    db.close()
    rev = {}
    for s, m, r, ly in rows:
        rev.setdefault(s, {})[m] = (r, ly)
    return rev


def signals_for(rev, month):
    out = {'S1_YOY': {}, 'S2_SUR': {}}
    for s, by in rev.items():
        if month not in by:
            continue
        r, ly = by[month]
        y = yoy(r, ly)
        if y is None:
            continue
        out['S1_YOY'][s] = y
        hist = [growth(*by[add_months(month, -k)]) if add_months(month, -k) in by else None for k in range(1, 13)]
        v = sur(hist, growth(r, ly))
        if v is not None:
            out['S2_SUR'][s] = v
    return out


def main():
    OUT.mkdir(exist_ok=True)
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day <= ? ORDER BY day", (CUTOFF,))]
    rev = load_revenue()
    cnt = Counter()
    series = {(sg, h): [] for sg in SIGNALS for h, _ in HORIZONS}
    month = FIRST_EVENT
    while month <= LAST_EVENT:
        E = entry_session(sessions, month)
        if E is None or E > CUTOFF:
            cnt['EVENT_MONTH_NO_ENTRY'] += 1
            month = add_months(month, 1)
            continue
        iE = sessions.index(E)
        lo = sessions[max(0, iE - LOOKBACK - 20)]
        hi = sessions[min(len(sessions) - 1, iE + 19)]
        bars = {}
        for s, d, o, c, a in daily.execute('SELECT symbol, day, open, close, amount FROM bars WHERE day BETWEEN ? AND ?', (lo, hi)):
            if COMMON.match(s):
                bars.setdefault(s, {})[d] = (o, c, a)
        ex = {}
        for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day > ? AND day <= ?', (E, hi)):
            if ref and ref > 0 and pc and pc > 0:
                ex.setdefault(s, []).append((d, pc / ref))
        eligible = set()
        for s, by in bars.items():
            if E not in by:
                continue
            prior = sorted(d for d in by if d < E)[-LOOKBACK:]
            if len(prior) < LOOKBACK or sum(by[d][2] for d in prior) / LOOKBACK < MIN_AMOUNT or by[prior[-1]][1] < MIN_PRICE:
                continue
            eligible.add(s)
        sig = signals_for(rev, month)
        fold = int(E[:4])
        for h, n in HORIZONS:
            if iE + n - 1 >= len(sessions):
                cnt['DROP_EXIT_AFTER_CUTOFF:' + h] += 1
                continue
            X = sessions[iE + n - 1]
            ret = {}
            for s in eligible:
                by = bars[s]
                entry = by[E][0]
                if not entry or entry <= 0:
                    continue
                if X in by:
                    exit_px = by[X][1]
                else:
                    before = [d for d in by if d < X]
                    exit_px = by[max(before)][1]
                    cnt['MISSING_EXIT:' + h] += 1
                factor = 1.0
                for d, f in ex.get(s, ()):
                    if d <= X and h != 'DT':
                        factor *= f
                gross = (exit_px * factor / entry - 1) * 100
                ret[s] = gross - cost_pct(entry, exit_px, same_day=(h == 'DT'))
            for sg in SIGNALS:
                scores = {s: v for s, v in sig[sg].items() if s in ret}
                if len(scores) < 10:
                    cnt['THIN_MONTH:%s:%s' % (sg, h)] += 1
                    continue
                top, bottom = deciles(scores)
                uni = sum(ret[s] for s in scores) / len(scores)
                t = sum(ret[s] for s in top) / len(top)
                b = sum(ret[s] for s in bottom) / len(bottom)
                series[(sg, h)].append({'month': month, 'entry': E, 'exit': X, 'fold': fold, 'n_universe': len(scores),
                                        'n_top': len(top), 'top': t, 'bottom': b, 'universe': uni, 'excess': t - uni})
        cnt['EVENT_MONTHS'] += 1
        month = add_months(month, 1)
    daily.close()
    res, lines = {}, []
    for (sg, h), months in series.items():
        c, st = criteria(months)
        cls = classify(c)
        bot = [m['bottom'] - m['universe'] for m in months]
        st['mean_bottom_excess_pct'] = sum(bot) / len(bot) if bot else None
        st['mean_universe_net_pct'] = sum(m['universe'] for m in months) / len(months) if months else None
        res['%s|%s' % (sg, h)] = {'classification': cls, 'criteria': c, 'stats': st, 'series': months}
        lines.append('%s %-3s %-12s months=%d top_net=%+.3f%% universe=%+.3f%% excess=%+.3f%% t=%s bottom_excess=%+.3f%% %s folds=%s' % (
            sg, h, cls, st['months'], st['mean_top_net_pct'] or 0, st['mean_universe_net_pct'] or 0, st['mean_excess_pct'] or 0,
            'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'], st['mean_bottom_excess_pct'] or 0,
            json.dumps(c), json.dumps({f: (v['months'], None if v['top'] is None else round(v['top'], 3),
                                           None if v['excess'] is None else round(v['excess'], 3)) for f, v in st['folds'].items()})))
    family = 'STRONG_CANDIDATE' if any(v['classification'] == 'STRONG' for v in res.values()) else 'NO_STRONG'
    lines += ['FAMILY %s' % family, 'COUNTS %s' % json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'REVENUE_DRIFT_DECISION.json').write_text(json.dumps(
        {'study': 'REVENUE_DRIFT_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'), 'family': family,
         'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_revenue_drift_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'REVENUE_DRIFT_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
