#!/usr/bin/env python3
"""META_B_FILTER_V1 worker: replays the frozen runway B rule over archived symbol-days (one symbol in memory at a time)
and writes every B firing in the radar top-N with its trade replay and decision-time features."""
import gzip, json, os, sys, time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import mb_common as M  # noqa: E402

M.prepare_worker_environment()   # radar env pinned, repo copy first so shared modules are cached from this checkout
from daytrade_learning.event_audit import costs as _C, timebase as TB  # noqa: E402,F401
for sub in ('passive_fill_v1', 'hv60_v1'):
    sys.path.insert(0, str(ROOT.parent / sub))
import hv60_common as H  # noqa: E402  (pool, archive paths, official daily DB, Amendment 1 references)
M.repo_first()           # hv60_common puts the production checkout first; restore the repo copy
import pf_run as PR  # noqa: E402  (archive file -> pf_fill.Ticks, frozen in PASSIVE_FILL_V1)
import mb_signal as S  # noqa: E402

WORK = ROOT / 'work'


def main():
    shard, nshard = int(sys.argv[1]), int(sys.argv[2])
    last_day = os.environ.get('MB_LAST_DAY', M.STAGE1_LAST_DAY)
    if last_day > TB.HARD_CUTOFF:
        raise SystemExit('last day after the hard cutoff')
    pins = M.verify_pins()
    compute, qualifies, score, radar_meta = M.radar_functions()
    evaluate_signal = M.pinned('strategy').evaluate_signal
    WORK.mkdir(exist_ok=True)
    syms = H.pool()
    daily = H.Daily(syms)
    days = [d for d in H.archive_days() if d <= last_day]
    if os.environ.get('MB_DAYS_CSV'):
        days = [d for d in days if d in set(os.environ['MB_DAYS_CSV'].split(','))]
    mine = [d for i, d in enumerate(days) if i % nshard == shard]
    M.log({'stage': 'start', 'shard': shard, 'days': len(mine), 'pool': len(syms), 'pins': pins, 'radar': radar_meta,
           'modules': M.module_files()})
    t0 = time.monotonic()
    for k, day in enumerate(mine):
        out = WORK / (day + '.json.gz')
        if out.exists():
            continue
        cnt, failed, per_symbol = Counter(), [], {}
        d0 = TB.day0_us(day)
        for sym, pth in sorted(H.day_files(day, syms).items()):
            cnt['SYMBOL_DAYS'] += 1
            ref = daily.reference(sym, day)
            if not ref:
                cnt['SKIP:no_reference'] += 1
                continue
            try:
                ticks = PR.load(pth, day, d0)
                if not ticks.tus:
                    cnt['SKIP:no_ticks'] += 1
                    continue
                kbars = json.loads(gzip.decompress(pth.read_bytes()))['kbars']
                sd = S.SymbolDay(sym, ticks, kbars, d0)
                per_symbol[sym] = S.scan_symbol(sd, ref, daily.trailing_range(sym, day), daily.bars.get(sym), day,
                                                compute, qualifies, score, evaluate_signal, cnt)
            except Exception as e:
                failed.append({'symbol': sym, 'reason': type(e).__name__ + ':' + str(e)[:80]})
        firings = S.assemble_day(per_symbol, M.RADAR_TOP_N)
        cnt['TOPN_FIRINGS'] = len(firings)
        tmp = out.with_suffix('.tmp')
        tmp.write_bytes(gzip.compress(json.dumps({'date': day, 'fold': TB.fold_for_date(day), 'cnt': dict(cnt),
                                                  'failed': failed, 'firings': firings},
                                                 separators=(',', ':')).encode()))
        tmp.replace(out)
        if (k + 1) % 10 == 0:
            M.log({'stage': 'progress', 'shard': shard, 'done': k + 1, 'total': len(mine),
                   'elapsed_s': round(time.monotonic() - t0)})
    M.log({'stage': 'complete', 'shard': shard})


if __name__ == '__main__':
    main()
