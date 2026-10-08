#!/usr/bin/env python3
"""HV60_V1 finalize: 60m primary metrics, A-H classification (event_audit.classify), decision, bundle."""
import csv, hashlib, json, math, statistics, sys, tarfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
import hv60_common as H  # noqa: E402
from daytrade_learning.event_audit import classify as CL  # noqa: E402

PIDS = ['HV1', 'HV2', 'HV3']
NAMES = {'HV1': 'HV1_OPEN_DRIVE_CONTINUATION', 'HV2': 'HV2_DOWNSIDE_OVERSHOOT_REVERSAL', 'HV3': 'HV3_VWAP_RECLAIM'}
HN = ['5m', '15m', '30m', '60m', '12:55']
PRIMARY = '60m'


def fin(a):
    return [x for x in a if x is not None and isinstance(x, float) and math.isfinite(x)]


def mean(a):
    a = fin(a)
    return sum(a) / len(a) if a else None


def median(a):
    a = fin(a)
    return statistics.median(a) if a else None


def wr(a):
    a = fin(a)
    return sum(1 for x in a if x > 0) / len(a) if a else None


def pf(a):
    a = fin(a)
    w, l = sum(x for x in a if x > 0), sum(x for x in a if x <= 0)
    return w / abs(l) if l else None


def bps(x):
    return None if x is None else x * 100


def col(rows, h, k):
    return [r[3 + HN.index(h) * 3 + k] for r in rows]


def stats(rows, h):
    g, n, q = col(rows, h, 0), col(rows, h, 1), col(rows, h, 2)
    return {'count': len(rows), 'valid': len(fin(g)), 'gross_bps': bps(mean(g)), 'gross_median_bps': bps(median(g)),
            'net_bps': bps(mean(n)), 'net_median_bps': bps(median(n)), 'quote_bps': bps(mean(q)),
            'quote_median_bps': bps(median(q)), 'gross_wr': wr(g), 'net_wr': wr(n), 'quote_wr': wr(q),
            'pf_gross': pf(g), 'pf_net': pf(n), 'pf_quote': pf(q)}


def main():
    H.OUT.mkdir(exist_ok=True)
    days = H.archive_days()
    missing = [d for d in days if not (H.WORK / (d + '.json')).exists()]
    if missing:
        H.log({'stage': 'STOP', 'missing_days': len(missing)})
        sys.exit(2)
    eps = {p: [] for p in PIDS}
    cnt_all, cnt_test, failed = Counter(), Counter(), 0
    for d in days:
        j = json.loads((H.WORK / (d + '.json')).read_text())
        cnt_all.update(j['cnt'])
        failed += len(j['failed'])
        if j['fold'] in (1, 2, 3, 4, 5):
            cnt_test.update(j['cnt'])
            for p, rows in j['ep'].items():
                for r in rows:
                    eps[p].append((j['fold'], d, r))
    results, lines = {}, []
    fold_rows, hor_rows = [], []
    for p in PIDS:
        allr = [r for _, _, r in eps[p]]
        s = stats(allr, PRIMARY)
        folds = {f: stats([r for fo, _, r in eps[p] if fo == f], PRIMARY) for f in (1, 2, 3, 4, 5)}
        crit = CL.criteria(s['gross_bps'], s['net_bps'], s['quote_bps'], [folds[f]['gross_bps'] for f in folds],
                           [folds[f]['net_bps'] for f in folds], [folds[f]['quote_bps'] for f in folds],
                           [folds[f]['count'] for f in folds])
        cls = CL.classify(crit)
        veto = stats([r for r in allr if r[22] == 1], PRIMARY)
        results[p] = {'name': NAMES[p], 'event_count': len(allr), 'event_days': len({d for _, d, _ in eps[p]}),
                      'primary_60m': s, 'folds_60m': folds, 'criteria': crit, 'classification': cls,
                      'plus_veto_60m_gross_bps': veto['gross_bps'], 'plus_veto_count': veto['count'],
                      'funnel_test': {k.split(':')[1]: v for k, v in cnt_test.items() if k.startswith(p + ':')},
                      'CANDIDATE_FOR_FORWARD_PAPER_SHADOW': cls == 'STRONG_ENTRY_CANDIDATE', 'PRODUCTION_READY': False}
        for f, x in folds.items():
            fold_rows.append([p, f, x['count'], x['valid'], x['gross_bps'], x['net_bps'], x['quote_bps']])
        for h in HN:
            x = stats(allr, h)
            hor_rows.append([p, h, x['count'], x['valid'], x['gross_bps'], x['net_bps'], x['quote_bps'], x['gross_wr'], x['pf_gross']])
    strong = [p for p in PIDS if results[p]['classification'] == 'STRONG_ENTRY_CANDIDATE']
    blocked = [p for p in PIDS if results[p]['classification'] == 'GROSS_EDGE_COST_BLOCKED']
    insuff = sum(results[p]['classification'] == 'INSUFFICIENT_EVENTS' for p in PIDS)
    fam = ('HV60_CANDIDATE_FOUND' if strong else 'HV60_GROSS_CANDIDATE_FOUND' if blocked
           else 'INSUFFICIENT_HV60_EVIDENCE' if insuff > len(PIDS) / 2 else 'NO_HV60_ENTRY_EDGE')
    vk = ['VIOL_REBUILD5', 'VIOL_BAR_END_GT_DECISION', 'VIOL_ENTRY_TICK', 'VIOL_ENTRY_AGE', 'VIOL_EXIT_WINDOW']
    viol = sum(cnt_all[k] for k in vk)
    prereg = {n: hashlib.sha256((H.ROOT / n).read_bytes()).hexdigest() for n in ('HV60_V1.yaml', 'HV60_V1_AMENDMENT_1.yaml')}
    cov, ndays, npool = H.coverage()
    (H.OUT / 'HV60_DECISION.json').write_text(json.dumps({
        'FAMILY_DECISION': fam, 'primitives': results, 'preregistration_sha256': prereg,
        'coverage_at_run': cov, 'test_window_days': ndays, 'pool_size': npool,
        'tier_counts_all_days': {k: cnt_all[k] for k in ('TIER_SYMBOL_DAYS', 'TIER_OUT', 'NO_TIER_HISTORY', 'NO_REFERENCE')},
        'LOOKAHEAD_VIOLATIONS': viol, 'violation_checks': {k: cnt_all[k] for k in vk}, 'causal_checked': cnt_all['CAUSAL_CHECKED'],
        'worker_failures': failed, 'FUTURE_DATA_READ': False, 'PHASE2C_HOLDOUT_TOUCHED': False, 'PRODUCTION_READY': False,
        'finalized_at': datetime.now().isoformat(timespec='seconds')}, indent=2, ensure_ascii=False) + '\n')
    for name, header, rows in (('HV60_FOLD_METRICS_60M.csv', ['pid', 'fold', 'count', 'valid', 'gross_bps', 'net_bps', 'quote_bps'], fold_rows),
                               ('HV60_HORIZON_METRICS.csv', ['pid', 'horizon', 'count', 'valid', 'gross_bps', 'net_bps', 'quote_bps', 'gross_wr', 'pf_gross'], hor_rows)):
        with (H.OUT / name).open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
    (H.OUT / 'FUTURE_HOLDOUT_GUARD.txt').write_text('FUTURE_DATA_READ=false\nPHASE2C_HOLDOUT_TOUCHED=false\nHARD_CUTOFF=2026-10-02\n')
    nm = sorted(x.name for x in H.OUT.iterdir() if x.is_file() and x.name not in ('MANIFEST.sha256', 'FINAL_LINES.txt'))
    (H.OUT / 'MANIFEST.sha256').write_text(''.join('%s  %s\n' % (hashlib.sha256((H.OUT / n).read_bytes()).hexdigest(), n) for n in nm))
    bundle = H.ROOT / ('easystock_hv60_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as t:
        for n in nm + ['MANIFEST.sha256']:
            t.add(H.OUT / n, arcname='easystock_hv60_v1/' + n)
    f2 = lambda x: 'NA' if x is None else '%.3f' % x
    lines = ['FAMILY_DECISION=' + fam, 'COVERAGE_AT_RUN=%.3f' % cov, 'LOOKAHEAD_VIOLATIONS=%d' % viol]
    for p in PIDS:
        r = results[p]
        s = r['primary_60m']
        lines.append('%s EVENTS=%d GROSS60_BPS=%s NET60_BPS=%s QUOTE60_BPS=%s GROSS_POS_FOLDS=%d MIN_FOLD=%d CLASS=%s'
                     % (r['name'], r['event_count'], f2(s['gross_bps']), f2(s['net_bps']), f2(s['quote_bps']),
                        sum(1 for f in r['folds_60m'].values() if f['gross_bps'] is not None and f['gross_bps'] > 0),
                        min(f['count'] for f in r['folds_60m'].values()), r['classification']))
    lines += ['BUNDLE=%s' % bundle, 'BUNDLE_SHA256=%s' % hashlib.sha256(bundle.read_bytes()).hexdigest()]
    (H.OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
