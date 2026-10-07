"""Event-audit toolkit: frozen time/cost/bar/episode/markout/classification conventions."""
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from daytrade_learning.event_audit import bars, classify, costs, episodes, markouts, timebase

DAY = '2026-03-24'
D0 = timebase.day0_us(DAY)


def us(hh, mm, ss=0):
    return D0 + (hh * 3600 + mm * 60 + ss) * 1_000_000


def kbars(start_hhmm=(9, 0), minutes=60, skip=()):
    """Archive-style 1m kbars; ts is the bar END in naive-Taiwan nanoseconds."""
    ts, o, h, l, c, v = [], [], [], [], [], []
    base = start_hhmm[0] * 60 + start_hhmm[1]
    for i in range(minutes):
        if i in skip:
            continue
        end_sec = (base + i + 1) * 60
        ts.append((D0 + end_sec * 1_000_000) * 1000)
        o.append(100.0 + i)
        h.append(101.0 + i)
        l.append(99.0 + i)
        c.append(100.5 + i)
        v.append(10.0)
    return {'ts': ts, 'Open': o, 'High': h, 'Low': l, 'Close': c, 'Volume': v}


# ---------------------------------------------------------------- timebase
def test_timestamp_convention_is_naive_taiwan_wall_clock():
    # first 1m bar of the 2026-03-20 archive sample (end label 09:01)
    assert timebase.ns_to_naive(1773997260000000000) == datetime(2026, 3, 20, 9, 1, 0)
    assert timebase.iso_from_us(1773997260000000) == '2026-03-20T09:01:00'


def test_fold_windows_cover_edges_and_gaps():
    f = timebase.fold_for_date
    assert f('2024-12-24') == 0 and f('2024-12-25') == 1 and f('2025-04-30') == 1
    assert f('2025-05-02') == 2 and f('2026-05-06') == 5 and f('2026-08-27') == 5
    assert f('2026-08-28') == -1
    assert len(timebase.CORE_UNIVERSE) == 42 and len(set(timebase.CORE_UNIVERSE)) == 42


def test_gap_day_between_windows_is_not_a_test_day():
    assert timebase.fold_for_date('2025-05-01') == -1


# ---------------------------------------------------------------- costs
def test_costs_match_frozen_audit_anchors():
    assert costs.cost_pct(45.25, 45.4) == (0.3314917127071823, 0.09281767955801104)
    g, n = costs.cost_pct(58.6, 58.3)
    assert (g, n) == (-0.5119453924914675, -0.7389078498293515)


def test_quote_stress_uses_ask_in_bid_out():
    gross, net = costs.cost_quote_pct(46.0, 45.5)
    assert gross < 0 and net < gross


def test_costs_reject_bad_prices():
    with pytest.raises(ValueError):
        costs.cost_pct(0, 10)
    with pytest.raises(ValueError):
        costs.cost_pct(float('nan'), 10)


# ---------------------------------------------------------------- bars
def test_group_complete_aligns_to_nine_and_marks_end():
    rows = bars.group_complete(bars.build_minute_bars(kbars(minutes=15), D0), 5)
    assert [r['_end_sec'] for r in rows] == [9 * 3600 + 300, 9 * 3600 + 600, 9 * 3600 + 900]
    assert rows[0]['open'] == 100.0 and rows[0]['close'] == 104.5 and rows[0]['volume'] == 50.0


def test_bucket_with_missing_minute_is_dropped_not_filled():
    rows = bars.group_complete(bars.build_minute_bars(kbars(minutes=15, skip={7}), D0), 5)
    assert [r['_end_sec'] for r in rows] == [9 * 3600 + 300, 9 * 3600 + 900]


def test_bars_outside_regular_session_are_ignored():
    pre = kbars(start_hhmm=(8, 50), minutes=15)           # 08:50-09:05
    mins = bars.build_minute_bars(pre, D0)
    assert min(mins) == 9 * 3600


def test_causal_rebuild_detects_lookahead():
    kb = kbars(minutes=30)
    full = bars.group_complete(bars.build_minute_bars(kb, D0), 5)
    decision = us(9, 15)                                   # three 5m bars are complete
    used = bars.strip([r for r in full if r['_end_sec'] * 1_000_000 + D0 <= decision])
    assert len(used) == 3
    assert bars.causal_rows_match(kb, D0, decision, used, 5)
    leaked = bars.strip(full[:4])                          # includes the 09:20 bar
    assert not bars.causal_rows_match(kb, D0, decision, leaked, 5)
    tampered = [dict(used[0], close=used[0]['close'] + 1)] + used[1:]
    assert not bars.causal_rows_match(kb, D0, decision, tampered, 5)


# ---------------------------------------------------------------- episodes
def test_false_to_true_only_and_overlap_boundary():
    t = lambda m: us(10, m)
    states = [(t(0), False), (t(5), True), (t(10), True), (t(15), False), (t(19), True),   # 14m after the accepted t(5): excluded
              (t(21), False), (t(35), True)]                                               # 30m after t(5): allowed
    r = episodes.select_episodes(states)
    assert (r.raw_pass_rows, r.false_to_true, r.overlap_excluded) == (4, 3, 1)
    assert r.accepted == (t(5), t(35))


def test_exactly_horizon_later_is_allowed_and_first_point_counts_from_false():
    r = episodes.select_episodes([(us(10, 0), True), (us(10, 5), False), (us(10, 15), True)])
    assert r.accepted == (us(10, 0), us(10, 15))
    assert r.overlap_excluded == 0


def test_dropped_points_reset_the_state():
    r = episodes.select_episodes([(us(10, 0), True), (us(10, 20), False), (us(10, 35), True)])
    assert r.false_to_true == 2


# ---------------------------------------------------------------- markouts
def ticks(points):
    """points: [(us, price, bid, ask)] -> parallel lists."""
    return ([p[0] for p in points], [p[1] for p in points], [p[2] for p in points], [p[3] for p in points])


def test_entry_never_uses_next_tick_or_stale_tick():
    tus, tp, tb, ta = ticks([(us(10, 0, 0), 50.0, 49.95, 50.0), (us(10, 5, 1), 51.0, 50.9, 51.0)])
    assert markouts.entry_index(tus, us(10, 5, 0)) is None          # last tick is 5 min old, next tick not allowed
    assert markouts.entry_index(tus, us(10, 0, 20)) == 0
    assert markouts.entry_index(tus, us(10, 0, 31)) is None


def test_markouts_gross_exit_and_path_window():
    t0 = us(10, 0)
    pts = [(t0 - 2_000_000, 100.0, 99.9, 100.0),
           (t0, 120.0, 119.9, 120.0),                                 # at decision: NOT path
           (t0 + 60_000_000, 101.0, 100.9, 101.0),
           (t0 + 600_000_000, 99.0, 98.9, 99.0),
           (t0 + 900_000_000, 102.0, 101.9, 102.0),                   # exactly +15m: included
           (t0 + 900_000_001, 150.0, 149.9, 150.0)]                   # after: excluded
    tus, tp, tb, ta = ticks(pts)
    ei = markouts.entry_index(tus, t0)
    assert ei == 1                                                    # tick at the decision instant is causal
    m = markouts.markouts(tus, tp, tb, ta, t0, ei, D0)
    assert m['15m']['status'] == 'OK' and m['15m']['exit_us'] == t0 + 900_000_000
    assert m['15m']['gross'] == pytest.approx((102.0 / 120.0 - 1) * 100)
    assert m['path']['MFE_15M'] == pytest.approx((102.0 / 120.0 - 1) * 100)   # path max is 102 (120 excluded)
    assert m['path']['MAE_15M'] == pytest.approx((99.0 / 120.0 - 1) * 100)
    assert m['path']['time_to_MAE_s'] == 600.0


def test_force_exit_guard_and_missing_markout():
    t0 = us(12, 30)
    tus, tp, tb, ta = ticks([(t0, 50.0, 49.95, 50.0), (t0 + 840_000_000, 50.5, 50.45, 50.5)])
    m = markouts.markouts(tus, tp, tb, ta, t0, 0, D0)
    assert m['30m']['status'] == 'HORIZON_AFTER_FORCE_EXIT' and m['60m']['status'] == 'HORIZON_AFTER_FORCE_EXIT'
    assert m['15m']['status'] == 'MARKOUT_MISSING'                    # the +14m tick is 60s before the target: stale


def test_stale_exit_is_missing_not_substituted():
    t0 = us(10, 0)
    tus, tp, tb, ta = ticks([(t0, 50.0, 49.95, 50.0), (t0 + 840_000_000, 50.5, 50.45, 50.5)])
    m = markouts.markouts(tus, tp, tb, ta, t0, 0, D0)
    assert m['15m']['status'] == 'MARKOUT_MISSING'


def test_quote_stress_requires_sane_book():
    t0 = us(10, 0)
    tus, tp, tb, ta = ticks([(t0, 50.0, 49.95, 50.0), (t0 + 900_000_000, 51.0, 52.0, 51.0)])   # bid > ask at exit
    m = markouts.markouts(tus, tp, tb, ta, t0, 0, D0)
    assert m['15m']['status'] == 'OK' and m['15m']['quote'] is None


# ---------------------------------------------------------------- classification
def _crit(g=10, n=5, q=3, fg=(1, 1, 1, 1, 1), fn=(1, 1, 1, 1, 1), fq=(1, 1, 1, 1, 1), fc=(100,) * 5):
    return classify.criteria(g, n, q, fg, fn, fq, fc)


def test_strong_requires_every_criterion():
    c = _crit(g=35, n=5, q=3)
    assert classify.classify(c) == 'STRONG_ENTRY_CANDIDATE'


def test_rule_order_insufficient_before_no_edge():
    assert classify.classify(_crit(g=-5, fc=(100, 100, 100, 100, 29))) == 'INSUFFICIENT_EVENTS'
    assert classify.classify(_crit(g=-5)) == 'NO_ENTRY_EDGE'
    assert classify.classify(_crit(g=0)) == 'NO_ENTRY_EDGE'


def test_weak_vs_cost_blocked():
    # gross>0 but below 30 bps -> weak even if 5/5 folds positive
    assert classify.classify(_crit(g=12, n=-20, q=-30, fn=(0,) * 5, fq=(0,) * 5)) == 'WEAK_OR_UNSTABLE'
    # unstable folds -> weak
    assert classify.classify(_crit(g=40, fg=(1, 1, 1, 0, 0))) == 'WEAK_OR_UNSTABLE'
    # strong gross, stable, but costs eat it -> cost blocked
    assert classify.classify(_crit(g=40, n=-5, q=-20, fn=(0,) * 5, fq=(0,) * 5)) == 'GROSS_EDGE_COST_BLOCKED'


def test_fold_positive_counts_ignore_missing_folds():
    c = _crit(g=40, fg=(1, 1, 1, None, None))
    assert c['B_gross_pos_ge_4_of_5_folds'] is False
