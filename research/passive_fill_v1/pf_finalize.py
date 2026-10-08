#!/usr/bin/env python3
"""PASSIVE_FILL_V1 finalize: day-clustered savings vs taker, frozen decision rule, bundle."""
import hashlib, json, math, sys, tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
WORK, OUT = ROOT / 'work', ROOT / 'output'
FOLDS = (1, 2, 3, 4, 5)
MIN_FOLD_N = 100
NAMES = ('n', 'gross', 'net', 'mid', 'd_gross', 'd_net', 'entry_passive', 'exit_passive', 'n_unfilled', 'mid_unfilled')


def summarize(per_day):
    """per_day: list of (fold, row). Point-weighted means; SE of d_gross clustered by day."""
    tot = [0.0] * len(NAMES)
    for _, row in per_day:
        tot = [a + b for a, b in zip(tot, row)]
    n = tot[0]
    s = {'points': int(n), 'days': sum(1 for _, r in per_day if r[0] > 0), 'unfilled': int(tot[8])}
    if n:
        for k in (1, 2, 3, 4, 5):
            s[NAMES[k] + '_bps'] = tot[k] / n
        s['shortfall_bps'] = (tot[3] - tot[1]) / n          # mid-to-mid minus realized gross (spread + adverse selection)
        s['all_in_cost_bps'] = (tot[3] - tot[2]) / n        # mid-to-mid minus realized net (adds fee + tax)
        s['entry_passive_rate'] = tot[6] / n
        s['exit_passive_rate'] = tot[7] / n
        m = tot[4] / n
        var = sum((r[4] - r[0] * m) ** 2 for _, r in per_day)
        s['d_gross_se_bps'] = math.sqrt(var) / n
        s['d_gross_lo95_bps'] = m - 1.96 * s['d_gross_se_bps']
    if tot[8]:
        s['mid_unfilled_bps'] = tot[9] / tot[8]
    folds = {}
    for f in FOLDS:
        rows = [r for fd, r in per_day if fd == f]
        fn = sum(r[0] for r in rows)
        folds[f] = {'points': int(fn), 'd_gross_bps': (sum(r[4] for r in rows) / fn) if fn else None}
    s['folds'] = folds
    return s


def decide(res, hname, pol, grp):
    q, st = res.get('|'.join((hname, 'QUEUE', pol, grp))), res.get('|'.join((hname, 'STRICT', pol, grp)))
    if not q or not st or not q['points']:
        return 'INSUFFICIENT_DATA', {}
    folds = q['folds']
    if any(folds[f]['points'] < MIN_FOLD_N for f in FOLDS):
        return 'INSUFFICIENT_DATA', {'fold_points': {f: folds[f]['points'] for f in FOLDS}}
    crit = {'A_queue_saving_gt_0': q['d_gross_bps'] > 0,
            'B_queue_lo95_gt_0': q['d_gross_lo95_bps'] > 0,
            'C_positive_in_4_of_5_folds': sum(1 for f in FOLDS if folds[f]['d_gross_bps'] > 0) >= 4,
            'D_strict_saving_gt_0': bool(st['points']) and st['d_gross_bps'] > 0}
    return ('SAVING_CONFIRMED' if all(crit.values()) else 'NOT_CONFIRMED'), crit


def main():
    OUT.mkdir(exist_ok=True)
    files = sorted(WORK.glob('*.json'))
    per_key, cnt, failed = defaultdict(list), Counter(), []
    for p in files:
        d = json.loads(p.read_text())
        assert d['date'] <= '2026-10-02' and d['fold'] in FOLDS
        cnt.update(d['cnt'])
        failed += [dict(x, date=d['date']) for x in d['failed']]
        for key, row in d['acc'].items():
            per_key[key].append((d['fold'], row))
    res = {key: summarize(v) for key, v in sorted(per_key.items())}
    decisions = {}
    for grp in ('ALL', 'HV_TIER', 'CORE42'):
        for pol in ('PF60', 'PF300'):
            decisions['60m|%s|%s' % (pol, grp)] = decide(res, '60m', pol, grp)
    primary = {k: v[0] for k, v in decisions.items() if k.endswith('|ALL') or k.endswith('|HV_TIER')}
    family = 'SAVING_CONFIRMED' if any(v == 'SAVING_CONFIRMED' for v in primary.values()) else 'NOT_CONFIRMED'
    out = {'study': 'PASSIVE_FILL_V1', 'generated_at': datetime.now().isoformat(timespec='seconds'),
           'days': len(files), 'counts': dict(cnt), 'failed_symbol_days': len(failed), 'failed_sample': failed[:20],
           'decisions': {k: {'decision': v[0], 'criteria': v[1]} for k, v in decisions.items()},
           'family_decision': family, 'results': res,
           'FUTURE_DATA_READ': False, 'PHASE2C_HOLDOUT_TOUCHED': False, 'PRODUCTION_READY': False}
    (OUT / 'PASSIVE_FILL_DECISION.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
    lines = ['PASSIVE_FILL_V1 days=%d symbol_days=%d failed=%d family=%s' % (len(files), cnt['SYMBOL_DAYS'], len(failed), family)]
    for hname in ('15m', '60m'):
        for grp in ('ALL', 'CORE42', 'HV_TIER'):
            for model in ('QUEUE', 'STRICT'):
                for pol in ('TAKER', 'PF60', 'PF300', 'PS60', 'PS300'):
                    s = res.get('|'.join((hname, model, pol, grp)))
                    if not s or not s['points'] or (pol == 'TAKER' and model == 'STRICT'):
                        continue
                    lines.append('%s %-7s %-6s %-5s n=%7d mid=%+6.2f gross=%+7.2f net=%+7.2f shortfall=%6.2f all_in=%6.2f '
                                 'saved=%+6.2f (lo95 %+6.2f) entry_passive=%.2f exit_passive=%.2f%s' % (
                                     hname, grp, model, pol, s['points'], s['mid_bps'], s['gross_bps'], s['net_bps'],
                                     s['shortfall_bps'], s['all_in_cost_bps'], s['d_gross_bps'], s['d_gross_lo95_bps'],
                                     s['entry_passive_rate'], s['exit_passive_rate'],
                                     (' mid_unfilled=%+.2f n_unfilled=%d' % (s['mid_unfilled_bps'], s['unfilled'])) if s['unfilled'] else ''))
    for k, v in decisions.items():
        lines.append('DECISION %s %s %s' % (k, v[0], json.dumps(v[1])))
    lines += ['FAMILY %s' % family, 'FUTURE_DATA_READ=false PHASE2C_HOLDOUT_TOUCHED=false PRODUCTION_READY=false']
    (OUT / 'FINAL_LINES.txt').write_text('\n'.join(lines) + '\n')
    bundle = OUT / ('easystock_passive_fill_v1_%s.tar.gz' % datetime.now().strftime('%Y%m%d'))
    with tarfile.open(bundle, 'w:gz') as tf:
        for p in [OUT / 'PASSIVE_FILL_DECISION.json', OUT / 'FINAL_LINES.txt'] + sorted(ROOT.glob('*.py')) + sorted(ROOT.glob('*.yaml')):
            tf.add(p, arcname=p.name)
    lines.append('BUNDLE %s sha256=%s' % (bundle.name, hashlib.sha256(bundle.read_bytes()).hexdigest()))
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
