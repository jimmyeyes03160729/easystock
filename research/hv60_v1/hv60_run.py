#!/usr/bin/env python3
"""HV60_V1 worker: per symbol-day in the high-volatility tier, evaluate HV1-HV3 at completed 5m bars."""
import json, os, sys, time
from bisect import bisect_right
from collections import Counter

sys.dont_write_bytecode = True
import hv60_common as H  # noqa: E402
import strategy_engine as SE  # noqa: E402
from daytrade_learning.event_audit import bars as B, episodes as EP, markouts as MK, timebase as TB  # noqa: E402
from daytrade_learning.knowledge_v1 import KnowledgeV1Features as KF  # noqa: E402

PIDS = ['HV1', 'HV2', 'HV3']
EXITS = [h for h, _ in MK.HORIZONS]


def limits():
    try:
        sys.path.insert(0, '/home/ubuntu/easystock')
        from easystock_admin.store import read_live_settings
        s = read_live_settings()
        return {'min_price': s.get('min_price', 1), 'max_price': s.get('max_price', 1000000), 'max_gain_pct': s.get('max_gain_pct', 5)}
    except Exception:
        return {'min_price': 1, 'max_price': 1000000, 'max_gain_pct': 5}


def flat(mk):
    row = []
    for name in EXITS:
        h = mk[name]
        row += ([round(h['gross'], 6), round(h['net'], 6), None if h['quote'] is None else round(h['quote'], 6)]
                if h['status'] == 'OK' else [None, None, None])
    p = mk['path']
    return row + [round(p['MFE_15M'], 6), round(p['MAE_15M'], 6), p['time_to_MFE_s'], p['time_to_MAE_s']]


def process(day, sym, pth, tr, ref, d0, lim, cnt, eps):
    kb, tus, tp, tb, ta = H.load_ticks(pth, day, d0)
    if not tus:
        return
    mins = B.build_minute_bars(kb, d0)
    rows5 = B.group_complete(mins, 5)
    rows15 = B.group_complete(mins, 15)
    if not rows5:
        return
    first_open = mins[min(mins)][0]
    ends5 = {r['_end_sec']: j for j, r in enumerate(rows5)}
    ends15 = [r['_end_sec'] for r in rows15]
    vw = [SE.calculate_vwap(B.strip(rows5[:j + 1])) for j in range(len(rows5))]
    states = {p: [] for p in PIDS}
    where = {}
    for i, r in enumerate(rows5):
        E = r['_end_sec']
        if not (H.ENTRY_START <= E < H.ENTRY_END):
            continue
        t_us = d0 + E * 1_000_000
        cnt['EVAL_POINTS'] += 1
        ei = MK.entry_index(tus, t_us)
        px = tp[ei] if ei is not None else None
        ok = (px is not None and lim['min_price'] <= px <= lim['max_price']
              and (px / ref - 1.0) * 100.0 <= lim['max_gain_pct'])
        cond = {p: False for p in PIDS}
        if px is not None and vw[i]:
            cond['HV1'] = (px / first_open - 1) >= 0.5 * tr and px >= vw[i]
            j15 = ends5.get(E - 900)
            clv = KF.close_location_value(B.strip([r])[0])
            if j15 is not None and clv is not None:
                cond['HV2'] = (px / rows5[j15]['close'] - 1) <= -0.35 * tr and clv > 0
            if i >= 6 and all(vw[j] and rows5[j]['close'] < vw[j] for j in range(i - 6, i)):
                cond['HV3'] = rows5[i]['close'] > vw[i]
        for p in PIDS:
            if cond[p]:
                cnt[p + ':COND_TRUE'] += 1
                if px is None:
                    cnt[p + ':DROP_STALE'] += 1
                elif not ok:
                    cnt[p + ':DROP_LIMITS'] += 1
            states[p].append((t_us, bool(cond[p] and ok)))
        where[t_us] = (i, ei)
    for p in PIDS:
        res = EP.select_episodes(states[p], horizon_us=H.HORIZON_US)
        cnt[p + ':RAW_PASS_ROWS'] += res.raw_pass_rows
        cnt[p + ':FALSE_TO_TRUE'] += res.false_to_true
        cnt[p + ':OVERLAP_EXCLUDED'] += res.overlap_excluded
        for t_us in res.accepted:
            i, ei = where[t_us]
            sub = B.strip(rows5[:i + 1])
            r15 = B.strip(rows15[:bisect_right(ends15, rows5[i]['_end_sec'])])
            cnt['CAUSAL_CHECKED'] += 1
            cnt['VIOL_REBUILD5'] += (not B.causal_rows_match(kb, d0, t_us, sub, 5))
            cnt['VIOL_BAR_END_GT_DECISION'] += (max(x['_max1m_end_us'] for x in rows5[:i + 1]) > t_us)
            cnt['VIOL_ENTRY_TICK'] += (tus[ei] > t_us)
            cnt['VIOL_ENTRY_AGE'] += (t_us - tus[ei] > MK.MAX_AGE_US)
            mk = MK.markouts(tus, tp, tb, ta, t_us, ei, d0)
            for name in EXITS:
                if mk[name]['status'] == 'OK' and mk[name]['exit_us'] <= t_us:
                    cnt['VIOL_EXIT_WINDOW'] += 1
            if mk['60m']['status'] != 'OK':
                cnt[p + ':MISSING60'] += 1
            rr = SE.evaluate_daytrade(sub, r15, stock=None, market_level='YELLOW') if len(r15) >= 2 else None
            vf = None if rr is None else int(rr.get('vetoes') == [])
            eps.setdefault(p, []).append([sym, t_us, tp[ei]] + flat(mk) + [vf, round(tr, 6)])
            cnt[p + ':FINAL'] += 1


def main():
    shard, n = int(sys.argv[1]), int(sys.argv[2])
    H.WORK.mkdir(exist_ok=True)
    daily = H.Daily(H.pool())
    lim = limits()
    syms = H.pool()
    days = H.archive_days()
    if os.environ.get('HV_DAYS_CSV'):
        days = [d for d in days if d in set(os.environ['HV_DAYS_CSV'].split(','))]
    mine = [d for i, d in enumerate(days) if i % n == shard]
    H.log({'stage': 'start', 'shard': shard, 'days': len(mine), 'pool': len(syms), 'limits': lim})
    t0 = time.monotonic()
    for k, day in enumerate(mine):
        out = H.WORK / (day + '.json')
        if out.exists():
            continue
        cnt, eps, failed = Counter(), {}, []
        d0 = TB.day0_us(day)
        for sym, pth in sorted(H.day_files(day, syms).items()):
            tr = daily.trailing_range(sym, day)
            if tr is None:
                cnt['NO_TIER_HISTORY'] += 1
                continue
            if tr < H.TIER_MIN:
                cnt['TIER_OUT'] += 1
                continue
            ref = daily.reference(sym, day)
            if not ref:
                cnt['NO_REFERENCE'] += 1
                continue
            cnt['TIER_SYMBOL_DAYS'] += 1
            try:
                process(day, sym, pth, tr, ref, d0, lim, cnt, eps)
            except Exception as e:
                failed.append({'symbol': sym, 'reason': type(e).__name__ + ':' + str(e)[:80]})
        tmp = out.with_suffix('.tmp')
        tmp.write_text(json.dumps({'date': day, 'fold': TB.fold_for_date(day), 'cnt': dict(cnt), 'failed': failed, 'ep': eps},
                                  separators=(',', ':')))
        tmp.replace(out)
        if (k + 1) % 25 == 0:
            H.log({'stage': 'progress', 'shard': shard, 'done': k + 1, 'total': len(mine), 'elapsed_s': round(time.monotonic() - t0)})
    H.log({'stage': 'complete', 'shard': shard})


if __name__ == '__main__':
    main()
