"""LONG entry/exit markouts and 15m path metrics from a tick series."""
from __future__ import annotations

import math
from bisect import bisect_right

from . import costs
from .timebase import FORCE_EXIT_SEC

MAX_AGE_US = 30_000_000
HORIZONS = (('5m', 300), ('15m', 900), ('30m', 1800), ('60m', 3600), ('12:55', None))


def entry_index(tus, t_us: int):
    """Index of the latest tick with ts <= t and age <= 30s, else None (never the next tick)."""
    i = bisect_right(tus, t_us) - 1
    if i < 0 or t_us - tus[i] > MAX_AGE_US:
        return None
    return i


def markouts(tus, tprice, tbids, tasks, t_us: int, entry_idx: int, day0_us: int) -> dict:
    """Per-horizon status/gross/net/quote plus 15m MFE/MAE.

    Exit = latest trade at or before the target (age <= 30s); 30m/60m targets after
    12:55 are HORIZON_AFTER_FORCE_EXIT rather than substituted.
    Path metrics only read ticks with decision < ts <= decision+15m.
    """
    entry = tprice[entry_idx]
    force_abs = day0_us + FORCE_EXIT_SEC * 1_000_000
    out = {}
    for name, secs in HORIZONS:
        target = force_abs if name == '12:55' else t_us + secs * 1_000_000
        if name in ('30m', '60m') and target > force_abs:
            out[name] = {'status': 'HORIZON_AFTER_FORCE_EXIT'}
            continue
        xi = bisect_right(tus, target) - 1
        if xi < 0 or target - tus[xi] > MAX_AGE_US:
            out[name] = {'status': 'MARKOUT_MISSING'}
            continue
        gross, net = costs.cost_pct(entry, tprice[xi])
        quote = None
        ask, bid, ebid, xask = tasks[entry_idx], tbids[xi], tbids[entry_idx], tasks[xi]
        if all(math.isfinite(v) and v > 0 for v in (ask, bid, ebid, xask)) and ebid <= ask and bid <= xask:
            quote = costs.cost_quote_pct(ask, bid)[1]
        out[name] = {'status': 'OK', 'gross': gross, 'net': net, 'quote': quote, 'exit_us': tus[xi]}
    lo, hi = bisect_right(tus, t_us), bisect_right(tus, t_us + 900_000_000)
    window = tprice[lo:hi]
    if window:
        top, bottom = max(window), min(window)
        out['path'] = {'MFE_15M': (top / entry - 1) * 100, 'MAE_15M': (bottom / entry - 1) * 100,
                       'time_to_MFE_s': (tus[lo + window.index(top)] - t_us) / 1e6,
                       'time_to_MAE_s': (tus[lo + window.index(bottom)] - t_us) / 1e6}
    else:
        out['path'] = {'MFE_15M': 0.0, 'MAE_15M': 0.0, 'time_to_MFE_s': 0.0, 'time_to_MAE_s': 0.0}
    return out
