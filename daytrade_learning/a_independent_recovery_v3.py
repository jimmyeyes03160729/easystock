"""Independent, frozen, offline entry hypotheses; never imported by live trading."""
from dataclasses import asdict, dataclass
from datetime import time, timedelta
from decimal import Decimal
import hashlib
import json
import math

from .a_recovery_v2 import aware, completed, screening_cost, shifted, tick_size

ARMS = ('direct', 'pullback', 'union', 'union_score68_control')


@dataclass(frozen=True)
class Policy:
    version: str = 'a-independent-recovery-v3'
    daily_buy_limit: float = 1_000_000
    allocation_fraction: float = .30
    max_stocks: int = 5
    early_slots: int = 2
    middle_slots: int = 4
    max_roundtrip_pct: float = .60
    stop_loss: float = .018
    take_profit: float = .045
    trailing_activate: float = .025
    trailing_pullback: float = .008
    breakeven_activate: float = .015
    breakeven_floor: float = .006
    min_completed_bars: int = 3
    max_signal_age_seconds: int = 10
    context_bars: int = 3
    direct_breakout_bars: int = 2
    confirmation_volume_ratio: float = 1.
    pullback_atr_fraction: float = .5

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key != 'version' and (not math.isfinite(value) or value <= 0):
                raise ValueError('invalid_policy')
        if not 0 < self.allocation_fraction <= 1 or not 0 < self.stop_loss < 1:
            raise ValueError('invalid_policy')
        if not self.early_slots <= self.middle_slots <= self.max_stocks:
            raise ValueError('invalid_slots')
        if self.min_completed_bars < 3:
            raise ValueError('insufficient_policy_history')
        for key in ('max_stocks', 'early_slots', 'middle_slots', 'min_completed_bars',
                    'max_signal_age_seconds', 'context_bars', 'direct_breakout_bars'):
            if not isinstance(getattr(self, key), int):
                raise ValueError('noninteger_policy')

    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def vwap_series(rows):
    volume = amount = 0.
    result = []
    for r in rows:
        volume += r['volume']
        amount += (r['high'] + r['low'] + r['close']) / 3 * r['volume']
        result.append(amount / volume if volume else None)
    return result


def true_range_context(rows, previous_close=None):
    values = []
    for i, r in enumerate(rows):
        previous = rows[i - 1]['close'] if i else previous_close if previous_close is not None else r['open']
        values.append(max(r['high'] - r['low'], abs(r['high'] - previous), abs(r['low'] - previous)))
    return sum(values) / len(values) if values else 0.


def entry_patterns(rows, now, previous, policy=Policy()):
    """Only completed bars; no old score, radar, future winner or next-bar input."""
    now = aware(now)
    rows = completed(rows, now)
    if (previous is None or not math.isfinite(previous) or previous <= 0
            or len(rows) < policy.min_completed_bars):
        return {}, 'missing_reference_or_history'
    if aware(rows[0]['date']).time().replace(tzinfo=None) != time(9):
        return {}, 'missing_session_open'
    if any(aware(r['date']) != aware(rows[0]['date']) + timedelta(minutes=5 * i)
           for i, r in enumerate(rows)):
        return {}, 'missing_completed_bar'
    if (now - (aware(rows[-1]['date']) + timedelta(minutes=5))).total_seconds() > policy.max_signal_age_seconds:
        return {}, 'stale_confirmation'
    if rows[0]['open'] >= previous:
        return {}, 'not_low_open'
    vwaps = vwap_series(rows)
    last = rows[-1]
    if not vwaps[-1] or last['close'] < vwaps[-1]:
        return {}, 'below_vwap'
    reclaim_indices = [i for i, r in enumerate(rows) if vwaps[i] and r['close'] > vwaps[i]
        and (r['open'] <= vwaps[i] if i == 0 else vwaps[i-1] and rows[i-1]['close'] <= vwaps[i-1])]
    if not reclaim_indices:
        return {}, 'no_completed_reclaim'
    prior = rows[max(0, len(rows) - 1 - policy.context_bars):-1]
    average_volume = sum(r['volume'] for r in prior) / len(prior)
    if (last['close'] <= last['open'] or average_volume <= 0
            or last['volume'] < average_volume * policy.confirmation_volume_ratio):
        return {}, 'weak_confirmation'
    common = dict(vwap=vwaps[-1], confirming_high=last['high'], confirming_close=last['close'],
        confirmation_end=(aware(last['date']) + timedelta(minutes=5)).isoformat(),
        relative_volume=last['volume'] / average_volume,
        vwap_distance_pct=(last['close'] / vwaps[-1] - 1) * 100)
    patterns = {}
    breakout_context = rows[max(0, len(rows) - 1 - policy.direct_breakout_bars):-1]
    if (last['close'] > max(r['high'] for r in breakout_context)
            and last['low'] >= rows[-2]['low']):
        patterns['direct'] = dict(common, pattern='direct', reference_support=None)
    # Pullback can remain above VWAP. Its near-support zone scales with past volatility,
    # not a fixed one-tick price tolerance. No future confirmation enters the zone.
    pullback = rows[-2]; context_start = max(0, len(rows) - 2 - policy.context_bars)
    before = rows[context_start:-2]
    preceding_close = rows[context_start - 1]['close'] if context_start else rows[0]['open']
    support = vwaps[-2]
    zone = max(float(tick_size(support)), true_range_context(before, preceding_close) * policy.pullback_atr_fraction) if support else 0.
    if (before and support and any(i <= len(rows) - 3 for i in reclaim_indices)
            and support - zone <= pullback['low'] <= support + zone
            and pullback['close'] >= support
            and pullback['volume'] <= sum(r['volume'] for r in before) / len(before)
            and last['close'] > pullback['high'] and last['low'] >= pullback['low']):
        patterns['pullback'] = dict(common, pattern='pullback', reference_support=support,
                                    support_zone=zone, pullback_low=pullback['low'])
    return patterns, None if patterns else 'no_independent_pattern'


def selected_for_arm(signal, arm):
    if arm not in ARMS:
        raise ValueError('invalid_arm')
    if arm in ('direct', 'pullback'):
        return signal['pattern'] == arm
    if arm == 'union_score68_control':
        return signal.get('legacy_rule_eligible') is True
    return True


def priority(signal):
    """Old score/radar cannot affect selection order."""
    return (-signal['relative_volume'], -signal['vwap_distance_pct'],
            signal['symbol'], 0 if signal['pattern'] == 'direct' else 1)


def execution_guard(signal, price, ticks, policy=Policy()):
    if not math.isfinite(price) or not 1 <= price <= 2000:
        return 'outside_user_price_limits'
    if (price / signal['previous'] - 1) * 100 > 8:
        return 'outside_user_gain_limit'
    if price < signal['vwap']:
        return 'execution_lost_vwap'
    paid = Decimal(str(shifted(price, 1, ticks)))
    ceiling = Decimal(str(signal['confirming_high'])) + tick_size(signal['confirming_high'])
    if paid > ceiling:
        return 'execution_chase'
    if screening_cost(price, ticks) > policy.max_roundtrip_pct:
        return 'insufficient_net_cost_room'
    return None
