#!/usr/bin/env python3
"""PASSIVE_FILL_V1 worker: unconditional LONG round trips on a fixed clock grid, taker vs passive execution."""
import gzip, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'hv60_v1'))
import hv60_common as H  # noqa: E402  (pool, archive paths, official daily DB; frozen HV60 helpers)
import pf_fill as F  # noqa: E402
from daytrade_learning.event_audit import costs as C, timebase as TB  # noqa: E402

WORK = ROOT / 'work'
GRID_SEC = [9 * 3600 + 30 * 60 + 900 * k for k in range(10)]      # 09:30, 09:45, ..., 11:45
HORIZONS = (('15m', 900), ('60m', 3600))
HV_MIN = 0.030
# per key: n, gross, net, mid, d_gross_vs_taker, d_net_vs_taker, entry_passive, exit_passive, n_unfilled, mid_unfilled
WIDTH = 10


def load(path, day, d0):
    d = json.loads(gzip.decompress(path.read_bytes()))
    if d.get('date') != day or d.get('symbol') != path.name[:-8]:
        raise ValueError('archive_identity_mismatch')
    t = d['ticks']
    n = len(t['ts'])
    cols = {k: (t.get(k) or [0] * n) for k in ('close', 'volume', 'tick_type', 'bid_price', 'ask_price', 'bid_volume', 'ask_volume')}
    keep = [i for i in range(n) if 32400 <= (int(t['ts'][i]) // 1000 - d0) // 1_000_000 < 48600]
    keep.sort(key=lambda i: int(t['ts'][i]))
    return F.Ticks([int(t['ts'][i]) // 1000 for i in keep], [float(cols['close'][i]) for i in keep],
                   [int(cols['volume'][i]) for i in keep], [int(cols['tick_type'][i]) for i in keep],
                   [float(cols['bid_price'][i]) for i in keep], [float(cols['ask_price'][i]) for i in keep],
                   [int(cols['bid_volume'][i]) for i in keep], [int(cols['ask_volume'][i]) for i in keep])


def add(acc, key, vals):
    row = acc.setdefault(key, [0.0] * WIDTH)
    for k, v in enumerate(vals):
        row[k] += v


def process(ticks, d0, groups, acc, cnt):
    for sec in GRID_SEC:
        t_us = d0 + sec * 1_000_000
        for hname, hs in HORIZONS:
            for model in F.MODELS:
                sim = F.simulate(ticks, t_us, hs * 1_000_000, model)
                if sim is None:
                    cnt['NO_QUOTE:' + hname + ':' + model] += 1
                    continue
                mid = (sim['mid1'] / sim['mid0'] - 1) * 1e4
                te, tx = sim['TAKER'][:2]
                tg, tn = (v * 100 for v in C.cost_pct(te, tx))
                for pol in F.POLICIES:
                    r = sim[pol]
                    if r is None:
                        vals = [0, 0, 0, 0, 0, 0, 0, 0, 1, mid]
                    else:
                        g, n = (v * 100 for v in C.cost_pct(r[0], r[1]))
                        vals = [1, g, n, mid, g - tg, n - tn, int(r[2]), int(r[3]), 0, 0]
                    for grp in groups:
                        add(acc, '|'.join((hname, model, pol, grp)), vals)
                cnt['POINTS:' + hname + ':' + model] += 1


def main():
    shard, nshard = int(sys.argv[1]), int(sys.argv[2])
    WORK.mkdir(exist_ok=True)
    syms = H.pool()
    daily = H.Daily(syms)
    days = [d for d in H.archive_days() if TB.fold_for_date(d) >= 1]
    if os.environ.get('PF_DAYS_CSV'):
        days = [d for d in days if d in set(os.environ['PF_DAYS_CSV'].split(','))]
    mine = [d for i, d in enumerate(days) if i % nshard == shard]
    H.log({'stage': 'start', 'shard': shard, 'days': len(mine), 'pool': len(syms)})
    t0 = time.monotonic()
    for k, day in enumerate(mine):
        out = WORK / (day + '.json')
        if out.exists():
            continue
        acc, cnt, failed = {}, Counter(), []
        d0 = TB.day0_us(day)
        for sym, pth in sorted(H.day_files(day, syms).items()):
            tr = daily.trailing_range(sym, day)
            groups = ['ALL'] + (['CORE42'] if sym in TB.CORE_UNIVERSE else []) + (['HV_TIER'] if tr is not None and tr >= HV_MIN else [])
            cnt['SYMBOL_DAYS'] += 1
            try:
                process(load(pth, day, d0), d0, groups, acc, cnt)
            except Exception as e:
                failed.append({'symbol': sym, 'reason': type(e).__name__ + ':' + str(e)[:80]})
        tmp = out.with_suffix('.tmp')
        tmp.write_text(json.dumps({'date': day, 'fold': TB.fold_for_date(day), 'cnt': dict(cnt), 'failed': failed,
                                   'acc': {key: [round(v, 6) for v in row] for key, row in acc.items()}}, separators=(',', ':')))
        tmp.replace(out)
        if (k + 1) % 20 == 0:
            H.log({'stage': 'progress', 'shard': shard, 'done': k + 1, 'total': len(mine), 'elapsed_s': round(time.monotonic() - t0)})
    H.log({'stage': 'complete', 'shard': shard})


if __name__ == '__main__':
    main()
