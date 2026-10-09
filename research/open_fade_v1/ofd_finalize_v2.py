#!/usr/bin/env python3
"""OPEN_FADE_V2 finalize: the OPEN_FADE_V1 hypotheses on the days V1 did not consume (30..49 valid symbols per day).

Reads the same per-day rows written by ofd_run.py (V1 work files). Selection by day is by the number of valid symbols only,
never by returns. Folds 1-4 decide; fold 5 keeps only the few leftover days and is reported.
"""
import hashlib, json, math, statistics, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import ofd_finalize as FZ  # noqa: E402

WORK, OUT = ROOT / 'work', ROOT / 'output_v2'
DECIDING_FOLDS = (1, 2, 3, 4)
MIN_DAY_SYMBOLS, V1_MIN_DAY_SYMBOLS = 30, 50
MIN_FOLD_DAYS = 40
FZ.MIN_DAY_SYMBOLS = MIN_DAY_SYMBOLS


def criteria(events):
    n = len(events)
    top, exc = [e['top'] for e in events], [e['excess'] for e in events]
    mt, me = (sum(top) / n, sum(exc) / n) if n else (None, None)
    sd = statistics.stdev(exc) if n > 1 else 0.0
    t = me / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None
    folds = {}
    for f in FZ.FOLDS:
        ev = [e for e in events if e['fold'] == f]
        folds[f] = {'events': len(ev), 'top': sum(e['top'] for e in ev) / len(ev) if ev else None,
                    'excess': sum(e['excess'] for e in ev) / len(ev) if ev else None}
    c = {'A': bool(n) and mt > 0,
         'B': sum(1 for f in DECIDING_FOLDS if folds[f]['top'] is not None and folds[f]['top'] > 0) >= 3,
         'C': bool(n) and me > 0 and t is not None and t >= 2.0,
         'D': sum(1 for f in DECIDING_FOLDS if folds[f]['excess'] is not None and folds[f]['excess'] > 0) >= 3,
         'G': all(folds[f]['events'] >= MIN_FOLD_DAYS for f in DECIDING_FOLDS)}
    return c, {'events': n, 'mean_top_net_bps': mt, 'mean_excess_bps': me, 't_excess': t, 'folds': folds}


def main():
    OUT.mkdir(exist_ok=True)
    days, cnt = [], Counter()
    for p in sorted(WORK.glob('*.json')):
        d = json.loads(p.read_text())
        assert d['date'] <= '2026-08-27' and d['fold'] in FZ.FOLDS
        n = len(d['rows'])
        if V1_MIN_DAY_SYMBOLS <= n:
            cnt['DAYS_CONSUMED_BY_V1'] += 1
            continue
        if n < MIN_DAY_SYMBOLS:
            cnt['DAYS_TOO_FEW_SYMBOLS'] += 1
            continue
        cnt['DAYS_USED'] += 1
        days.append(d)
    res, lines = {}, []
    for sg in FZ.SIGNALS:
        for grp, pred in (('ALL', lambda r: True), ('CORE42', lambda r: r['core'])):
            events = []
            for d in days:
                ev = FZ.day_event([r for r in d['rows'] if pred(r)], sg)
                if ev:
                    ev['fold'], ev['date'] = d['fold'], d['date']
                    events.append(ev)
            if not events:
                continue
            c, st = criteria(events)
            cls = FZ.classify(c)
            n = len(events)
            st.update(mean_base_short_bps=sum(e['base'] for e in events) / n, mean_quota3_short_bps=sum(e['quota3'] for e in events) / n,
                      mean_top_mid_bps=sum(e['top_mid'] for e in events) / n, mean_base_mid_bps=sum(e['base_mid'] for e in events) / n,
                      mean_bottom_long_bps=sum(e['bottom_long'] for e in events) / n, mean_base_long_bps=sum(e['base_long'] for e in events) / n,
                      per_1m_top_short_twd_per_name_day=(sum(e['top'] for e in events) / n) * 100,
                      per_1m_quota3_twd_per_day=(sum(e['quota3'] for e in events) / n) * 100, mean_top_size=sum(e['k'] for e in events) / n)
            res['%s|%s' % (sg, grp)] = {'classification': cls, 'criteria': c, 'stats': st}
            lines.append('%-3s %-7s %-13s days=%d top_size=%.1f top_short_net=%+.1f bps (%+.0f TWD/1M) base_short=%+.1f excess=%+.1f t=%s quota3=%+.1f bps (%+.0f TWD/day on 1M) '
                         'top_mid=%+.1f base_mid=%+.1f %s folds=%s' % (
                             sg, grp, cls, n, st['mean_top_size'], st['mean_top_net_bps'], st['per_1m_top_short_twd_per_name_day'], st['mean_base_short_bps'],
                             st['mean_excess_bps'], 'NA' if st['t_excess'] is None else '%.2f' % st['t_excess'], st['mean_quota3_short_bps'],
                             st['per_1m_quota3_twd_per_day'], st['mean_top_mid_bps'], st['mean_base_mid_bps'], json.dumps(c),
                             json.dumps({f: (v['events'], None if v['top'] is None else round(v['top'], 1), None if v['excess'] is None else round(v['excess'], 1))
                                         for f, v in st['folds'].items()})))
    primary = {sg: res['%s|ALL' % sg]['classification'] for sg in FZ.SIGNALS if '%s|ALL' % sg in res}
    family = 'STRONG_CANDIDATE' if 'STRONG' in primary.values() else 'NO_STRONG'
    lines += ['PRIMARY ' + json.dumps(primary), 'FAMILY ' + family, 'COUNTS ' + json.dumps(dict(cnt)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'OPEN_FADE_V2_DECISION.json').write_text(json.dumps({'study': 'OPEN_FADE_V2', 'generated_at': datetime.now().isoformat(timespec='seconds'),
                                                                'family': family, 'primary': primary, 'counts': dict(cnt), 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_open_fade_v2_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'OPEN_FADE_V2_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
