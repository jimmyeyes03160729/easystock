#!/usr/bin/env python3
"""OPEN_FADE_V1 worker: per symbol-day 09:30 and 12:55 touch quotes plus the opening gap and morning run, short and long nets."""
import json, os, sys, time
from bisect import bisect_right
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
for sub in ('passive_fill_v1', 'hv60_v1'):
    sys.path.insert(0, str(ROOT.parent / sub))
import hv60_common as H  # noqa: E402
import pf_run as PR  # noqa: E402  (load(): archive file -> Ticks, frozen in PASSIVE_FILL_V1)
from daytrade_learning.event_audit import costs as C, timebase as TB  # noqa: E402
import paper_execution as pe  # noqa: E402

WORK = ROOT / 'work'
T_ENTRY, T_EXIT = 9 * 3600 + 30 * 60, 12 * 3600 + 55 * 60
SHARES = 1000
HV_MIN = 0.030
EXPLORATION_EVERY = 6          # archive days with index % 6 == 0 were used for the descriptive decomposition and are excluded


def short_net_pct(bid0, ask1):
    e, x = Decimal(str(bid0)) * SHARES, Decimal(str(ask1)) * SHARES
    return float((e - x) / e * 100 - (pe.fee(e) + pe.fee(x) + pe.tax(e)) / e * 100)


def row_for(ticks, d0, ref):
    """None unless the opening tick, a fresh 09:30 touch quote and a fresh 12:55 touch quote all exist."""
    if not ticks.tus or ticks.tus[0] - d0 > (9 * 3600 + 60) * 1_000_000 or not ref or ref <= 0:
        return None
    t0, t1 = d0 + T_ENTRY * 1_000_000, d0 + T_EXIT * 1_000_000
    i0, i1 = ticks.quote_at(t0), ticks.quote_at(t1)
    k = bisect_right(ticks.tus, t0) - 1
    if i0 is None or i1 is None or k < 0 or t0 - ticks.tus[k] > 30_000_000:
        return None
    p_open, p0 = ticks.price[0], ticks.price[k]
    mid0, mid1 = (ticks.bid[i0] + ticks.ask[i0]) / 2, (ticks.bid[i1] + ticks.ask[i1]) / 2
    return {'gap': (p_open / ref - 1) * 100, 'run': (p0 / ref - 1) * 100, 'mid': (mid1 / mid0 - 1) * 1e4,
            'short_net': short_net_pct(ticks.bid[i0], ticks.ask[i1]) * 100,
            'long_net': C.cost_quote_pct(ticks.ask[i0], ticks.bid[i1])[1] * 100}


def main():
    shard, nshard = int(sys.argv[1]), int(sys.argv[2])
    WORK.mkdir(exist_ok=True)
    syms = H.pool()
    daily = H.Daily(syms)
    all_days = H.archive_days()
    explore = {d for i, d in enumerate(all_days) if i % EXPLORATION_EVERY == 0}
    days = [d for d in all_days if TB.fold_for_date(d) >= 1 and d not in explore]
    if os.environ.get('OFD_DAYS_CSV'):
        days = [d for d in days if d in set(os.environ['OFD_DAYS_CSV'].split(','))]
    mine = [d for i, d in enumerate(days) if i % nshard == shard]
    H.log({'stage': 'start', 'shard': shard, 'days': len(mine), 'excluded_exploration_days': len(explore)})
    t0 = time.monotonic()
    for k, day in enumerate(mine):
        out = WORK / (day + '.json')
        if out.exists():
            continue
        d0, rows, failed = TB.day0_us(day), [], 0
        for sym, pth in sorted(H.day_files(day, syms).items()):
            try:
                r = row_for(PR.load(pth, day, d0), d0, daily.reference(sym, day))
            except Exception:
                failed += 1
                continue
            if r is None:
                continue
            tr = daily.trailing_range(sym, day)
            r.update(sym=sym, hv=int(tr is not None and tr >= HV_MIN), core=int(sym in TB.CORE_UNIVERSE))
            rows.append(r)
        tmp = out.with_suffix('.tmp')
        tmp.write_text(json.dumps({'date': day, 'fold': TB.fold_for_date(day), 'failed': failed,
                                   'rows': [{k2: (round(v, 4) if isinstance(v, float) else v) for k2, v in r.items()} for r in rows]},
                                  separators=(',', ':')))
        tmp.replace(out)
        if (k + 1) % 20 == 0:
            H.log({'stage': 'progress', 'shard': shard, 'done': k + 1, 'total': len(mine), 'elapsed_s': round(time.monotonic() - t0)})
    H.log({'stage': 'complete', 'shard': shard})


if __name__ == '__main__':
    main()
