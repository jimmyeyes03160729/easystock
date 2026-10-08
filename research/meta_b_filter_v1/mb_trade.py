"""META_B_FILTER_V1 trade replay: runway B's own exits (manager.py at 6aa1e5a) on archived trade ticks. No I/O.

The exit state machine mirrors ``PositionManagerV2.update_price`` exactly: triggers use trade prices relative to the
signal price (B's ``entry_price``). Fills differ by convention only:
  * QUOTE (primary): buy at the best ask of the latest tick <= t; every sell leg at the bid of its triggering tick.
  * TRADE (secondary, as live B): buy at the signal price; sell legs at the triggering trade price.
The 12:55 force exit uses this symbol's own latest tick <= 12:55:00 (the live runner's highest-price defect is not
copied).
"""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal

import paper_execution as pe

POSITION_TWD = 300_000.0          # runway_v2.config DEFAULT_POSITION_AMOUNT
TAKE_PROFIT_HALF_PCT = 0.015      # TAKE_PROFIT_HALF_PCT
TRAILING_TRIGGER_PCT = 0.020      # TRAILING_TRIGGER_PCT
TRAILING_PULLBACK_PCT = 0.008     # TRAILING_PULLBACK_PCT
FORCE_EXIT_SEC = 12 * 3600 + 55 * 60


def b_shares(price: float) -> int:
    """PositionManagerV2.open_position sizing."""
    return max(1000, int(POSITION_TWD // (price * 1000)) * 1000)


def exit_path(tus, prices, t_us: int, day0_us: int, signal_price: float, stop: float, shares: int):
    """Legs [(tick_index, shares, reason)] closing the position opened at t; mirrors update_price.

    Ticks strictly after t are processed in order; the first tick at or after 12:55:00 ends the loop and the
    remainder is closed at the latest tick <= 12:55:00 (index -1 means: no tick after entry before 12:55, close at
    the latest tick <= 12:55:00 overall, which may be the entry tick).
    """
    force_us = day0_us + FORCE_EXIT_SEC * 1_000_000
    highest, half_closed, trailing = signal_price, False, False
    legs = []
    k = bisect_right(tus, t_us)
    while k < len(tus) and tus[k] < force_us:
        p = prices[k]
        if p > highest:
            highest = p
        if p <= stop:
            legs.append((k, shares, 'breakeven' if half_closed else 'stop'))
            return legs
        ret = p / signal_price - 1.0
        if not half_closed and ret >= TAKE_PROFIT_HALF_PCT:
            half = shares // 2
            if half >= 1000:
                half_closed = True
                shares -= half
                stop = max(stop, signal_price)
                legs.append((k, half, 'half_take_profit'))
                k += 1
                continue            # live update_price returns right after the partial exit
        if ret >= TRAILING_TRIGGER_PCT:
            trailing = True
        if trailing and (highest - p) / highest >= TRAILING_PULLBACK_PCT:
            legs.append((k, shares, 'trailing'))
            return legs
        k += 1
    j = bisect_right(tus, force_us) - 1
    legs.append((j, shares, 'force_exit'))
    return legs


def _bid_at(ticks, k: int) -> float | None:
    if ticks.valid(k):
        return ticks.bid[k]
    q = ticks.quote_at(ticks.tus[k], max_age_us=None)
    return ticks.bid[q] if q is not None else None


def settle(buy_px: float, sells, shares: int):
    """Net TWD and bps of entry notional for one buy and its sell legs [(price, shares)], paper_execution costs."""
    buy_amt = Decimal(str(buy_px)) * shares
    cost = pe.fee(buy_amt)
    proceeds = Decimal(0)
    for px, sh in sells:
        amt = Decimal(str(px)) * sh
        proceeds += amt
        cost += pe.fee(amt) + pe.tax(amt)
    net = proceeds - buy_amt - cost
    return float(net), float(net / buy_amt * 10000), float(buy_amt)


def replay(ticks, t_us: int, day0_us: int, signal_price: float, stop: float):
    """Both fill conventions for a B entry decided at t with B's own stop_price. None without a fresh entry quote."""
    q = ticks.quote_at(t_us)
    if q is None:
        return None
    shares = b_shares(signal_price)
    legs = exit_path(ticks.tus, ticks.price, t_us, day0_us, signal_price, stop, shares)
    if legs[-1][0] < 0:
        return None
    quote_sells, trade_sells = [], []
    for k, sh, _ in legs:
        bid = _bid_at(ticks, k)
        if bid is None or bid <= 0:
            return None
        quote_sells.append((bid, sh))
        trade_sells.append((ticks.price[k], sh))
    qn, qb, qamt = settle(ticks.ask[q], quote_sells, shares)
    tn, tb, tamt = settle(signal_price, trade_sells, shares)
    return {
        'shares': shares, 'stop': stop, 'entry_ask': ticks.ask[q], 'entry_bid': ticks.bid[q],
        'entry_quote_us': ticks.tus[q],
        'legs': [{'us': ticks.tus[k], 'shares': sh, 'reason': r, 'bid': b[0], 'trade': tr[0]}
                 for (k, sh, r), b, tr in zip(legs, quote_sells, trade_sells)],
        'exit_us': ticks.tus[legs[-1][0]],
        'quote': {'net_twd': qn, 'bps': qb, 'buy_twd': qamt},
        'trade': {'net_twd': tn, 'bps': tb, 'buy_twd': tamt},
    }
