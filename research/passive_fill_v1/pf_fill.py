"""PASSIVE_FILL_V1 fill model on archived trade ticks (research only, no I/O).

Quotes are only observed at trade ticks, so the quote "at" a time is the bid/ask carried by the latest trade
tick at or before it. A resting limit order joins the back of the queue at its price; it fills when a later
trade prints through the price (STRICT and QUEUE) or, in the QUEUE model only, when trades initiated against
the resting side at exactly that price have consumed the displayed queue ahead plus our own lot.
Cancellations ahead of us are ignored (conservative).
"""
from __future__ import annotations

from bisect import bisect_right

MAX_AGE_US = 30_000_000
BUY, SELL = 1, -1
SELLER_INITIATED, BUYER_INITIATED = 2, 1     # Shioaji tick_type
POLICIES = ('TAKER', 'PF60', 'PF300', 'PS60', 'PS300')
WAIT_US = {'PF60': 60_000_000, 'PF300': 300_000_000, 'PS60': 60_000_000, 'PS300': 300_000_000}
MODELS = ('QUEUE', 'STRICT')


class Ticks:
    """Parallel trade-tick arrays for one symbol-day, sorted by time."""

    def __init__(self, tus, price, vol, ttype, bid, ask, bidv, askv):
        self.tus, self.price, self.vol, self.ttype = tus, price, vol, ttype
        self.bid, self.ask, self.bidv, self.askv = bid, ask, bidv, askv

    def valid(self, i) -> bool:
        return self.bid[i] > 0 and self.ask[i] > 0 and self.bid[i] < self.ask[i]

    def quote_at(self, t_us, max_age_us=MAX_AGE_US):
        """Index of the latest tick <= t with a valid two-sided quote and age <= max_age (None: no limit)."""
        i = bisect_right(self.tus, t_us) - 1
        while i >= 0 and not self.valid(i):
            i -= 1
        if i < 0 or (max_age_us is not None and t_us - self.tus[i] > max_age_us):
            return None
        return i


def passive_fill(ticks: Ticks, side: int, limit: float, queue_ahead: int, start_us: int, end_us: int,
                 model: str = 'QUEUE', lots: int = 1):
    """Fill time of a resting limit order over (start_us, end_us], else None."""
    lo, hi = bisect_right(ticks.tus, start_us), bisect_right(ticks.tus, end_us)
    against = SELLER_INITIATED if side == BUY else BUYER_INITIATED
    need, done = max(0, queue_ahead) + lots, 0
    for k in range(lo, hi):
        p = ticks.price[k]
        if (side == BUY and p < limit) or (side == SELL and p > limit):
            return ticks.tus[k]
        if model == 'QUEUE' and p == limit and ticks.ttype[k] == against:
            done += ticks.vol[k]
            if done >= need:
                return ticks.tus[k]
    return None


def _leg(ticks: Ticks, side: int, t_us: int, wait_us: int, model: str):
    """Passive leg posted at the touch at t, falling back to crossing the spread at t + wait.

    Returns (price, passive_filled) or None when no fallback quote exists.
    """
    i = ticks.quote_at(t_us)
    limit = ticks.bid[i] if side == BUY else ticks.ask[i]
    queue = ticks.bidv[i] if side == BUY else ticks.askv[i]
    if passive_fill(ticks, side, limit, queue, t_us, t_us + wait_us, model) is not None:
        return limit, True
    j = ticks.quote_at(t_us + wait_us, max_age_us=None)
    return (ticks.ask[j] if side == BUY else ticks.bid[j]), False


def simulate(ticks: Ticks, t_us: int, h_us: int, model: str):
    """All policies for one LONG round trip decided at t and exited at t + h.

    Returns None when either touch quote (at t or at t + h, age <= 30s) is missing; otherwise
    {'mid0', 'mid1', policy: (entry, exit, entry_passive, exit_passive) or None when skipped}.
    """
    i0, i1 = ticks.quote_at(t_us), ticks.quote_at(t_us + h_us)
    if i0 is None or i1 is None:
        return None
    out = {'mid0': (ticks.bid[i0] + ticks.ask[i0]) / 2, 'mid1': (ticks.bid[i1] + ticks.ask[i1]) / 2,
           'TAKER': (ticks.ask[i0], ticks.bid[i1], False, False)}
    for pol in POLICIES[1:]:
        w = WAIT_US[pol]
        entry_px, entry_passive = _leg(ticks, BUY, t_us, w, model)
        if pol.startswith('PS') and not entry_passive:
            out[pol] = None
            continue
        exit_px, exit_passive = _leg(ticks, SELL, t_us + h_us, w, model)
        out[pol] = (entry_px, exit_px, entry_passive, exit_passive)
    return out
