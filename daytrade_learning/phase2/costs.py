"""Phase 2A Transaction Cost Model & Accounting Semantics.

Centralizes:
- Official statutory and exchange rules (SOURCE_PARAMETER)
- EasyStock broker and account parameters (EASYSTOCK_EXISTING_PARAMETER)
- Research stress testing grids (RESEARCH_GOVERNANCE_CANDIDATE)

Ensures Slippage Single Source of Truth:
- Execution fill price = actual simulated fill price
- Retain theoretical_entry_price, actual_entry_price, theoretical_exit_price, actual_exit_price
- slippage_cost is derived from the difference between actual execution and theoretical execution
- net_pnl strictly does NOT double-count slippage
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CostParameterCategory(str, Enum):
    SOURCE_PARAMETER = "SOURCE_PARAMETER"
    EASYSTOCK_EXISTING_PARAMETER = "EASYSTOCK_EXISTING_PARAMETER"
    RESEARCH_GOVERNANCE_CANDIDATE = "RESEARCH_GOVERNANCE_CANDIDATE"


@dataclass(frozen=True)
class CostParameterDefinition:
    name: str
    value: Any
    category: CostParameterCategory
    source: str
    description: str


# Centralized Cost Governance Parameters
PARAM_BROKER_FEE_RATE = CostParameterDefinition(
    name="broker_fee_rate",
    value=0.001425,
    category=CostParameterCategory.SOURCE_PARAMETER,
    source="Taiwan Stock Exchange (TWSE) Statutory Fee Rate",
    description="Standard statutory broker commission rate of 0.1425%",
)

PARAM_BROKER_DISCOUNT = CostParameterDefinition(
    name="broker_discount",
    value=0.28,
    category=CostParameterCategory.EASYSTOCK_EXISTING_PARAMETER,
    source="EasyStock Account Configuration (paper_ledger.py)",
    description="Broker fee discount 28% (28折)",
)

PARAM_MINIMUM_FEE = CostParameterDefinition(
    name="minimum_fee",
    value=20.0,
    category=CostParameterCategory.EASYSTOCK_EXISTING_PARAMETER,
    source="EasyStock Account Configuration (paper_ledger.py)",
    description="Minimum broker commission per order of 20 TWD",
)

PARAM_DAYTRADE_TAX_RATE = CostParameterDefinition(
    name="daytrade_tax_rate",
    value=0.0015,
    category=CostParameterCategory.SOURCE_PARAMETER,
    source="Statutory Day-Trading Securities Transaction Tax Act",
    description="Incentive day-trade securities transaction tax rate of 0.15%",
)

PARAM_NORMAL_TAX_RATE = CostParameterDefinition(
    name="normal_tax_rate",
    value=0.0030,
    category=CostParameterCategory.SOURCE_PARAMETER,
    source="Statutory Securities Transaction Tax Act",
    description="Standard securities transaction tax rate of 0.30%",
)

PARAM_SLIPPAGE_GRID = CostParameterDefinition(
    name="slippage_grid",
    value=[0.0, 5.0, 10.0, 15.0, 20.0],
    category=CostParameterCategory.RESEARCH_GOVERNANCE_CANDIDATE,
    source="Knowledge V2 Research Parameter Candidate",
    description="Slippage stress-test grid in basis points (bps)",
)

COST_PARAMETER_REGISTRY: dict[str, CostParameterDefinition] = {
    p.name: p for p in [
        PARAM_BROKER_FEE_RATE,
        PARAM_BROKER_DISCOUNT,
        PARAM_MINIMUM_FEE,
        PARAM_DAYTRADE_TAX_RATE,
        PARAM_NORMAL_TAX_RATE,
        PARAM_SLIPPAGE_GRID,
    ]
}


def get_twse_tick_size(price: float) -> float:
    """TWSE official tick size brackets for equities."""
    if price <= 0:
        raise ValueError(f"Price must be strictly positive: {price}")
    if price < 10.0:
        return 0.01
    elif price < 50.0:
        return 0.05
    elif price < 100.0:
        return 0.10
    elif price < 500.0:
        return 0.50
    elif price < 1000.0:
        return 1.00
    else:
        return 5.00


def round_to_twse_tick(price: float, round_up: bool = False) -> float:
    """Round price to the nearest TWSE tick according to price bracket."""
    tick = get_twse_tick_size(price)
    units = price / tick
    rounded_units = math.ceil(units - 1e-9) if round_up else round(units)
    return round(rounded_units * tick, 4)


class TransactionCostModel:
    """Standard transaction cost calculation honoring TWSE and EasyStock rules."""

    def __init__(
        self,
        broker_fee_rate: float = PARAM_BROKER_FEE_RATE.value,
        broker_discount: float = PARAM_BROKER_DISCOUNT.value,
        minimum_fee: float = PARAM_MINIMUM_FEE.value,
        daytrade_tax_rate: float = PARAM_DAYTRADE_TAX_RATE.value,
        normal_tax_rate: float = PARAM_NORMAL_TAX_RATE.value,
    ):
        self.broker_fee_rate = broker_fee_rate
        self.broker_discount = broker_discount
        self.minimum_fee = minimum_fee
        self.daytrade_tax_rate = daytrade_tax_rate
        self.normal_tax_rate = normal_tax_rate

    def calculate_commission(self, notional: float) -> float:
        """Commission fee with discount and minimum fee applied."""
        if notional <= 0:
            return 0.0
        raw_fee = notional * self.broker_fee_rate * self.broker_discount
        return max(self.minimum_fee, math.floor(raw_fee))

    def calculate_tax(self, sell_notional: float, is_daytrade: bool = True) -> float:
        """Securities transaction tax charged on sell transactions."""
        if sell_notional <= 0:
            return 0.0
        tax_rate = self.daytrade_tax_rate if is_daytrade else self.normal_tax_rate
        return math.floor(sell_notional * tax_rate)

    def calculate_round_trip_costs(
        self,
        entry_notional: float,
        exit_notional: float,
        is_daytrade: bool = True,
    ) -> tuple[float, float, float]:
        """Returns (entry_commission, exit_commission, exit_tax)."""
        entry_comm = self.calculate_commission(entry_notional)
        exit_comm = self.calculate_commission(exit_notional)
        exit_tax = self.calculate_tax(exit_notional, is_daytrade=is_daytrade)
        return entry_comm, exit_comm, exit_tax


def calculate_derived_slippage_cost(
    theoretical_entry: float,
    actual_entry: float,
    theoretical_exit: float,
    actual_exit: float,
    quantity: int,
    direction: str = "LONG",
) -> float:
    """Derives exact slippage cost from actual vs theoretical execution fills.
    
    For LONG:
      Entry slippage: (actual_entry - theoretical_entry) * quantity  [paying more is adverse]
      Exit slippage:  (theoretical_exit - actual_exit) * quantity    [receiving less is adverse]
    For SHORT:
      Entry slippage: (theoretical_entry - actual_entry) * quantity  [selling for less is adverse]
      Exit slippage:  (actual_exit - theoretical_exit) * quantity    [buying back for more is adverse]
    """
    if quantity <= 0:
        raise ValueError(f"Quantity must be positive: {quantity}")
    dir_upper = direction.upper()
    if dir_upper == "LONG":
        entry_slip = (actual_entry - theoretical_entry) * quantity
        exit_slip = (theoretical_exit - actual_exit) * quantity
    elif dir_upper == "SHORT":
        entry_slip = (theoretical_entry - actual_entry) * quantity
        exit_slip = (actual_exit - theoretical_exit) * quantity
    else:
        raise ValueError(f"Unsupported direction: {direction}")
    return round(entry_slip + exit_slip, 4)


def calculate_single_source_pnl(
    theoretical_entry_price: float,
    actual_entry_price: float,
    theoretical_exit_price: float,
    actual_exit_price: float,
    quantity: int,
    cost_model: TransactionCostModel | None = None,
    is_daytrade: bool = True,
    direction: str = "LONG",
) -> dict[str, float]:
    """Single Source of Truth PnL accounting.
    
    Actual execution prices ALREADY embody slippage.
    Gross PnL (actual) = (actual_exit - actual_entry) * quantity  (for LONG)
    Net PnL = Gross PnL (actual) - entry_commission - exit_commission - tax
    
    Equivalence check:
    Theoretical Gross = (theoretical_exit - theoretical_entry) * quantity
    Slippage Cost = derived difference
    Net PnL also equals: Theoretical Gross - Slippage Cost - entry_commission - exit_commission - tax
    
    This guarantees slippage is NOT double counted.
    """
    if cost_model is None:
        cost_model = TransactionCostModel()
    if quantity <= 0:
        raise ValueError(f"Quantity must be positive: {quantity}")

    dir_upper = direction.upper()
    if dir_upper == "LONG":
        gross_actual = (actual_exit_price - actual_entry_price) * quantity
        gross_theoretical = (theoretical_exit_price - theoretical_entry_price) * quantity
    elif dir_upper == "SHORT":
        gross_actual = (actual_entry_price - actual_exit_price) * quantity
        gross_theoretical = (theoretical_entry_price - theoretical_exit_price) * quantity
    else:
        raise ValueError(f"Unsupported direction: {direction}")

    actual_entry_notional = actual_entry_price * quantity
    actual_exit_notional = actual_exit_price * quantity

    entry_comm, exit_comm, tax = cost_model.calculate_round_trip_costs(
        actual_entry_notional, actual_exit_notional, is_daytrade=is_daytrade
    )

    slippage_cost = calculate_derived_slippage_cost(
        theoretical_entry=theoretical_entry_price,
        actual_entry=actual_entry_price,
        theoretical_exit=theoretical_exit_price,
        actual_exit=actual_exit_price,
        quantity=quantity,
        direction=dir_upper,
    )

    # Net PnL from actual execution
    net_pnl = gross_actual - entry_comm - exit_comm - tax

    # Theoretical equivalent check: must match within floating precision
    theoretical_net = gross_theoretical - slippage_cost - entry_comm - exit_comm - tax
    if abs(net_pnl - theoretical_net) > 1e-5:
        raise AssertionError(
            f"Accounting discrepancy detected: actual net ({net_pnl}) != theoretical net ({theoretical_net})"
        )

    return {
        "theoretical_entry_price": theoretical_entry_price,
        "actual_entry_price": actual_entry_price,
        "theoretical_exit_price": theoretical_exit_price,
        "actual_exit_price": actual_exit_price,
        "quantity": float(quantity),
        "gross_pnl_actual": round(gross_actual, 4),
        "gross_pnl_theoretical": round(gross_theoretical, 4),
        "entry_commission": float(entry_comm),
        "exit_commission": float(exit_comm),
        "total_commission": float(entry_comm + exit_comm),
        "tax": float(tax),
        "slippage_cost": slippage_cost,
        "net_pnl": round(net_pnl, 4),
    }
