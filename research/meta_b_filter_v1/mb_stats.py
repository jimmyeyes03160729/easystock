"""META_B_FILTER_V1 statistics, portfolio simulation and classification (pure functions, frozen criteria)."""
from __future__ import annotations

import math

FEATURES = ('b_score', 'is_orb', 'gain_pct', 'vwap_dist_pct', 'buy_ratio_60s', 'log_surge_60s', 'log_amount_60s',
            'return_5m_pct', 'return_15m_pct', 'minutes_since_0900', 'gap_open_pct', 'range_so_far_rel',
            'trailing_range_20', 'spread_bps_l1', 'radar_rank', 'pool_up_from_open_share',
            'pool_median_return_from_open_pct', 'prev_day_return_pct', 'prev_day_close_location')
TAUS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
MIN_INNER_PICKS = 30
MIN_TRAIN_EVENTS, MIN_TRAIN_POSITIVES = 300, 30
MIN_FOLD_FILTERED = 30
DAILY_BUY_CAP_TWD, DAILY_LOSS_STOP_TWD, MAX_POSITIONS = 1_000_000.0, 6_000.0, 3


def complete(f) -> bool:
    return all(f['features'].get(k) is not None and math.isfinite(f['features'][k]) for k in FEATURES)


def vector(f):
    return [float(f['features'][k]) for k in FEATURES]


def event_level(firings):
    """One open trade per symbol: a firing counts only after the symbol's previous counted trade has fully closed."""
    out, busy_until = [], {}
    for f in sorted(firings, key=lambda f: (f['date'], f['t_us'], f['radar_rank'])):
        key = (f['date'], f['sym'])
        if f['t_us'] <= busy_until.get(key, -1):
            continue
        busy_until[key] = f['exit_us']
        out.append(f)
    return out


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def excess_t(rows, accepted):
    """Filtered minus all mean (bps), SE by day-clustered linearization. rows: [(date, bps)], accepted: [bool]."""
    na = len(rows)
    nf = sum(accepted)
    if na == 0 or nf == 0:
        return None, None, None
    ma = sum(b for _, b in rows) / na
    mf = sum(b for (_, b), a in zip(rows, accepted) if a) / nf
    z = {}
    for (d, b), a in zip(rows, accepted):
        v = -(b - ma) / na
        if a:
            v += (b - mf) / nf
        z[d] = z.get(d, 0.0) + v
    D = len(z)
    if D < 2:
        return mf - ma, None, None
    var = D / (D - 1) * sum(v * v for v in z.values())
    se = math.sqrt(var) if var > 0 else None
    return mf - ma, se, ((mf - ma) / se if se else None)


def choose_tau(probs, returns_bps):
    """Highest inner mean return among taus with >= 30 picks; ties -> higher tau; none -> 0.50."""
    best = None
    for tau in TAUS:
        picked = [r for p, r in zip(probs, returns_bps) if p >= tau]
        if len(picked) < MIN_INNER_PICKS:
            continue
        m = sum(picked) / len(picked)
        if best is None or m >= best[1]:
            best = (tau, m)
    return best[0] if best else 0.50


def inner_split(train):
    """First 75% / last 25% of the training window's trading dates."""
    dates = sorted({f['date'] for f in train})
    cut = dates[int(math.floor(0.75 * len(dates)))] if dates else None
    return [f for f in train if f['date'] < cut], [f for f in train if f['date'] >= cut]


def portfolio(firings, accept):
    """B-constrained day simulation over raw firings (radar order per minute). accept(f) -> bool.

    A position counts against the 3 slots until its final exit; its net TWD is realized at the final exit for the
    6,000 TWD loss stop (conservative for the profitable half leg). Buys use the QUOTE entry notional.
    """
    days = {}
    for f in firings:
        days.setdefault(f['date'], []).append(f)
    trades, buys, net = 0, 0.0, 0.0
    for day in sorted(days):
        open_, closed, bought = {}, [], 0.0
        for f in sorted(days[day], key=lambda f: (f['t_us'], f['radar_rank'])):
            t = f['t_us']
            for s in [s for s, (x, _) in open_.items() if x <= t]:
                closed.append(open_.pop(s))
            realized = sum(p for x, p in closed)
            if not accept(f) or realized <= -DAILY_LOSS_STOP_TWD or len(open_) >= MAX_POSITIONS or f['sym'] in open_:
                continue
            amt = f['quote']['buy_twd']
            if bought + amt > DAILY_BUY_CAP_TWD:
                continue
            bought += amt
            open_[f['sym']] = (f['exit_us'], f['quote']['net_twd'])
            trades += 1
            net += f['quote']['net_twd']
        buys += bought
    return {'trades': trades, 'buys_twd': buys, 'net_twd': net,
            'net_twd_per_1m_buys': (net / buys * 1_000_000) if buys else None}


def criteria(folds, agg):
    """Preregistered A-E and G. folds: list of per-fold dicts; agg: aggregate dict."""
    est = [f for f in folds if f.get('status') == 'ESTIMATED']
    return {
        'A': agg['filtered_mean_bps'] is not None and agg['filtered_mean_bps'] > 0,
        'B': sum(1 for f in est if f['filtered_mean_bps'] is not None and f['filtered_mean_bps'] > f['all_mean_bps']) >= 4,
        'C': sum(1 for f in est if f['filtered_mean_bps'] is not None and f['filtered_mean_bps'] > 0) >= 3,
        'D': agg['excess_t'] is not None and agg['excess_t'] >= 2.0,
        'E': agg['portfolio_filtered']['net_twd_per_1m_buys'] is not None and agg['portfolio_filtered']['net_twd_per_1m_buys'] > 0,
        'G': len(est) == len(folds) == 5 and all(f['n_filtered'] >= MIN_FOLD_FILTERED for f in est),
    }


def classify(c):
    if not c['G']:
        return 'INSUFFICIENT'
    if all(c[k] for k in 'ABCDE'):
        return 'PASS_TO_FORWARD'
    if not c['D']:
        return 'NO_FILTER_EDGE'
    if c['B'] and (not c['A'] or not c['E']):
        return 'FILTER_HELPS_NET_NEGATIVE'
    return 'WEAK'
