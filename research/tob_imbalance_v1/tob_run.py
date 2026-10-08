#!/usr/bin/env python3
"""TOB_IMBALANCE_V1 worker: top-of-book size imbalance vs forward mid and taker-cost returns on a 5-minute grid."""
import json, os, sys, time
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
for sub in ('passive_fill_v1', 'hv60_v1'):
    sys.path.insert(0, str(ROOT.parent / sub))
import hv60_common as H  # noqa: E402
import pf_fill as F  # noqa: E402
import pf_run as PR  # noqa: E402  (load(): archive file -> F.Ticks, frozen in PASSIVE_FILL_V1)
from daytrade_learning.event_audit import costs as C, timebase as TB  # noqa: E402
import paper_execution as pe  # noqa: E402

WORK = ROOT / 'work'
GRID_SEC = list(range(9 * 3600 + 30 * 60, 12 * 3600 + 25 * 60 + 1, 300))     # 09:30 .. 12:25
HORIZONS = (('1m', 60), ('5m', 300), ('15m', 900))
EDGES = (-0.6, -0.2, 0.2, 0.6)
BUCKETS = ('B1', 'B2', 'B3', 'B4', 'B5')
HV_MIN = 0.030
SHARES = 1000


def imbalance(bid_vol, ask_vol):
    tot = bid_vol + ask_vol
    return None if tot <= 0 else (bid_vol - ask_vol) / tot


def bucket(i):
    """B1: I <= -0.6 ... B5: I >= +0.6 (edges belong to the outer bucket)."""
    if i <= EDGES[0]:
        return 'B1'
    if i < EDGES[1]:
        return 'B2'
    if i <= EDGES[2]:
        return 'B3'
    if i < EDGES[3]:
        return 'B4'
    return 'B5'


def short_net_pct(bid0, ask1):
    e, x = Decimal(str(bid0)) * SHARES, Decimal(str(ask1)) * SHARES
    return float((e - x) / e * 100 - (pe.fee(e) + pe.fee(x) + pe.tax(e)) / e * 100)


def point(ticks, t_us, h_us):
    """None without fresh touch quotes at t and t+h or without displayed size; else bucket and bps metrics."""
    i0, i1 = ticks.quote_at(t_us), ticks.quote_at(t_us + h_us)
    if i0 is None or i1 is None:
        return None
    imb = imbalance(ticks.bidv[i0], ticks.askv[i0])
    if imb is None:
        return None
    mid0, mid1 = (ticks.bid[i0] + ticks.ask[i0]) / 2, (ticks.bid[i1] + ticks.ask[i1]) / 2
    return {'imb': imb, 'bucket': bucket(imb), 'mid': (mid1 / mid0 - 1) * 1e4,
            'long_net': C.cost_quote_pct(ticks.ask[i0], ticks.bid[i1])[1] * 100,
            'short_net': short_net_pct(ticks.bid[i0], ticks.ask[i1]) * 100}


def process(ticks, d0, groups, acc, cnt):
    for sec in GRID_SEC:
        t_us = d0 + sec * 1_000_000
        for hname, hs in HORIZONS:
            p = point(ticks, t_us, hs * 1_000_000)
            if p is None:
                cnt['SKIP:' + hname] += 1
                continue
            cnt['POINTS:' + hname] += 1
            for grp in groups:
                for b in ('ALL', p['bucket']):
                    row = acc.setdefault('|'.join((hname, grp, b)), [0.0] * 4)
                    row[0] += 1
                    row[1] += p['mid']
                    row[2] += p['long_net']
                    row[3] += p['short_net']


def main():
    shard, nshard = int(sys.argv[1]), int(sys.argv[2])
    WORK.mkdir(exist_ok=True)
    syms = H.pool()
    daily = H.Daily(syms)
    days = [d for d in H.archive_days() if TB.fold_for_date(d) >= 1]
    if os.environ.get('TOB_DAYS_CSV'):
        days = [d for d in days if d in set(os.environ['TOB_DAYS_CSV'].split(','))]
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
                process(PR.load(pth, day, d0), d0, groups, acc, cnt)
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
