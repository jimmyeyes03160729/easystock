"""Conservative long-stock Paper execution; no broker order methods.

Book sizes are shares. No last-price fallback and no partial SELL simulation.
Fee discount/minimum and rounding are explicit simulator assumptions.
"""
from datetime import time
from decimal import Decimal, ROUND_HALF_UP
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


def execution(evidence, side, now, shares=None):
    """Return supported executable price/depth or an explicit skip reason."""
    evidence = evidence or {}
    if side not in ('BUY', 'SELL'):
        raise ValueError('invalid_side')
    if side == 'BUY':
        eligibility = evidence.get('eligibility')
        if eligibility is not True:
            return {'status':'skipped', 'skip_reason':'daytrade_ineligible' if eligibility is False else 'daytrade_eligibility_unknown'}
        if not time(9,30) <= now.time().replace(tzinfo=None) < time(12,30):
            return {'status':'skipped','skip_reason':'entry_cutoff'}
    elif not time(9) <= now.time().replace(tzinfo=None) < time(13,30):
        return {'status':'pending','skip_reason':'outside_market_session'}
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
