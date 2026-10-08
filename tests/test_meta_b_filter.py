"""META_B_FILTER_V1 research code on synthetic data: pins, B exit replay vs PositionManagerV2, costs, causality,
cross-symbol assembly, statistics, portfolio constraints and classification."""
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'research' / 'meta_b_filter_v1'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'research' / 'passive_fill_v1'))
sys.path.insert(0, str(STUDY))
import mb_common as M  # noqa: E402  (no environment or sys.path side effects at import)
import paper_execution as pe  # noqa: E402
import pf_fill as F  # noqa: E402
import mb_trade as T  # noqa: E402
import mb_signal as S  # noqa: E402
import mb_stats as ST  # noqa: E402
from daytrade_learning.event_audit import timebase as TB  # noqa: E402

DAY = '2025-03-03'
D0 = TB.day0_us(DAY)


def at(h, m, s=0):
    return D0 + ((h * 60 + m) * 60 + s) * 1_000_000


def make_ticks(points, spread=0.5, bidv=10, askv=10):
    """points: [(us, price)] -> pf_fill.Ticks with a constant one-tick spread around the trade price."""
    tus = [u for u, _ in points]
    px = [p for _, p in points]
    n = len(points)
    return F.Ticks(tus, px, [1] * n, [1] * n, [p - spread for p in px], [p for p in px], [bidv] * n, [askv] * n)


def test_vendored_runway_files_match_preregistered_blobs():
    info = M.verify_pins()
    assert info['blobs'] == M.PINNED_BLOBS
    assert 'runway_v2' not in sys.modules or 'meta_b_filter_v1' not in sys.modules['runway_v2'].__file__


def test_git_blob_sha_matches_git(tmp_path):
    p = tmp_path / 'empty'
    p.write_bytes(b'')
    assert M.git_blob_sha(p) == 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391'


def _manager_legs(prices, entry, stop, shares, tmp_path):
    mgr = M.pinned('manager').PositionManagerV2(db_path=tmp_path / 'ledger.sqlite')
    mgr.open_position(symbol='9999', name='x', price=entry, dt_str='t', signal_type='ORB_BREAKOUT', score=70,
                      reasons=[], stop_price=stop)
    assert mgr.positions['9999'].shares == shares
    legs = []
    for k, p in enumerate(prices):
        ev = mgr.update_price('9999', p, 't%d' % k)
        if ev:
            legs.append((k, ev['shares'], ev['reason']))
            if not ev['is_partial']:
                return legs
    ev = mgr.update_price('9999', prices[-1], 'force', force_exit=True)
    legs.append((len(prices) - 1, ev['shares'], ev['reason']))
    return legs


REASON = {'停損出場': 'stop', '保本出場': 'breakeven', '分批停利 50%': 'half_take_profit',
          '移動停利出場': 'trailing', '收盤強制平倉': 'force_exit'}


@pytest.mark.parametrize('seed', range(40))
def test_exit_path_matches_position_manager(seed, tmp_path):
    rng = random.Random(seed)
    entry = rng.choice([23.4, 58.2, 101.0, 312.5])
    prices, p = [], entry
    for _ in range(rng.randint(5, 120)):
        p = round(max(1.0, p * (1 + rng.gauss(0.0005, 0.006))), 2)
        prices.append(p)
    stop = round(entry * 0.985, 2)
    shares = T.b_shares(entry)
    t = at(9, 10)
    tus = [t + (k + 1) * 10_000_000 for k in range(len(prices))]       # all before 12:55
    mine = T.exit_path(tus, prices, t, D0, entry, stop, shares)
    theirs = _manager_legs(prices, entry, stop, shares, tmp_path)
    assert [(k, sh, r) for k, sh, r in mine] == [(k, sh, REASON[r]) for k, sh, r in theirs]


def test_force_exit_uses_own_latest_tick_at_1255():
    pts = [(at(12, 50), 100.0), (at(12, 54, 59), 101.0), (at(12, 55), 100.5), (at(12, 56), 99.0)]
    legs = T.exit_path([u for u, _ in pts], [p for _, p in pts], at(12, 49), D0, 100.0, 98.5, 3000)
    assert legs == [(2, 3000, 'force_exit')]


def test_replay_quote_and_trade_conventions_and_costs():
    pts = [(at(9, 10, 1), 100.0), (at(9, 11), 101.6), (at(9, 12), 100.0)]
    ticks = make_ticks(pts)
    r = T.replay(ticks, at(9, 10, 3), D0, 100.0, 98.5)
    # half at +1.6% (1000 of 3000 shares -> half = 1500), then breakeven stop at 100.0 for the rest
    assert [(l['shares'], l['reason']) for l in r['legs']] == [(1500, 'half_take_profit'), (1500, 'breakeven')]
    buy = Decimal('100.0') * 3000
    sells = [(Decimal('101.1'), 1500), (Decimal('99.5'), 1500)]
    cost = pe.fee(buy) + sum(pe.fee(p * s) + pe.tax(p * s) for p, s in sells)
    net = sum(p * s for p, s in sells) - buy - cost
    assert r['quote']['net_twd'] == pytest.approx(float(net))
    assert r['quote']['bps'] == pytest.approx(float(net / buy * 10000))
    assert r['entry_ask'] == 100.0 and r['legs'][0]['bid'] == 101.1


def test_replay_needs_fresh_entry_quote():
    ticks = make_ticks([(at(9, 0, 0), 100.0), (at(9, 20), 101.0)])
    assert T.replay(ticks, at(9, 10, 3), D0, 100.0, 98.5) is None        # last quote 10 minutes old


def test_level1_check():
    # tick size follows the bid (runway_v2.orderbook.get_tick_size(bid))
    assert S.level1_check(make_ticks([(at(9, 10), 200.0)], spread=0.5, bidv=5), 0) is None
    assert S.level1_check(make_ticks([(at(9, 10), 200.0)], spread=1.5), 0) == 'spread_ticks'
    assert S.level1_check(make_ticks([(at(9, 10), 100.0)], spread=0.5), 0) == 'spread_ticks'   # bid 99.5 -> 0.1 tick
    assert S.level1_check(make_ticks([(at(9, 10), 20.0)], spread=0.10), 0) is None
    assert S.level1_check(make_ticks([(at(9, 10), 10.5)], spread=0.10), 0) == 'spread_pct'     # 2 ticks, 0.96%
    assert S.level1_check(make_ticks([(at(9, 10), 200.0)], bidv=2), 0) == 'bid1_volume'


def _kbars(start_min, n, price):
    ts = [(D0 + (start_min + k + 1) * 60_000_000) * 1000 for k in range(n)]      # archive ts = bar END in ns
    return {'ts': ts, 'Open': [price] * n, 'High': [price + 1] * n, 'Low': [price - 1] * n,
            'Close': [price] * n, 'Volume': [10.0] * n}


def test_scan_symbol_is_causal_and_builds_features():
    pts = [(at(9, 0) + k * 5_000_000, 100.0 + 0.01 * k) for k in range(0, 2900)]     # 09:00 .. 13:01
    ticks = make_ticks(pts)
    sd = S.SymbolDay('1234', ticks, _kbars(9 * 60, 240, 100.0), D0)
    seen = []

    def compute(events, now):
        assert all(e[0] <= now for e in events)
        return {'surge_60s': 2.0, 'buy_ratio_60s': 0.9, 'amount_60s': 5e6, 'volume_60s': 50}

    def evaluate(**kw):
        t_us = S.minute_us(D0, int(kw['current_time_str'][:2]) * 60 + int(kw['current_time_str'][3:5]), 3)
        assert len(kw['kbars5']) == ((t_us - at(9, 0)) // 1_000_000) // 300
        seen.append(kw['current_time_str'])
        if kw['current_time_str'] != '09:40:03':
            return None
        return {'price': kw['current_price'], 'gain_pct': 1.5, 'vwap': 100.0, 'signal_type': 'VWAP_PULLBACK',
                'score': 70.0, 'stop_price': 99.0}

    from collections import Counter
    cnt = Counter()
    rows, marks, firings = S.scan_symbol(sd, 99.0, 0.03, [('2025-02-27', 100, 98, 99, 98.5, 'TWSE')], DAY,
                                         compute, lambda r: True, lambda r: 50.0, evaluate, cnt)
    assert seen[0] == '09:05:03' and seen[-1] == '12:30:03' and len(seen) == 206
    (f,) = firings
    t40 = at(9, 40, 3)
    assert f['t_us'] == t40 and f['price'] == sd.price_at(t40)
    feats = f['features']
    assert feats['minutes_since_0900'] == pytest.approx(40.05)
    assert feats['return_5m_pct'] == pytest.approx((sd.price_at(t40) / sd.price_at(t40 - 300_000_000) - 1) * 100)
    assert feats['prev_day_return_pct'] == pytest.approx((99 / 98.5 - 1) * 100)
    assert feats['prev_day_close_location'] == pytest.approx(0.5)
    assert feats['gap_open_pct'] == pytest.approx((100.0 / 99.0 - 1) * 100)
    hi_lo = max(p for u, p in pts if u <= t40) - min(p for u, p in pts if u <= t40)
    assert feats['range_so_far_rel'] == pytest.approx(hi_lo / 99.0 / 0.03)


def test_early_returns_fall_back_to_first_trade_of_session():
    pts = [(at(9, 0, 30) + k * 5_000_000, 100.0 + 0.01 * k) for k in range(0, 2900)]
    sd = S.SymbolDay('1234', make_ticks(pts), _kbars(9 * 60, 240, 100.0), D0)
    t = at(9, 6, 3)
    q = sd.ticks.quote_at(t)
    sig = {'price': sd.price_at(t), 'gain_pct': 1.0, 'vwap': 100.0, 'signal_type': 'ORB_BREAKOUT', 'score': 60.0}
    feats = S.own_features(sd, t, 9 * 60 + 6, sig, {'surge_60s': 2.0, 'amount_60s': 2e6, 'buy_ratio_60s': 0.7},
                           q, 99.0, 0.03, None, None)
    assert feats['return_15m_pct'] == pytest.approx((sig['price'] / 100.0 - 1) * 100)      # first trade 09:00:30
    assert feats['return_5m_pct'] == pytest.approx((sig['price'] / sd.price_at(t - 300_000_000) - 1) * 100)


def test_assemble_day_ranks_top_n_and_pool_features():
    def firing(sym, minute):
        return {'sym': sym, 'minute': minute, 't_us': S.minute_us(D0, minute, 3), 'features': {}}
    per = {
        'A': ({600: (90.0, 2.0, 1.0)}, {600: (101.0, 100.0)}, [firing('A', 600)]),
        'B': ({600: (80.0, 2.0, 1.0)}, {600: (99.0, 100.0)}, [firing('B', 600)]),
        'C': ({600: (95.0, 2.0, 1.0)}, {600: (102.0, 100.0)}, []),
    }
    out = S.assemble_day(per, top_n=2)
    assert [(f['sym'], f['radar_rank']) for f in out] == [('A', 2)]          # C ranks 1, B falls outside the top 2
    assert out[0]['features']['pool_up_from_open_share'] == pytest.approx(2 / 3)
    assert out[0]['features']['pool_median_return_from_open_pct'] == pytest.approx(1.0)


def _f(day, sym, t, exit_, bps=10.0, net=100.0, buy=300_000.0, rank=1):
    return {'date': day, 'sym': sym, 't_us': t, 'exit_us': exit_, 'radar_rank': rank,
            'quote': {'bps': bps, 'net_twd': net, 'buy_twd': buy}}


def test_event_level_reentry_only_after_close():
    fs = [_f(DAY, 'A', 1, 10), _f(DAY, 'A', 5, 20), _f(DAY, 'A', 10, 30), _f(DAY, 'A', 11, 40), _f(DAY, 'B', 5, 9)]
    assert [(f['sym'], f['t_us']) for f in ST.event_level(fs)] == [('A', 1), ('B', 5), ('A', 11)]


def test_excess_t_day_clustered():
    rows = [('d1', 10.0), ('d1', -10.0), ('d2', 20.0), ('d2', 0.0), ('d3', 5.0), ('d3', -5.0)]
    ex, se, t = ST.excess_t(rows, [True, False, True, False, True, False])
    assert ex == pytest.approx((10 + 20 + 5) / 3 - 20 / 6)
    assert se > 0 and t == pytest.approx(ex / se)


def test_choose_tau_rules():
    probs = [0.52] * 40 + [0.72] * 30
    rets = [-5.0] * 40 + [8.0] * 30
    assert ST.choose_tau(probs, rets) == 0.70          # 0.55..0.70 tie at +8 -> highest tau with >= 30 picks
    assert ST.choose_tau([0.9] * 10, [1.0] * 10) == 0.50


def test_portfolio_constraints():
    fs = [_f(DAY, s, 1, 100, net=-100.0, rank=r) for r, s in enumerate('ABCD', 1)]
    assert ST.portfolio(fs, lambda f: True)['trades'] == 3                    # max 3 open positions
    big = [_f(DAY, 'A', 1, 2, buy=600_000.0), _f(DAY, 'B', 3, 4, buy=500_000.0), _f(DAY, 'C', 5, 6, buy=300_000.0)]
    assert ST.portfolio(big, lambda f: True)['trades'] == 2                   # 1,000,000 TWD daily buy cap
    loss = [_f(DAY, 'A', 1, 2, net=-6_000.0), _f(DAY, 'B', 3, 4)]
    assert ST.portfolio(loss, lambda f: True)['trades'] == 1                  # loss stop after a -6,000 close
    res = ST.portfolio([_f(DAY, 'A', 1, 2, net=500.0, buy=250_000.0)], lambda f: True)
    assert res['net_twd_per_1m_buys'] == pytest.approx(2000.0)
    assert ST.portfolio(fs, lambda f: f['sym'] == 'D')['trades'] == 1


def test_classification():
    base = dict(A=True, B=True, C=True, D=True, E=True, G=True)
    assert ST.classify(base) == 'PASS_TO_FORWARD'
    assert ST.classify({**base, 'G': False}) == 'INSUFFICIENT'
    assert ST.classify({**base, 'D': False}) == 'NO_FILTER_EDGE'
    assert ST.classify({**base, 'A': False}) == 'FILTER_HELPS_NET_NEGATIVE'
    assert ST.classify({**base, 'C': False}) == 'WEAK'


def _synthetic_work(work, days, rng):
    import gzip, json
    for day in days:
        d0 = TB.day0_us(day)
        firings = []
        for k, sym in enumerate(('1101', '2330')):
            feats = {name: rng.gauss(0, 1) for name in ST.FEATURES}
            bps = 40.0 * feats['b_score'] + rng.gauss(0, 20)            # b_score carries the signal
            t = d0 + (9 * 3600 + 600 + 60 * k) * 1_000_000
            firings.append({'sym': sym, 'minute': 550 + k, 't_us': t, 'exit_us': t + 600_000_000,
                            'radar_rank': k + 1, 'signal_type': 'ORB_BREAKOUT', 'b_score': 60.0, 'price': 100.0,
                            'features': feats, 'shares': 3000, 'legs': [],
                            'quote': {'bps': bps, 'net_twd': bps * 30.0, 'buy_twd': 300_000.0},
                            'trade': {'bps': bps + 5, 'net_twd': (bps + 5) * 30.0, 'buy_twd': 300_000.0}})
        (work / (day + '.json.gz')).write_bytes(gzip.compress(json.dumps(
            {'date': day, 'fold': TB.fold_for_date(day), 'cnt': {'B_FIRING': 2}, 'failed': [], 'firings': firings}).encode()))


def test_finalize_end_to_end_on_synthetic_work(tmp_path, monkeypatch):
    pytest.importorskip('sklearn')
    from datetime import date, timedelta
    import json
    import mb_finalize as FIN
    work, out = tmp_path / 'work', tmp_path / 'output'
    work.mkdir()
    rng = random.Random(7)
    d, days = date(2024, 1, 2), []
    while d <= date(2026, 8, 27):
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    _synthetic_work(work, days, rng)
    monkeypatch.setattr(FIN, 'WORK', work)
    monkeypatch.setattr(FIN, 'OUT', out)
    FIN.main()
    res = json.loads((out / 'META_B_FILTER_V1_STAGE1.json').read_text())
    assert [f['status'] for f in res['folds']] == ['ESTIMATED'] * 5
    assert res['criteria']['D'] is True and res['aggregate']['excess_bps'] > 0
    assert (out / 'FINAL_LINES.txt').read_text().startswith('META_B_FILTER_V1 stage 1 decision: ')
    assert (out / 'BUNDLE_SHA256').exists()


def test_finalize_refuses_days_after_stage1_cutoff(tmp_path, monkeypatch):
    import mb_finalize as FIN
    work = tmp_path / 'work'
    work.mkdir()
    _synthetic_work(work, ['2026-09-01'], random.Random(1))
    monkeypatch.setattr(FIN, 'WORK', work)
    with pytest.raises(SystemExit):
        FIN.load()


def test_criteria_needs_five_estimated_folds_with_30_picks():
    fold = {'status': 'ESTIMATED', 'n_filtered': 30, 'filtered_mean_bps': 5.0, 'all_mean_bps': 1.0}
    agg = {'filtered_mean_bps': 5.0, 'excess_t': 2.5, 'portfolio_filtered': {'net_twd_per_1m_buys': 10.0}}
    assert all(ST.criteria([fold] * 5, agg).values())
    c = ST.criteria([fold] * 4 + [{'status': 'NOT_ESTIMABLE', 'n_filtered': 0}], agg)
    assert c['G'] is False
