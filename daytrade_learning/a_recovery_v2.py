"""Frozen offline A experiment. No SDK, database, network or live imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import math

from paper_execution import cost_aware_breakeven, fee, tax, tick_size
from strategy_engine import calculate_vwap

TPE = timezone(timedelta(hours=8))
ARMS = ('baseline', 'allocation_only', 'recovery_allocation', 'recovery_structural')


@dataclass(frozen=True)
class Policy:
    version: str = 'a-recovery-research-v2'
    daily_buy_limit: float = 1_000_000
    allocation_fraction: float = .30
    max_stocks: int = 5
    early_slots: int = 2
    middle_slots: int = 4
    max_chase_pct: float = .01
    max_roundtrip_pct: float = .60  # percent, not fraction
    stop_loss: float = .018
    take_profit: float = .045
    trailing_activate: float = .025
    trailing_pullback: float = .008
    breakeven_activate: float = .015
    breakeven_floor: float = .006

    def __post_init__(self):
        floats = (self.daily_buy_limit, self.allocation_fraction, self.max_chase_pct,
                  self.max_roundtrip_pct, self.stop_loss, self.take_profit,
                  self.trailing_activate, self.trailing_pullback,
                  self.breakeven_activate, self.breakeven_floor)
        if any(not math.isfinite(v) or v <= 0 for v in floats):
            raise ValueError('invalid_policy')
        if not 0 < self.allocation_fraction <= 1 or not 0 < self.stop_loss < 1:
            raise ValueError('invalid_policy')
        if not 0 < self.early_slots <= self.middle_slots <= self.max_stocks:
            raise ValueError('invalid_slots')

    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def aware(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None:
        raise ValueError('naive_timestamp')
    return value.astimezone(TPE)


def execution_time(signal_time):
    return (aware(signal_time) + timedelta(seconds=2)).replace(second=0, microsecond=0) + timedelta(minutes=1)


def shifted(price, direction, ticks):
    if not math.isfinite(price) or price <= 0 or ticks not in (1, 2):
        raise ValueError('invalid_execution')
    value = Decimal(str(price))
    for _ in range(ticks):
        value += direction * tick_size(value if direction > 0 else value - Decimal('.000001'))
    if value <= 0:
        raise ValueError('invalid_execution')
    return float(value)


def aligned(price, direction):
    value = Decimal(str(price)); step = tick_size(value)
    mode = ROUND_CEILING if direction > 0 else ROUND_FLOOR
    return float((value / step).to_integral_value(rounding=mode) * step)


def screening_cost(price, ticks):
    buy, sell = shifted(price, 1, ticks), shifted(price, -1, ticks)
    amount = buy * 1000
    return ((buy - sell) * 1000 + float(fee(amount) + fee(sell * 1000) + tax(sell * 1000))) / amount * 100


def completed(rows, now):
    now = aware(now)
    result = [r for r in rows if aware(r['date']).date() == now.date()
              and aware(r['date']) + timedelta(minutes=5) <= now]
    stamps = [aware(r['date']) for r in result]
    if stamps != sorted(set(stamps)):
        raise ValueError('unordered_or_duplicate_bars')
    return result


def recovery_setup(rows, now, previous, price, policy=Policy()):
    """Past completed reclaim -> later pullback -> latest confirmation only."""
    rows = completed(rows, now)
    if previous is None or not math.isfinite(previous) or previous <= 0 or len(rows) < 4:
        return False, 'missing_reference_or_history'
    if rows[0]['open'] >= previous:
        return False, 'not_low_open'
    vwaps = [calculate_vwap(rows[:i + 1]) for i in range(len(rows))]
    reclaim = None
    for i in range(len(rows) - 2):
        if not vwaps[i]:
            continue
        was_below = (rows[i]['open'] <= vwaps[i] if i == 0
                     else vwaps[i - 1] and rows[i - 1]['close'] <= vwaps[i - 1])
        if was_below and rows[i]['close'] > vwaps[i]:
            reclaim = i
    if reclaim is None:
        return False, 'no_completed_reclaim'
    pullback, confirmation = rows[-2:]
    vwap = vwaps[-2]
    prior = rows[max(0, len(rows) - 5):-2]
    if not vwap or not prior:
        return False, 'no_pullback_context'
    tolerance = float(tick_size(vwap))
    if not (vwap - tolerance <= pullback['low'] <= vwap + tolerance
            and pullback['close'] >= vwap and pullback['close'] >= pullback['open']
            and pullback['volume'] <= sum(r['volume'] for r in prior) / len(prior)):
        return False, 'pullback_not_held'
    if not (confirmation['close'] > pullback['high']
            and confirmation['close'] > confirmation['open']
            and confirmation['low'] >= pullback['low']
            and confirmation['volume'] >= 1.15 * sum(r['volume'] for r in prior) / len(prior)):
        return False, 'no_completed_confirmation'
    last_vwap = vwaps[-1]
    if (not last_vwap or price < last_vwap
            or price > last_vwap * (1 + policy.max_chase_pct)
            or price > confirmation['high'] + float(tick_size(confirmation['high']))):
        return False, 'chase_distance'
    return True, 'reclaim_pullback_confirmation'


def position_size(price, remaining, count, now, arm, policy=Policy()):
    if arm not in ARMS:
        raise ValueError('invalid_arm')
    if (not math.isfinite(price) or price <= 0 or not math.isfinite(remaining)
            or remaining < 0 or not isinstance(count, int) or count < 0):
        raise ValueError('invalid_sizing_input')
    clock = aware(now).time().replace(tzinfo=None)
    if not time(9, 30) <= clock < time(12, 30):
        return 0, 'entry_window'
    slots = policy.max_stocks
    if arm != 'baseline':
        slots = policy.early_slots if clock < time(10) else policy.middle_slots if clock < time(11) else slots
    if count >= slots:
        return 0, 'slot_reservation' if slots < policy.max_stocks else 'daily_stock_limit'
    allocation = remaining if arm == 'baseline' else min(remaining, policy.daily_buy_limit * policy.allocation_fraction)
    shares = int(Decimal(str(allocation)) // (Decimal(str(price)) * 1000)) * 1000
    return (shares, None) if shares > 0 else (0, 'lot_exceeds_allocation')


def technical_reason(rows, now, structural):
    rows = completed(rows, now)
    if len(rows) < 3:
        return None
    if structural:
        vwaps = [calculate_vwap(rows[:i + 1]) for i in (len(rows) - 2, len(rows) - 1)]
        if all(v and r['close'] < v for r, v in zip(rows[-2:], vwaps)):
            return 'two_completed_closes_below_vwap'
        if rows[-1]['close'] < min(r['low'] for r in rows[-3:-1]):
            return 'completed_structure_break'
    else:
        vwap = calculate_vwap(rows)
        if vwap and rows[-1]['close'] < vwap:
            return 'below_vwap'
        if len(rows) >= 7 and rows[-1]['close'] < min(r['low'] for r in rows[-6:-1]):
            return 'five_minute_short_low'
    return None


class Portfolio:
    """In-memory hypothetical execution, allowance is never replenished."""
    def __init__(self, arm, ticks=1, policy=Policy()):
        if arm not in ARMS or ticks not in (1, 2):
            raise ValueError('invalid_experiment')
        self.arm, self.ticks, self.policy = arm, ticks, policy
        self.used = 0.
        self.positions, self.trades, self.traded = {}, [], set()
        self.peak = self.max_drawdown = 0.

    def open(self, signal, price, now):
        symbol = signal['symbol']
        if symbol in self.traded:
            return 'same_stock_reentry'
        paid = shifted(price, 1, self.ticks)
        shares, reason = position_size(paid, self.policy.daily_buy_limit - self.used,
                                      len(self.traded), now, self.arm, self.policy)
        if not shares:
            return reason
        self.used = round(self.used + paid * shares, 2)
        self.traded.add(symbol)
        self.positions[symbol] = dict(symbol=symbol, entry_at=aware(now),
            signal_at=aware(signal['at']), entry_price=paid, signal_price=price,
            shares=shares, buy_fee=float(fee(paid * shares)), highest=price,
            stop=price * (1 - self.policy.stop_loss), target=price * (1 + self.policy.take_profit),
            trailing=None, current=price, trend_active=False)
        return None

    def close(self, symbol, price, now, reason):
        p = self.positions.pop(symbol)
        exit_price = shifted(price, -1, self.ticks)
        sell_fee, sell_tax = float(fee(exit_price * p['shares'])), float(tax(exit_price * p['shares']))
        gross = round((exit_price - p['entry_price']) * p['shares'], 2)
        costs = p['buy_fee'] + sell_fee + sell_tax
        self.trades.append({k: v.isoformat() if isinstance(v, datetime) else v
                            for k, v in dict(p, exit_at=aware(now), exit_price=exit_price,
                                reason=reason, gross_pnl=gross, costs=costs,
                                sell_fee=sell_fee, tax=sell_tax, net_pnl=round(gross - costs, 2)).items()})

    def tick(self, symbol, price, now):
        p = self.positions.get(symbol)
        if p is None:
            return
        p['current'] = price; p['highest'] = max(p['highest'], price)
        p['trend_active'] = p['highest'] >= p['entry_price'] * (1 + self.policy.breakeven_activate)
        if aware(now).time().replace(tzinfo=None) >= time(12, 55):
            return self.close(symbol, price, now, 'force_exit')
        if price <= p['stop']:
            return self.close(symbol, price, now, 'hard_stop')
        if self.arm != 'recovery_structural' or not p['trend_active']:
            floor, activation = cost_aware_breakeven(p['entry_price'], self.policy.breakeven_floor,
                                                    self.policy.breakeven_activate)
            if p['highest'] >= activation and price <= floor:
                return self.close(symbol, price, now, 'breakeven')
        if price >= p['target']:
            return self.close(symbol, price, now, 'take_profit')
        if (self.arm != 'recovery_structural' or not p['trend_active']) and p['highest'] >= p['signal_price'] * (1 + self.policy.trailing_activate):
            p['trailing'] = max(p['trailing'] or 0, p['highest'] * (1 - self.policy.trailing_pullback))
            if price <= p['trailing']:
                self.close(symbol, price, now, 'trailing')

    def segment(self, symbol, start, end, now):
        p = self.positions.get(symbol)
        if p is None:
            return
        levels = [p['target']] if end > start else [p['stop']]
        if end < start and (self.arm != 'recovery_structural' or not p['trend_active']):
            floor, activation = cost_aware_breakeven(p['entry_price'], self.policy.breakeven_floor,
                                                    self.policy.breakeven_activate)
            if p['highest'] >= activation:
                levels.append(floor)
            if p['trailing'] is not None:
                levels.append(p['trailing'])
        levels = sorted((aligned(v, 1 if end > start else -1) for v in levels), reverse=end < start)
        for level in levels:
            if min(start, end) <= level <= max(start, end):
                self.tick(symbol, level, now)
                if symbol not in self.positions:
                    return
        self.tick(symbol, end, now)

    def mark(self, prices):
        pnl = sum(t['net_pnl'] for t in self.trades)
        for symbol, p in self.positions.items():
            # Never silently omit an open liability if the latest minute is missing.
            bid = shifted(prices.get(symbol, p['current']), -1, self.ticks)
            pnl += ((bid - p['entry_price']) * p['shares'] - p['buy_fee']
                    - float(fee(bid * p['shares']) + tax(bid * p['shares'])))
        self.peak = max(self.peak, pnl)
        self.max_drawdown = max(self.max_drawdown, self.peak - pnl)

    def summary(self):
        return dict(arm=self.arm, ticks=self.ticks, trades=self.trades,
            closed_count=len(self.trades), wins=sum(t['net_pnl'] > 0 for t in self.trades),
            net_pnl=round(sum(t['net_pnl'] for t in self.trades), 2), buy_used=self.used,
            max_drawdown_twd=round(self.max_drawdown, 2), unresolved=sorted(self.positions))


def deployment_gate(reports, *, complete_forward_evidence=False):
    """Exploratory profitability cannot authorize deployment."""
    reasons = []
    if not complete_forward_evidence:
        reasons.append('missing_complete_forward_eligibility_depth_and_market_evidence')
    days = {r['day'] for r in reports if r.get('split') == 'holdout'}
    if len(days) < 10:
        reasons.append('insufficient_untouched_evaluation_days')
    for ticks in (1, 2):
        rows = [r for r in reports if r.get('split') == 'holdout' and r['ticks'] == ticks]
        for path in ('low-first', 'high-first'):
            baseline = [r for r in rows if r['path'] == path and r['arm'] == 'baseline']
            candidate = [r for r in rows if r['path'] == path and r['arm'] == 'recovery_structural']
            if (len(baseline) != len(days) or len(candidate) != len(days)
                    or {r['day'] for r in baseline} != days
                    or {r['day'] for r in candidate} != days):
                reasons.append(f'unpaired_evaluation_days_t{ticks}_{path}')
            if not candidate or sum(r.get('closed_count', 0) for r in candidate) == 0:
                reasons.append(f'no_candidate_trades_t{ticks}_{path}')
            if not candidate or sum(r['net_pnl'] for r in candidate) <= 0:
                reasons.append(f'nonpositive_holdout_t{ticks}_{path}')
            if (candidate and baseline and max(r['max_drawdown_twd'] for r in candidate)
                    > max(r['max_drawdown_twd'] for r in baseline)):
                reasons.append(f'worse_drawdown_t{ticks}_{path}')
            if any(r['unresolved'] for r in candidate):
                reasons.append(f'unresolved_positions_t{ticks}_{path}')
    return {'deployment_allowed': not reasons, 'reasons': reasons}
