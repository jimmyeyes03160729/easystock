"""Shared historical replay mechanics; never rank by future bar availability."""
from __future__ import annotations

from .market_daily import future_bars

CORRECTION_ID = 'REBOUND_SIMULATION_CORRECTION_V1'


def session_bars(market, symbol: str, day: str, sessions: list[str], *, before: str):
    """Return one slot per market session, with None for missing stock bars."""
    if not sessions or any(d <= day or d >= before for d in sessions):
        raise ValueError('historical_session_boundary')
    if sessions != sorted(set(sessions)):
        raise ValueError('nonmonotonic_sessions')
    loaded = future_bars(market, symbol, day, len(sessions), before=before, through=sessions[-1])
    by_day = {bar['time']: bar for bar in loaded}
    return [by_day.get(d) for d in sessions]


def replay(bars: list[dict | None], target: float, invalid: float, *, stop: bool,
           take: bool, horizon: int) -> dict:
    """Resolve only observed exits; a missing live-position bar is censored.

    The loaders enforce calendar maturity separately. Missing bars after a
    resolved exit do not erase that trade. An unknown live path is not a no-fill.
    """
    if horizon < 1:
        raise ValueError('invalid_horizon')
    if not bars or bars[0] is None:
        return {'status': 'NO_FILL_D1_MISSING', 'gross': None, 'exit_session': None}
    entry = bars[0]['open']
    if not invalid < entry < target:
        return {'status': 'NO_FILL_OUTSIDE_BRACKET', 'gross': None, 'exit_session': None}
    for n in range(horizon):
        bar = bars[n] if n < len(bars) else None
        if bar is None:
            return {'status': 'UNRESOLVED_MISSING_BAR', 'gross': None, 'exit_session': None}
        if n and ((stop and bar['open'] <= invalid) or (take and bar['open'] >= target)):
            price = bar['open']
        elif stop and bar['low'] <= invalid:
            price = invalid
        elif take and bar['high'] >= target:
            price = target
        elif n == horizon - 1:
            price = bar['close']
        else:
            continue
        return {'status': 'EXECUTED', 'gross': (price / entry - 1) * 100, 'exit_session': n + 1}
    raise AssertionError('unreachable_replay')


def missing_outcome_threshold(trades: list[float], unresolved: int) -> dict:
    """Required average net return of censored trades to make the total zero."""
    return {'resolved_trades': len(trades), 'unresolved_trades': unresolved,
            'unresolved_mean_net_to_break_even_pct':
                round(-sum(trades) / unresolved, 6) if unresolved else None}


def cost_sensitivity(net_trades: list[float], cost: float = 0.6) -> dict:
    from .research import metrics
    gross = [t + cost for t in net_trades]
    return {'break_even_cost_pct': round(sum(gross) / len(gross), 6) if gross else None,
            'fixed_trade_list': True,
            'scenarios': {f'{c:.2f}': metrics([t - c for t in gross])
                          for c in (0.60, 0.50, 0.45, 0.40, 0.30)}}
