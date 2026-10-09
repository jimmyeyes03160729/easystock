#!/usr/bin/env python3
"""REVENUE_SHORT_V1 (preregistered): the monthly revenue surprise (S2_SUR) held 15 days or less.

Same events, universe, signal, entry and costs as REVENUE_DRIFT_V1 (rev_study.py), with three changes fixed in the
preregistration: horizons H10 (primary, ~14 calendar days) and H15; limit-up opens are unfillable (excluded from the
decile and the baseline, an empty slot in TOP10); and a 10-name portfolio (TOP10) sized for 1,000,000 TWD of capital.
"""
import hashlib, json, math, sqlite3, statistics, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import rev_study as R  # noqa: E402  (frozen helpers)

HORIZONS = (('H10', 10), ('H15', 15))
TOP_N = 10
LIMIT_UP = 1.09
SLIP_BPS = 20
OUT = ROOT / 'output_short'


def portfolios(scores, ret, limit_up):
    """scores: {symbol: SUR} ranked before the open; ret: {symbol: net %}; limit_up: symbols that opened >= 1.09 x reference.

    DEC is the top decile of all scored names minus the unfillable ones (equal weight over the filled names). TOP10 is
    the 10 highest scores; an unfillable name leaves its tenth of the capital in cash (0%). The baseline is every
    fillable scored name.
    """
    top, _ = R.deciles(scores)
    filled = [s for s in scores if s not in limit_up]
    dec = [s for s in top if s not in limit_up]
    ten = sorted(scores, key=lambda s: (-scores[s], s))[:TOP_N]
    ten_filled = [s for s in ten if s not in limit_up]
    if not filled or not dec:
        return None
    return {'universe': sum(ret[s] for s in filled) / len(filled), 'n_universe': len(filled),
            'dec': sum(ret[s] for s in dec) / len(dec), 'n_dec': len(dec),
            'top10': sum(ret[s] for s in ten_filled) / TOP_N, 'n_top10': len(ten_filled), 'top10_names': ten}


def criteria(months, min_size):
    """REVENUE_DRIFT_V1 criteria A-D; G = >= 40 months and mean portfolio size >= min_size."""
    n = len(months)
    if not n:
        return {k: False for k in 'ABCDG'}, {'months': 0}
    top = [m['top'] for m in months]
    exc = [m['excess'] for m in months]
    mean_top, mean_exc = sum(top) / n, sum(exc) / n
    sd = statistics.stdev(exc) if n > 1 else 0.0
    t = mean_exc / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None
    fold = {}
    for f in R.FOLDS:
        ms = [m for m in months if m['fold'] == f]
        fold[f] = {'months': len(ms), 'top': sum(m['top'] for m in ms) / len(ms) if ms else None,
                   'excess': sum(m['excess'] for m in ms) / len(ms) if ms else None}
    c = {'A': mean_top > 0,
         'B': sum(1 for f in R.FOLDS if fold[f]['top'] is not None and fold[f]['top'] > 0) >= 4,
         'C': mean_exc > 0 and t is not None and t >= 2.0,
         'D': sum(1 for f in R.FOLDS if fold[f]['excess'] is not None and fold[f]['excess'] > 0) >= 4,
         'G': n >= 40 and sum(m['n'] for m in months) / n >= min_size}
    srt = sorted(top)
    st = {'months': n, 'mean_top_net_pct': mean_top, 'mean_excess_pct': mean_exc, 't_excess': t,
          'win_months': sum(1 for x in top if x > 0), 'worst_month_pct': srt[0], 'p10_month_pct': srt[int(0.1 * (n - 1))],
          'median_month_pct': statistics.median(top), 'mean_top_net_slip_pct': mean_top - 2 * SLIP_BPS / 100.0,
          'twd_per_1m_per_event': round(mean_top * 10000), 'folds': fold}
    return c, st


def decide(res):
    """Homepage rule frozen in the preregistration."""
    horizon = 'H10' if res['DEC|H10']['classification'] == 'STRONG' else 'H5'
    t10 = res['TOP10|H10']
    top10_ok = bool(t10['criteria']['A'] and t10['criteria']['B'] and (t10['stats'].get('mean_excess_pct') or 0) > 0)
    return {'horizon': horizon, 'list': 'TOP10' if horizon == 'H10' and top10_ok else 'DECILE'}


def main():
    OUT.mkdir(exist_ok=True)
    daily = sqlite3.connect('file:%s?mode=ro' % R.DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day <= ? ORDER BY day", (R.CUTOFF,))]
    rev = R.load_revenue()
    cnt = Counter()
    series = {(p, h): [] for p in ('DEC', 'TOP10') for h, _ in HORIZONS}
    month = R.FIRST_EVENT
    while month <= R.LAST_EVENT:
        E = R.entry_session(sessions, month)
        if E is None or E > R.CUTOFF:
            cnt['EVENT_MONTH_NO_ENTRY'] += 1
            month = R.add_months(month, 1)
            continue
        iE = sessions.index(E)
        lo = sessions[max(0, iE - R.LOOKBACK - 20)]
        hi = sessions[min(len(sessions) - 1, iE + max(n for _, n in HORIZONS) - 1)]
        bars = {}
        for s, d, o, c, a, rf in daily.execute('SELECT symbol, day, open, close, amount, reference FROM bars WHERE day BETWEEN ? AND ?', (lo, hi)):
            if R.COMMON.match(s):
                bars.setdefault(s, {})[d] = (o, c, a, rf)
        ex = {}
        for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day > ? AND day <= ?', (E, hi)):
            if ref and ref > 0 and pc and pc > 0:
                ex.setdefault(s, []).append((d, pc / ref))
        eligible = set()
        for s, by in bars.items():
            if E not in by:
                continue
            prior = sorted(d for d in by if d < E)[-R.LOOKBACK:]
            if len(prior) < R.LOOKBACK or sum(by[d][2] for d in prior) / R.LOOKBACK < R.MIN_AMOUNT or by[prior[-1]][1] < R.MIN_PRICE:
                continue
            eligible.add(s)
        sur = R.signals_for(rev, month)['S2_SUR']
        fold = int(E[:4])
        for h, n in HORIZONS:
            if iE + n - 1 >= len(sessions):
                cnt['DROP_EXIT_AFTER_CUTOFF:' + h] += 1
                continue
            X = sessions[iE + n - 1]
            ret, limit_up = {}, set()
            for s in eligible:
                by = bars[s]
                entry = by[E][0]
                if not entry or entry <= 0:
                    continue
                if by[E][3] and entry >= by[E][3] * LIMIT_UP:
                    limit_up.add(s)
                if X in by:
                    exit_px = by[X][1]
                else:
                    exit_px = by[max(d for d in by if d < X)][1]
                    cnt['MISSING_EXIT:' + h] += 1
                factor = 1.0
                for d, f in ex.get(s, ()):
                    if d <= X:
                        factor *= f
                ret[s] = (exit_px * factor / entry - 1) * 100 - R.cost_pct(entry, exit_px, same_day=False)
            scores = {s: v for s, v in sur.items() if s in ret}
            if len(scores) < 10:
                cnt['THIN_MONTH:' + h] += 1
                continue
            p = portfolios(scores, ret, limit_up)
            if p is None:
                cnt['EMPTY_MONTH:' + h] += 1
                continue
            cnt['LIMITUP_OPEN_IN_DECILE:' + h] += len(R.deciles(scores)[0]) - p['n_dec']
            cnt['LIMITUP_OPEN_IN_TOP10:' + h] += TOP_N - p['n_top10']
            base = {'month': month, 'entry': E, 'exit': X, 'fold': fold, 'universe': p['universe'], 'n_universe': p['n_universe']}
            series[('DEC', h)].append(dict(base, top=p['dec'], n=p['n_dec'], excess=p['dec'] - p['universe']))
            series[('TOP10', h)].append(dict(base, top=p['top10'], n=p['n_top10'], excess=p['top10'] - p['universe'],
                                             names=p['top10_names']))
        cnt['EVENT_MONTHS'] += 1
        month = R.add_months(month, 1)
    daily.close()
    res, lines = {}, []
    for (pf, h), months in series.items():
        c, st = criteria(months, 20 if pf == 'DEC' else 8)
        cls = R.classify(c)
        st['mean_universe_net_pct'] = sum(m['universe'] for m in months) / len(months) if months else None
        res['%s|%s' % (pf, h)] = {'classification': cls, 'criteria': c, 'stats': st, 'series': months}
        lines.append('S2_SUR %-5s %-3s %-12s months=%d net=%+.3f%% universe=%+.3f%% excess=%+.3f%% t=%s win=%d/%d worst=%+.2f%% '
                     'p10=%+.2f%% slip20=%+.3f%% per1M=%+d TWD/event %s folds=%s' % (
                         pf, h, cls, st['months'], st['mean_top_net_pct'], st['mean_universe_net_pct'], st['mean_excess_pct'],
                         'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'], st['win_months'], st['months'],
                         st['worst_month_pct'], st['p10_month_pct'], st['mean_top_net_slip_pct'], st['twd_per_1m_per_event'],
                         json.dumps(c), json.dumps({f: (v['months'], None if v['top'] is None else round(v['top'], 3),
                                                        None if v['excess'] is None else round(v['excess'], 3))
                                                    for f, v in st['folds'].items()})))
    decision = decide(res)
    lines += ['HOMEPAGE %s' % json.dumps(decision), 'COUNTS %s' % json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false REBOUND_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'REVENUE_SHORT_DECISION.json').write_text(json.dumps(
        {'study': 'REVENUE_SHORT_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'), 'homepage': decision,
         'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_revenue_short_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'REVENUE_SHORT_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
