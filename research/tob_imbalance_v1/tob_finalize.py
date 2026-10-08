#!/usr/bin/env python3
"""TOB_IMBALANCE_V1 finalize: day-clustered excess mid return per imbalance bucket, frozen classification, bundle."""
import hashlib, json, math, sys, tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WORK, OUT = ROOT / 'work', ROOT / 'output'
FOLDS = (1, 2, 3, 4, 5)
MIN_FOLD_N = 1000
HORIZONS = ('1m', '5m', '15m')
GROUPS = ('ALL', 'CORE42', 'HV_TIER')
BUCKETS = ('B1', 'B2', 'B3', 'B4', 'B5')


def excess(days, bucket_key, all_key, col):
    """days: {date: (fold, {key: row})}. Mean(bucket) - mean(all) with a day-clustered (linearized) SE."""
    nb = sb = na = sa = 0.0
    for _, rows in days.values():
        b, a = rows.get(bucket_key), rows.get(all_key)
        if b:
            nb, sb = nb + b[0], sb + b[col]
        if a:
            na, sa = na + a[0], sa + a[col]
    if not nb or not na:
        return None
    mb, ma = sb / nb, sa / na
    var = 0.0
    for _, rows in days.values():
        b, a = rows.get(bucket_key) or [0, 0, 0, 0], rows.get(all_key) or [0, 0, 0, 0]
        var += ((b[col] - mb * b[0]) / nb - (a[col] - ma * a[0]) / na) ** 2
    se = math.sqrt(var)
    return {'n': int(nb), 'mean': mb, 'all_mean': ma, 'excess': mb - ma, 'se': se, 't': (mb - ma) / se if se > 0 else None}


def fold_means(days, bucket_key, all_key, col):
    out = {}
    for f in FOLDS:
        sub = {d: v for d, v in days.items() if v[0] == f}
        e = excess(sub, bucket_key, all_key, col)
        out[f] = {'n': e['n'] if e else 0, 'excess': e['excess'] if e else None, 'mean': e['mean'] if e else None}
    return out


def summarize(days, hname, grp, b, side):
    key, allk = '|'.join((hname, grp, b)), '|'.join((hname, grp, 'ALL'))
    col = 3 if side == 'SHORT' else 2
    sign = -1 if side == 'SHORT' else 1
    mid = excess(days, key, allk, 1)
    if not mid:
        return None
    net = excess(days, key, allk, col)
    mid_f, net_f = fold_means(days, key, allk, 1), fold_means(days, key, allk, col)
    s = {'n': mid['n'], 'mid_bps': mid['mean'], 'all_mid_bps': mid['all_mean'],
         'directional_excess_mid_bps': sign * mid['excess'], 't_excess': None if mid['t'] is None else sign * mid['t'],
         'net_bps': net['mean'], 'folds': {}}
    for f in FOLDS:
        s['folds'][f] = {'n': mid_f[f]['n'], 'directional_excess_mid_bps': None if mid_f[f]['excess'] is None else sign * mid_f[f]['excess'],
                         'net_bps': net_f[f]['mean']}
    return s


def criteria(s):
    fo = s['folds']
    return {'A': s['directional_excess_mid_bps'] > 0 and s['t_excess'] is not None and s['t_excess'] >= 2.0,
            'B': sum(1 for f in FOLDS if fo[f]['directional_excess_mid_bps'] is not None and fo[f]['directional_excess_mid_bps'] > 0) >= 4,
            'C': s['net_bps'] > 0,
            'D': sum(1 for f in FOLDS if fo[f]['net_bps'] is not None and fo[f]['net_bps'] > 0) >= 4,
            'G': all(fo[f]['n'] >= MIN_FOLD_N for f in FOLDS)}


def classify(c):
    if not c['G']:
        return 'INSUFFICIENT'
    if all(c[k] for k in 'ABCD'):
        return 'STRONG'
    if c['A'] and c['B'] and not c['C']:
        return 'SIGNAL_COST_BLOCKED'
    if not c['A']:
        return 'NO_EDGE'
    return 'WEAK'


def main():
    OUT.mkdir(exist_ok=True)
    days, cnt, failed = {}, Counter(), []
    for p in sorted(WORK.glob('*.json')):
        d = json.loads(p.read_text())
        assert d['date'] <= '2026-10-02' and d['fold'] in FOLDS
        cnt.update(d['cnt'])
        failed += [dict(x, date=d['date']) for x in d['failed']]
        days[d['date']] = (d['fold'], d['acc'])
    res, decisions, lines = {}, {}, []
    for hname in HORIZONS:
        for grp in GROUPS:
            for b in BUCKETS:
                for side in (('LONG',) if b == 'B5' else ('SHORT',) if b == 'B1' else ('LONG',)):
                    s = summarize(days, hname, grp, b, side)
                    if not s:
                        continue
                    c = criteria(s)
                    cls = classify(c)
                    res['%s|%s|%s|%s' % (hname, grp, b, side)] = {'stats': s, 'criteria': c, 'classification': cls}
                    lines.append('%-3s %-7s %s %-5s n=%8d mid=%+6.2f (all %+6.2f) dir_excess=%+6.2f t=%s net=%+7.2f %s %s' % (
                        hname, grp, b, side, s['n'], s['mid_bps'], s['all_mid_bps'], s['directional_excess_mid_bps'],
                        'NA' if s['t_excess'] is None else '%+.2f' % s['t_excess'], s['net_bps'], cls, json.dumps(c)))
                    if grp == 'ALL' and b == 'B5':
                        decisions[hname] = cls
    family = 'STRONG_CANDIDATE' if any(v == 'STRONG' for v in decisions.values()) else (
        'SIGNAL_COST_BLOCKED' if any(v == 'SIGNAL_COST_BLOCKED' for v in decisions.values()) else 'NO_STRONG')
    lines += ['PRIMARY ' + json.dumps(decisions), 'FAMILY ' + family, 'COUNTS ' + json.dumps(dict(cnt)),
              'days=%d failed_symbol_days=%d' % (len(days), len(failed)),
              'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'TOB_IMBALANCE_DECISION.json').write_text(json.dumps(
        {'study': 'TOB_IMBALANCE_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'), 'family': family,
         'primary': decisions, 'counts': dict(cnt), 'failed_sample': failed[:20], 'results': res}, indent=1))
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_tob_imbalance_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'TOB_IMBALANCE_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
