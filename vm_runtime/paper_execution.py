"""Conservative long-stock Paper execution; no broker order methods.

Book sizes are shares. No last-price fallback and no partial SELL simulation.
Fee discount/minimum and rounding are explicit simulator assumptions.
"""
from datetime import time
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import math

STANDARD_FEE_RATE = Decimal('0.001425')
SIMULATED_DISCOUNT = Decimal('0.28')
MINIMUM_FEE = Decimal('20')
DAY_TAX_RATE = Decimal('0.0015')
ORDINARY_STOCK_TAX_RATE = Decimal('0.003')


def fee(amount, rate=STANDARD_FEE_RATE * SIMULATED_DISCOUNT):
    return max(MINIMUM_FEE, (Decimal(str(amount)) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def tax(amount, *, eligible=True, same_day=True):
    rate = DAY_TAX_RATE if eligible and same_day else ORDINARY_STOCK_TAX_RATE
    return (Decimal(str(amount)) * rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)


# Ordinary-stock tick schedule (TWSE/TPEx): (upper bound exclusive, tick).
TICKS = ((10, '0.01'), (50, '0.05'), (100, '0.1'), (500, '0.5'), (1000, '1'))


def tick_size(price):
    p = Decimal(str(price))
    return next((Decimal(t) for bound, t in TICKS if p < bound), Decimal('5'))


def roundtrip_cost_pct(price, shares=1000):
    """One-lot buy fee, sell fee and day tax at an unchanged price, plus one
    tick of spread, as a percentage of notional. A screening estimate only."""
    p = Decimal(str(price))
    amount = p * shares
    costs = fee(amount) * 2 + tax(amount)
    return float((costs / amount + tick_size(p) / p) * 100)


def breakeven_exit_price(entry_price, shares=1000, *, fee_rate=None,
                         minimum_fee=MINIMUM_FEE, tax_rate=DAY_TAX_RATE):
    """Lowest tick-aligned exit whose net proceeds cover the entry and costs.
    Rates default to the Paper schedule; research passes its own assumptions."""
    rate = STANDARD_FEE_RATE * SIMULATED_DISCOUNT if fee_rate is None else Decimal(str(fee_rate))
    minimum, tax_rate = Decimal(str(minimum_fee)), Decimal(str(tax_rate))
    cost = lambda amount, r: max(minimum, (amount * r).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    entry = Decimal(str(entry_price))
    if not entry.is_finite() or entry <= 0:
        raise ValueError('invalid_entry_price')
    paid = entry * shares + cost(entry * shares, rate)
    tick = tick_size(entry)
    price = (entry / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    for _ in range(1000):
        amount = price * shares
        proceeds = amount - cost(amount, rate) - (amount * tax_rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        if proceeds >= paid:
            return float(price)
        price += tick_size(price)
    raise ValueError('no_breakeven_price')


def cost_aware_breakeven(entry_price, floor_pct, activate_pct, **rates):
    """(floor, activation) prices for a breakeven exit that actually breaks even.

    The floor covers fees and tax, plus one tick because a sell fills at the bid;
    activation must sit at least one tick above it. Neither is below the
    configured percentage levels."""
    entry = float(entry_price)
    floor = breakeven_exit_price(entry, **rates)
    floor = max(entry * (1 + floor_pct), floor + float(tick_size(floor)))
    activate = max(entry * (1 + activate_pct), floor + float(tick_size(floor)))
    return round(floor, 2), round(activate, 2)


def execution(evidence, side, now, shares=None):
    """Return supported executable price/depth or an explicit skip reason."""
    evidence = evidence or {}
    if side not in ('BUY', 'SELL'):
        raise ValueError('invalid_side')
    # Carried into the skip so the stored record shows the contract's actual flags.
    detail = {k: evidence[k] for k in ('eligibility_detail', 'quote_error') if evidence.get(k)}
    if side == 'BUY':
        eligibility = evidence.get('eligibility')
        if eligibility is not True:
            return {'status':'skipped', 'skip_reason':'daytrade_ineligible' if eligibility is False else 'daytrade_eligibility_unknown', **detail}
        if not time(9,30) <= now.time().replace(tzinfo=None) < time(12,30):
            return {'status':'skipped','skip_reason':'entry_cutoff'}
    elif not time(9) <= now.time().replace(tzinfo=None) < time(13,30):
        return {'status':'pending','skip_reason':'outside_market_session'}
    if evidence.get('quote_error'):
        return {'status':'skipped' if side=='BUY' else 'pending', 'skip_reason':'quote_unavailable', **detail}
    try:
        from datetime import datetime
        observed = datetime.fromisoformat(str(evidence['quote_at']))
        observed = observed.astimezone(now.tzinfo) if observed.tzinfo is not None else observed
        if observed.tzinfo is None or observed.date() != now.date() or not 0 <= (now-observed).total_seconds() <= 15:
            return {'status':'skipped' if side=='BUY' else 'pending','skip_reason':'quote_stale'}
        price = float(evidence['ask' if side=='BUY' else 'bid'])
        depth = float(evidence['ask_shares' if side=='BUY' else 'bid_shares'])
        if not math.isfinite(price) or price <= 0 or not math.isfinite(depth) or depth < 1000:
            raise ValueError('no_depth')
        capacity = int(depth // 1000) * 1000
        if side == 'SELL' and (shares is None or shares <= 0 or shares % 1000 or capacity < shares):
            raise ValueError('insufficient_depth')
        return {'status':'executable', 'price':price, 'max_shares':capacity, 'quote_at':observed.isoformat()}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {'status':'skipped' if side=='BUY' else 'pending','skip_reason':'no_counterparty'}
