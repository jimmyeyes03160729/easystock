"""Phase 2A Causal Research Dataset & Trade Semantics.

Fixes Enforced:
1. Trade Record Semantics:
   - Explicit quantity (shares), default notional/lot sizing.
   - initial_risk_per_share and initial_risk_amount fields.
   - Rejects zero-risk trades (initial_risk_per_share <= 0).
   - Rejects long invalid stops (stop_loss >= entry) and short invalid stops (stop_loss <= entry).
2. Explicit MFE/MAE Decomposition:
   - mfe_price, mae_price (TWD)
   - mfe_pct, mae_pct (%)
   - mfe_R, mae_R (R-multiples)
3. Event-based Sample & Label Interval:
   - sample_time, label_start_time, label_end_time for purging and embargo.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Optional, Sequence

from .costs import (
    TransactionCostModel,
    calculate_single_source_pnl,
)
from .execution import (
    parse_phase2_timestamp,
    validate_causal_order,
    MarketBar,
)


class InvalidTradeParametersError(ValueError):
    """Raised when trade parameters violate risk or direction constraints."""
    pass


@dataclass(frozen=True)
class Phase2TradeRecord:
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    quantity: int

    # Timestamps
    feature_time: str
    signal_time: str
    decision_available_time: str
    execution_time: str
    exit_time: str

    # Sample and Forward-Label Timing for Purging & Embargo
    sample_time: str
    label_start_time: str
    label_end_time: str

    # Execution Prices
    theoretical_entry_price: float
    actual_entry_price: float
    theoretical_exit_price: float
    actual_exit_price: float

    # Risk Definition
    stop_loss_price: float
    initial_risk_per_share: float
    initial_risk_amount: float

    # Explicit MFE & MAE Decomposition
    mfe_price: float
    mae_price: float
    mfe_pct: float
    mae_pct: float
    mfe_R: float
    mae_R: float

    # Accounting & PnL
    gross_pnl_actual: float
    gross_pnl_theoretical: float
    commission_total: float
    tax_total: float
    slippage_cost: float
    net_pnl: float
    pnl_R: float

    # Feature Snapshot (Strictly Causal)
    features_snapshot: dict[str, Any]

    def __post_init__(self):
        if self.quantity <= 0:
            raise InvalidTradeParametersError(f"Quantity must be strictly positive: {self.quantity}")
        if self.initial_risk_per_share <= 0:
            raise InvalidTradeParametersError(
                f"zero-risk R rejection: initial_risk_per_share must be strictly positive: {self.initial_risk_per_share}"
            )
        if self.initial_risk_amount <= 0:
            raise InvalidTradeParametersError(
                f"zero-risk R rejection: initial_risk_amount must be strictly positive: {self.initial_risk_amount}"
            )

        dir_upper = self.direction.upper()
        if dir_upper == "LONG":
            if self.stop_loss_price >= self.actual_entry_price:
                raise InvalidTradeParametersError(
                    f"long invalid stop: stop_loss_price ({self.stop_loss_price}) must be strictly below actual_entry_price ({self.actual_entry_price})"
                )
        elif dir_upper == "SHORT":
            if self.stop_loss_price <= self.actual_entry_price:
                raise InvalidTradeParametersError(
                    f"short invalid stop: stop_loss_price ({self.stop_loss_price}) must be strictly above actual_entry_price ({self.actual_entry_price})"
                )
        else:
            raise InvalidTradeParametersError(f"Unsupported direction: {self.direction}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_phase2_trade(
    symbol: str,
    direction: str,
    quantity: int,
    feature_time: datetime | str,
    signal_time: datetime | str,
    decision_available_time: datetime | str,
    execution_time: datetime | str,
    exit_time: datetime | str,
    theoretical_entry_price: float,
    actual_entry_price: float,
    theoretical_exit_price: float,
    actual_exit_price: float,
    stop_loss_price: float,
    intraday_bars_during_trade: Sequence[MarketBar],
    features_snapshot: dict[str, Any],
    cost_model: Optional[TransactionCostModel] = None,
    is_daytrade: bool = True,
    sample_time: Optional[datetime | str] = None,
    label_start_time: Optional[datetime | str] = None,
    label_end_time: Optional[datetime | str] = None,
) -> Phase2TradeRecord:
    """Builds a validated Phase2TradeRecord with full causal and accounting verification."""
    ft = parse_phase2_timestamp(feature_time)
    st = parse_phase2_timestamp(signal_time)
    dt = parse_phase2_timestamp(decision_available_time)
    et = parse_phase2_timestamp(execution_time)
    xt = parse_phase2_timestamp(exit_time)

    validate_causal_order(ft, st, dt, et)
    if xt <= et:
        raise InvalidTradeParametersError(f"exit_time ({xt}) must be strictly after execution_time ({et})")

    # Sample and label intervals for purging
    st_sample = parse_phase2_timestamp(sample_time) if sample_time else st
    l_start = parse_phase2_timestamp(label_start_time) if label_start_time else et
    l_end = parse_phase2_timestamp(label_end_time) if label_end_time else xt

    if l_start > l_end:
        raise InvalidTradeParametersError(f"label_start_time ({l_start}) cannot exceed label_end_time ({l_end})")

    dir_upper = direction.upper()
    initial_risk_per_share = abs(actual_entry_price - stop_loss_price)
    initial_risk_amount = round(initial_risk_per_share * quantity, 4)

    # Compute PnL with Single Source of Truth
    pnl_data = calculate_single_source_pnl(
        theoretical_entry_price=theoretical_entry_price,
        actual_entry_price=actual_entry_price,
        theoretical_exit_price=theoretical_exit_price,
        actual_exit_price=actual_exit_price,
        quantity=quantity,
        cost_model=cost_model,
        is_daytrade=is_daytrade,
        direction=dir_upper,
    )

    # Compute explicit MFE / MAE
    if intraday_bars_during_trade:
        highs = [b.high for b in intraday_bars_during_trade]
        lows = [b.low for b in intraday_bars_during_trade]
        max_high = max(highs)
        min_low = min(lows)
    else:
        max_high = max(actual_entry_price, actual_exit_price)
        min_low = min(actual_entry_price, actual_exit_price)

    if dir_upper == "LONG":
        mfe_price = max(actual_entry_price, max_high)
        mae_price = min(actual_entry_price, min_low)
        mfe_pct = (mfe_price - actual_entry_price) / actual_entry_price * 100.0
        mae_pct = (actual_entry_price - mae_price) / actual_entry_price * 100.0
        mfe_R = (mfe_price - actual_entry_price) / initial_risk_per_share if initial_risk_per_share > 0 else 0.0
        mae_R = -(actual_entry_price - mae_price) / initial_risk_per_share if initial_risk_per_share > 0 else 0.0
    else:  # SHORT
        mfe_price = min(actual_entry_price, min_low)
        mae_price = max(actual_entry_price, max_high)
        mfe_pct = (actual_entry_price - mfe_price) / actual_entry_price * 100.0
        mae_pct = (mae_price - actual_entry_price) / actual_entry_price * 100.0
        mfe_R = (actual_entry_price - mfe_price) / initial_risk_per_share if initial_risk_per_share > 0 else 0.0
        mae_R = -(mae_price - actual_entry_price) / initial_risk_per_share if initial_risk_per_share > 0 else 0.0

    pnl_R = pnl_data["net_pnl"] / initial_risk_amount if initial_risk_amount > 0 else 0.0

    return Phase2TradeRecord(
        symbol=symbol,
        direction=dir_upper,
        quantity=quantity,
        feature_time=ft.isoformat(),
        signal_time=st.isoformat(),
        decision_available_time=dt.isoformat(),
        execution_time=et.isoformat(),
        exit_time=xt.isoformat(),
        sample_time=st_sample.isoformat(),
        label_start_time=l_start.isoformat(),
        label_end_time=l_end.isoformat(),
        theoretical_entry_price=round(theoretical_entry_price, 4),
        actual_entry_price=round(actual_entry_price, 4),
        theoretical_exit_price=round(theoretical_exit_price, 4),
        actual_exit_price=round(actual_exit_price, 4),
        stop_loss_price=round(stop_loss_price, 4),
        initial_risk_per_share=round(initial_risk_per_share, 4),
        initial_risk_amount=round(initial_risk_amount, 4),
        mfe_price=round(mfe_price, 4),
        mae_price=round(mae_price, 4),
        mfe_pct=round(mfe_pct, 4),
        mae_pct=round(mae_pct, 4),
        mfe_R=round(mfe_R, 4),
        mae_R=round(mae_R, 4),
        gross_pnl_actual=pnl_data["gross_pnl_actual"],
        gross_pnl_theoretical=pnl_data["gross_pnl_theoretical"],
        commission_total=pnl_data["total_commission"],
        tax_total=pnl_data["tax"],
        slippage_cost=pnl_data["slippage_cost"],
        net_pnl=pnl_data["net_pnl"],
        pnl_R=round(pnl_R, 4),
        features_snapshot=dict(features_snapshot),
    )
