"""META_B_FILTER_V1 per-symbol pass: production radar each minute, frozen B rule, level-1 checks, trade replay and
the symbol's own decision-time features. No I/O; radar and rule functions are injected."""
from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right

from daytrade_learning.event_audit import bars as BARS

import mb_common as M
import mb_trade as T

GRID_MINUTES = range(9 * 60 + 5, 12 * 60 + 30 + 1)   # decision points 09:05:03 .. 12:30:03
GRID_SECOND = 3
RADAR_WINDOW_SEC = 420         # compute_volume_surge_metrics looks back max(RADAR_HISTORY_SECONDS, 60*(4+2))
MAX_SPREAD_TICKS = 2            # runway_v2.config defaults
MAX_SPREAD_PCT = 0.0060
MIN_BID1_VOLUME = 3


def minute_us(day0_us: int, minute: int, second: int) -> int:
    return day0_us + (minute * 60 + second) * 1_000_000


def level1_check(ticks, q: int):
    """runway_v2.orderbook.validate_orderbook on level 1 only (spread ticks, spread pct, bid-1 size); OBI skipped."""
    ob = M.pinned('orderbook').OrderBookSnapshot(symbol='', dt_str='', bid_prices=[ticks.bid[q]], bid_volumes=[int(ticks.bidv[q])],
                           ask_prices=[ticks.ask[q]], ask_volumes=[int(ticks.askv[q])])
    if ob.spread_ticks > MAX_SPREAD_TICKS:
        return 'spread_ticks'
    if ob.spread_ticks > 1 and ob.spread_pct > MAX_SPREAD_PCT:
        return 'spread_pct'
    if ob.bid1_vol < MIN_BID1_VOLUME:
        return 'bid1_volume'
    return None


def prev_day_features(daily_rows, day: str):
    """(prev_day_return_pct, prev_day_close_location) from the latest official bar strictly before day."""
    prev = [r for r in daily_rows or [] if r[0] < day]
    if not prev:
        return None, None
    d, h, l, c, ref, _ = prev[-1]
    base = ref if ref else (prev[-2][3] if len(prev) >= 2 else None)
    ret = (c / base - 1) * 100 if base and c else None
    loc = 0.5 if (h is None or l is None or h == l) else ((c - l) / (h - l) if c is not None else None)
    return ret, loc


class SymbolDay:
    """Precomputed arrays for one archived symbol-day."""

    def __init__(self, sym, ticks, kbars, day0_us):
        self.sym, self.ticks, self.d0 = sym, ticks, day0_us
        self.secs = [u / 1e6 for u in ticks.tus]
        self.events = [(s, float(v), int(tt), float(p), float(v) * float(p) * 1000)
                       for s, v, tt, p in zip(self.secs, ticks.vol, ticks.ttype, ticks.price)]
        self.bars1 = BARS.build_minute_bars(kbars, day0_us)
        first = min(self.bars1) if self.bars1 else None
        self.session_open = self.bars1[first][0] if first is not None else None
        self.session_open_end_us = self.bars1[first][5] if first is not None else None
        hi, lo, h, l = [], [], -math.inf, math.inf
        for p in ticks.price:
            h, l = max(h, p), min(l, p)
            hi.append(h)
            lo.append(l)
        self.hi, self.lo = hi, lo

    def last_index(self, t_us):
        return bisect_right(self.ticks.tus, t_us) - 1

    def price_at(self, t_us):
        i = self.last_index(t_us)
        return self.ticks.price[i] if i >= 0 else None

    def radar(self, compute, t_us):
        t = t_us / 1e6
        lo, hi = bisect_left(self.secs, t - RADAR_WINDOW_SEC), bisect_right(self.secs, t)
        return compute(self.events[lo:hi], t) if hi > lo else None

    def kbars5(self, t_us):
        done = {s: b for s, b in self.bars1.items() if b[5] <= t_us}
        return BARS.strip(BARS.group_complete(done, 5))

    def opened(self, t_us):
        return self.session_open if self.session_open_end_us is not None and self.session_open_end_us <= t_us else None


def own_features(sd: SymbolDay, t_us, minute, signal, radar, q, reference, trailing_range, prev_ret, prev_loc):
    price = signal['price']

    def ret_back(sec):
        # Amendment 1: before the session's first trade + h, the reference is that first trade (return since open).
        p = sd.price_at(t_us - sec * 1_000_000) or (sd.ticks.price[0] if sd.ticks.tus[0] <= t_us else None)
        return (price / p - 1) * 100 if p else None

    i = sd.last_index(t_us)
    so = sd.opened(t_us)
    ask, bid = sd.ticks.ask[q], sd.ticks.bid[q]
    surge, amount = radar.get('surge_60s'), radar.get('amount_60s')
    rng = (sd.hi[i] - sd.lo[i]) / reference / trailing_range if (i >= 0 and trailing_range) else None
    return {
        'b_score': signal['score'],
        'is_orb': 1.0 if signal['signal_type'] == 'ORB_BREAKOUT' else 0.0,
        'gain_pct': signal['gain_pct'],
        'vwap_dist_pct': (price / signal['vwap'] - 1) * 100 if signal.get('vwap') else None,
        'buy_ratio_60s': radar.get('buy_ratio_60s'),
        'log_surge_60s': math.log(surge) if surge and surge > 0 else None,
        'log_amount_60s': math.log(amount) if amount and amount > 0 else None,
        'return_5m_pct': ret_back(300),
        'return_15m_pct': ret_back(900),
        'minutes_since_0900': (t_us - sd.d0) / 60e6 - 540.0,
        'gap_open_pct': (so / reference - 1) * 100 if so else None,
        'range_so_far_rel': rng,
        'trailing_range_20': trailing_range,
        'spread_bps_l1': (ask - bid) / ((ask + bid) / 2) * 1e4,
        'prev_day_return_pct': prev_ret,
        'prev_day_close_location': prev_loc,
    }


def scan_symbol(sd: SymbolDay, reference, trailing_range, daily_rows, day, compute, qualifies, score, evaluate, cnt):
    """Per-minute radar rows (qualified only), per-minute (price, session open) and B firings with replays."""
    prev_ret, prev_loc = prev_day_features(daily_rows, day)
    radar_rows, marks, firings = {}, {}, []
    for minute in GRID_MINUTES:
        t_us = minute_us(sd.d0, minute, GRID_SECOND)
        marks[minute] = (sd.price_at(t_us), sd.opened(t_us))
        radar = sd.radar(compute, t_us)
        if not radar or not qualifies(radar):
            continue
        radar_rows[minute] = (score(radar), float(radar.get('surge_60s') or 0.0), float(radar.get('amount_60s') or 0.0))
        price = sd.price_at(t_us)
        if price is None:
            continue
        time_str = '%02d:%02d:%02d' % (minute // 60, minute % 60, GRID_SECOND)
        signal = evaluate(symbol=sd.sym, name=sd.sym, current_price=price, previous_close=reference,
                          current_time_str=time_str, kbars5=sd.kbars5(t_us), radar_metrics=radar, orderbook=None)
        if not signal:
            continue
        cnt['B_SIGNAL'] += 1
        q = sd.ticks.quote_at(t_us)
        if q is None:
            cnt['REJECT:no_fresh_quote'] += 1
            continue
        why = level1_check(sd.ticks, q)
        if why:
            cnt['REJECT:l1_' + why] += 1
            continue
        trade = T.replay(sd.ticks, t_us, sd.d0, price, signal['stop_price'])
        if trade is None:
            cnt['REJECT:no_exit_quote'] += 1
            continue
        cnt['B_FIRING'] += 1
        firings.append({
            'sym': sd.sym, 'minute': minute, 't_us': t_us, 'signal_type': signal['signal_type'],
            'b_score': signal['score'], 'price': price,
            'features': own_features(sd, t_us, minute, signal, radar, q, reference, trailing_range, prev_ret, prev_loc),
            'shares': trade['shares'], 'exit_us': trade['exit_us'], 'legs': trade['legs'],
            'quote': trade['quote'], 'trade': trade['trade'],
        })
    return radar_rows, marks, firings


def assemble_day(per_symbol, top_n: int):
    """Cross-symbol pass: radar top-N per minute, radar_rank and pool features for each firing in the top-N."""
    by_minute = {}
    for sym, (rows, _, _) in per_symbol.items():
        for minute, key in rows.items():
            by_minute.setdefault(minute, []).append((key, sym))
    rank = {}
    for minute, lst in by_minute.items():
        lst.sort(key=lambda x: x[0], reverse=True)
        for r, (_, sym) in enumerate(lst[:top_n], 1):
            rank[(minute, sym)] = r
    pool = {}
    out = []
    for sym, (_, _, firings) in per_symbol.items():
        for f in firings:
            r = rank.get((f['minute'], sym))
            if r is None:
                continue
            m = f['minute']
            if m not in pool:
                rets = [(p / o - 1) * 100 for (p, o) in (v[1].get(m, (None, None)) for v in per_symbol.values())
                        if p and o]
                pool[m] = (sum(x > 0 for x in rets) / len(rets), statistics.median(rets)) if rets else (None, None)
            g = dict(f)
            g['radar_rank'] = r
            g['features'] = dict(f['features'], radar_rank=float(r), pool_up_from_open_share=pool[m][0],
                                 pool_median_return_from_open_pct=pool[m][1])
            out.append(g)
    out.sort(key=lambda f: (f['t_us'], f['radar_rank']))
    return out
