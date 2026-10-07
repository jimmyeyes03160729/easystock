"""Round-trip costs for 1000-share day trades, delegating to paper_execution fee/tax."""
from __future__ import annotations

from decimal import Decimal

import paper_execution as pe

SHARES = 1000


def _d(x) -> Decimal:
    v = Decimal(str(x))
    if not v.is_finite() or v <= 0:
        raise ValueError('price must be a positive finite number')
    return v


def _cost_pct(entry, exit_, shares: int) -> tuple[float, float]:
    e, x = _d(entry), _d(exit_)
    ea, xa = e * shares, x * shares
    cost = pe.fee(ea) + pe.fee(xa) + pe.tax(xa)
    gross = float((x / e - 1) * 100)
    return gross, gross - float(cost / ea * 100)


def cost_pct(entry_price, exit_price, shares: int = SHARES) -> tuple[float, float]:
    """LONG (gross_pct, research_net_pct) from trade prices."""
    return _cost_pct(entry_price, exit_price, shares)


def cost_quote_pct(entry_ask, exit_bid, shares: int = SHARES) -> tuple[float, float]:
    """LONG quote stress: buy at the ask, sell at the bid."""
    return _cost_pct(entry_ask, exit_bid, shares)
