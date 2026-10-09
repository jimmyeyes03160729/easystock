#!/usr/bin/env python3
"""OPEN_FADE_V1 finalize: daily top-decile SHORT vs all-valid baseline, frozen criteria, bundle."""
import hashlib, json, math, statistics, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WORK, OUT = ROOT / 'work', ROOT / 'output'
FOLDS = (1, 2, 3, 4, 5)
SIGNALS = ('gap', 'run')
MIN_DAY_SYMBOLS, MIN_FOLD_EVENTS = 50, 100
QUOTA_K = 3


def top_bottom(rows, key):
    """Top and bottom ceil(10%) of rows by key (descending, ties by symbol)."""
    ranked = sorted(rows, key=lambda r: (-r[key], r['sym']))
    k = math.ceil(len(ranked) * 0.1)
    return ranked[:k], ranked[-k:], k


def mean(rows, col):
    return sum(r[col] for r in rows) / len(rows)


def day_event(rows, key):
    if len(rows) < MIN_DAY_SYMBOLS:
        return None
    top, bottom, k = top_bottom(rows, key)
    base = mean(rows, 'short_net')
    q = sorted(rows, key=lambda r: (-r[key], r['sym']))[:QUOTA_K]
    return {'n': len(rows), 'k': k, 'top': mean(top, 'short_net'), 'base': base, 'excess': mean(top, 'short_net') - base,
            'bottom_long': mean(bottom, 'long_net'), 'base_long': mean(rows, 'long_net'),
            'top_mid': mean(top, 'mid'), 'base_mid': mean(rows, 'mid'), 'quota3': mean(q, 'short_net')}


def criteria(events):
    n = len(events)
    top, exc = [e['top'] for e in events], [e['excess'] for e in events]
    mt, me = (sum(top) / n, sum(exc) / n) if n else (None, None)
    sd = statistics.stdev(exc) if n > 1 else 0.0
    t = me / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None
    folds = {}
    for f in FOLDS:
        ev = [e for e in events if e['fold'] == f]
        folds[f] = {'events': len(ev), 'top': sum(e['top'] for e in ev) / len(ev) if ev else None,
                    'excess': sum(e['excess'] for e in ev) / len(ev) if ev else None}
    c = {'A': bool(n) and mt > 0,
         'B': sum(1 for f in FOLDS if folds[f]['top'] is not None and folds[f]['top'] > 0) >= 4,
         'C': bool(n) and me > 0 and t is not None and t >= 2.0,
         'D': sum(1 for f in FOLDS if folds[f]['excess'] is not None and folds[f]['excess'] > 0) >= 4,
         'G': all(folds[f]['events'] >= MIN_FOLD_EVENTS for f in FOLDS)}
    return c, {'events': n, 'mean_top_net_bps': mt, 'mean_excess_bps': me, 't_excess': t, 'folds': folds}


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
    days, cnt = [], Counter()
    for p in sorted(WORK.glob('*.json')):
        d = json.loads(p.read_text())
        assert d['date'] <= '2026-08-27' and d['fold'] in FOLDS
        cnt['DAYS'] += 1
        cnt['FAILED_SYMBOL_DAYS'] += d['failed']
        days.append(d)
    res, lines = {}, []
    for sg in SIGNALS:
        for grp, pred in (('ALL', lambda r: True), ('CORE42', lambda r: r['core']), ('HV_TIER', lambda r: r['hv'])):
            events = []
            for d in days:
                ev = day_event([r for r in d['rows'] if pred(r)], sg)
                if ev:
                    ev['fold'] = d['fold']
                    ev['date'] = d['date']
                    events.append(ev)
            if not events:
                continue
            c, st = criteria(events)
            cls = classify(c)
            n = len(events)
            st.update(mean_base_short_bps=sum(e['base'] for e in events) / n, mean_quota3_short_bps=sum(e['quota3'] for e in events) / n,
                      mean_bottom_long_bps=sum(e['bottom_long'] for e in events) / n, mean_base_long_bps=sum(e['base_long'] for e in events) / n,
                      mean_top_mid_bps=sum(e['top_mid'] for e in events) / n, mean_base_mid_bps=sum(e['base_mid'] for e in events) / n,
                      per_1m_top_short_twd_per_name_day=(sum(e['top'] for e in events) / n) * 100,
                      per_1m_quota3_twd_per_day=(sum(e['quota3'] for e in events) / n) * 100)
            res['%s|%s' % (sg, grp)] = {'classification': cls, 'criteria': c, 'stats': st}
            lines.append('%-3s %-7s %-13s days=%d top_short_net=%+.1f bps (%+.0f TWD/1M) base_short=%+.1f excess=%+.1f t=%s quota3=%+.1f bps (%+.0f TWD/day on 1M) '
                         'top_mid=%+.1f base_mid=%+.1f bottom_long=%+.1f base_long=%+.1f %s folds=%s' % (
                             sg, grp, cls, n, st['mean_top_net_bps'], st['per_1m_top_short_twd_per_name_day'], st['mean_base_short_bps'], st['mean_excess_bps'],
                             'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'], st['mean_quota3_short_bps'], st['per_1m_quota3_twd_per_day'],
                             st['mean_top_mid_bps'], st['mean_base_mid_bps'], st['mean_bottom_long_bps'], st['mean_base_long_bps'], json.dumps(c),
                             json.dumps({f: (v['events'], None if v['top'] is None else round(v['top'], 1)) for f, v in st['folds'].items()})))
    primary = {sg: res['%s|ALL' % sg]['classification'] for sg in SIGNALS if '%s|ALL' % sg in res}
    family = 'STRONG_CANDIDATE' if 'STRONG' in primary.values() else 'NO_STRONG'
    lines += ['PRIMARY ' + json.dumps(primary), 'FAMILY ' + family, 'COUNTS ' + json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'OPEN_FADE_DECISION.json').write_text(json.dumps({'study': 'OPEN_FADE_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'),
                                                             'family': family, 'primary': primary, 'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_open_fade_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'OPEN_FADE_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
