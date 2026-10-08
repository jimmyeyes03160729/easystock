"""PASSIVE_FILL_V1 fill model: queue/strict fills, fallback, skip and quote staleness."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'research' / 'passive_fill_v1'))
import pf_fill as F  # noqa: E402

S = 1_000_000


def ticks(rows):
    """rows: (sec, price, vol, tick_type, bid, ask, bidv, askv)."""
    cols = list(zip(*rows))
    return F.Ticks([c * S for c in cols[0]], *[list(c) for c in cols[1:]])


def test_quote_at_respects_age_and_skips_invalid_quotes():
    t = ticks([(0, 10.0, 1, 1, 9.9, 10.0, 5, 5), (10, 10.0, 1, 1, 0.0, 10.0, 0, 5)])
    assert t.quote_at(20 * S) == 0          # tick 1 has no bid, falls back to tick 0 (age 20s)
    assert t.quote_at(31 * S) is None       # age 31s > 30s
    assert t.quote_at(99 * S, max_age_us=None) == 0
    assert t.quote_at(-1) is None


def test_queue_model_needs_queue_ahead_plus_own_lot():
    t = ticks([(0, 10.0, 1, 1, 9.9, 10.0, 3, 5),
               (5, 9.9, 2, 2, 9.9, 10.0, 1, 5),     # sellers hit 2 of the 3 ahead
               (6, 9.9, 1, 1, 9.9, 10.0, 1, 5),     # buyer-initiated print at 9.9 does not consume the bid queue
               (8, 9.9, 1, 2, 9.9, 10.0, 0, 5),     # queue ahead gone, our lot still waiting
               (9, 9.9, 1, 2, 9.8, 9.9, 0, 5)])     # our lot fills
    assert F.passive_fill(t, F.BUY, 9.9, 3, 0, 60 * S, 'QUEUE') == 9 * S
    assert F.passive_fill(t, F.BUY, 9.9, 3, 0, 8 * S, 'QUEUE') is None
    assert F.passive_fill(t, F.BUY, 9.9, 3, 0, 60 * S, 'STRICT') is None


def test_trade_through_fills_in_both_models_and_sell_side_mirrors():
    t = ticks([(0, 10.0, 1, 1, 9.9, 10.0, 50, 50), (3, 9.8, 1, 2, 9.8, 9.9, 5, 5), (4, 10.1, 1, 1, 10.0, 10.1, 5, 5)])
    for model in F.MODELS:
        assert F.passive_fill(t, F.BUY, 9.9, 50, 0, 60 * S, model) == 3 * S
        assert F.passive_fill(t, F.SELL, 10.0, 50, 0, 60 * S, model) == 4 * S
    assert F.passive_fill(t, F.BUY, 9.9, 50, 3 * S, 60 * S, 'QUEUE') is None   # start is exclusive


def test_simulate_policies_fallback_and_skip():
    rows = [(0, 10.0, 1, 1, 9.9, 10.0, 1, 1),
            (30, 9.9, 5, 2, 9.9, 10.0, 0, 1),          # entry bid queue consumed -> passive buy at 9.9 within 60s
            (900, 10.2, 1, 1, 10.1, 10.2, 1, 9),       # exit touch at t+15m: ask 10.2, queue 9
            (1000, 10.3, 1, 1, 10.2, 10.3, 1, 9)]      # prints through 10.2 -> passive sell at 10.2
    sim = F.simulate(ticks(rows), 0, 900 * S, 'QUEUE')
    assert sim['mid0'] == pytest.approx(9.95) and sim['mid1'] == pytest.approx(10.15)
    assert sim['TAKER'] == (10.0, 10.1, False, False)
    assert sim['PF60'] == (9.9, 10.1, True, False)       # exit print at +100s is after the 60s wait: cross at the 10.1 bid
    assert sim['PF300'] == (9.9, 10.2, True, True)
    assert sim['PS60'] == (9.9, 10.1, True, False)
    strict = F.simulate(ticks(rows), 0, 900 * S, 'STRICT')
    assert strict['PS60'] is None and strict['PS300'] is None     # no trade-through below 9.9
    assert strict['PF60'][0] == 10.0 and strict['PF60'][2] is False


def test_simulate_requires_fresh_touch_at_entry_and_exit():
    rows = [(0, 10.0, 1, 1, 9.9, 10.0, 1, 1), (500, 10.0, 1, 1, 9.9, 10.0, 1, 1)]
    assert F.simulate(ticks(rows), 0, 900 * S, 'QUEUE') is None
    assert F.simulate(ticks(rows), 100 * S, 900 * S, 'QUEUE') is None
