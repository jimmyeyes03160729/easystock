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
from enum import Enum
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


# Historical vs Streaming K-Bar Labeling Semantics Lock
HISTORICAL_KBAR_LABEL: str = "RIGHT_EDGE"
STREAMING_KBAR_LABEL: str = "START_TIME"

# Expected Session Timestamps (TWSE 09:01-13:25 continuous + 13:30 close = 266 marks)
EXPECTED_SESSION_MINUTES: frozenset[int] = frozenset(set(range(9 * 60 + 1, 13 * 60 + 26)) | {13 * 60 + 30})

# Observed Large Gap Threshold & Diagnostic Governance Provenance
OBSERVED_LARGE_GAP_THRESHOLD: float = 0.08  # ±8.0%
OBSERVED_LARGE_GAP_PROVENANCE: dict[str, str] = {
    "status": "RESEARCH_GOVERNANCE_CANDIDATE",
    "purpose": "DIAGNOSTIC_ONLY",
    "rule": "Never determines corporate action TRUE/FALSE; never used as candidate entry filter; never used as full-run exclusion rule; never affects candidate performance verdict.",
}


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


class StockDayCompletenessStatus(str, Enum):
    COMPLETE = "COMPLETE"
    USABLE_WITH_GAPS = "USABLE_WITH_GAPS"
    PARTIAL_UNKNOWN_MISSINGNESS = "PARTIAL_UNKNOWN_MISSINGNESS"
    INVALID = "INVALID"


class MissingnessType(str, Enum):
    NONE = "NONE"
    NO_TRADE_MINUTE = "NO_TRADE_MINUTE"
    PARTIAL_UNKNOWN_MISSINGNESS = "PARTIAL_UNKNOWN_MISSINGNESS"
    OUT_OF_SESSION = "OUT_OF_SESSION"
    DUPLICATE = "DUPLICATE"
    NON_MONOTONIC = "NON_MONOTONIC"
    MISSING_SESSION_BOUNDARY = "MISSING_SESSION_BOUNDARY"
    INSUFFICIENT_BARS = "INSUFFICIENT_BARS"


class CorporateActionBoundaryStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    TRUE = "TRUE"
    FALSE = "FALSE"


@dataclass(frozen=True)
class StockDayCompletenessReport:
    symbol: str
    date_str: str
    status: StockDayCompletenessStatus
    expected_session_bars: int
    actual_bar_count: int
    missing_session_bars: int
    session_coverage_pct: float
    first_bar_time: Optional[str]
    last_bar_time: Optional[str]
    has_opening_coverage: bool
    has_closing_coverage: bool
    duplicate_count: int
    out_of_session_count: int
    monotonic_timestamp: bool
    missingness_type: MissingnessType
    corporate_action_boundary: CorporateActionBoundaryStatus = CorporateActionBoundaryStatus.UNKNOWN
    observed_large_gap: bool = False
    rejection_reason: Optional[str] = None


def assess_stock_day_completeness(
    symbol: str,
    bars: Sequence[MarketBar],
    corporate_action_boundary: CorporateActionBoundaryStatus | str = CorporateActionBoundaryStatus.UNKNOWN,
    observed_large_gap: Optional[bool] = None,
) -> StockDayCompletenessReport:
    """Classifies a symbol-day based on TWSE Expected Session Timestamp Coverage.
    
    Session Model:
    - 265 continuous trading minute marks (09:01 through 13:25).
    - 1 closing call auction match mark (13:30).
    - Total expected session timestamps: 266.
    - 13:26-13:29 are closing auction accumulation minutes with no continuous trading.
    
    Data Missingness Policy:
    - Shioaji kbars only emits bars when trades occur.
    - 1-minute bars alone cannot distinguish between NO_TRADE_MINUTE and MISSING_DATA.
    - Intermediate gaps without corruption are classified as USABLE_WITH_GAPS (PARTIAL_UNKNOWN_MISSINGNESS).
    - Arbitrary hard thresholds (e.g. >= 265) are strictly prohibited.
    """
    import datetime as dt_module

    ca_status = (
        corporate_action_boundary
        if isinstance(corporate_action_boundary, CorporateActionBoundaryStatus)
        else CorporateActionBoundaryStatus(str(corporate_action_boundary).upper())
    )

    if not bars:
        return StockDayCompletenessReport(
            symbol=symbol,
            date_str="UNKNOWN",
            status=StockDayCompletenessStatus.INVALID,
            expected_session_bars=266,
            actual_bar_count=0,
            missing_session_bars=266,
            session_coverage_pct=0.0,
            first_bar_time=None,
            last_bar_time=None,
            has_opening_coverage=False,
            has_closing_coverage=False,
            duplicate_count=0,
            out_of_session_count=0,
            monotonic_timestamp=True,
            missingness_type=MissingnessType.INSUFFICIENT_BARS,
            corporate_action_boundary=ca_status,
            observed_large_gap=False,
            rejection_reason="EMPTY_BAR_SEQUENCE",
        )

    tpe_tz = dt_module.timezone(dt_module.timedelta(hours=8))
    first_tpe = bars[0].bar_close_time.astimezone(tpe_tz)
    day = first_tpe.date()
    date_str = day.strftime("%Y-%m-%d")

    seen_times = set()
    duplicate_count = 0
    monotonic = True
    out_of_session_count = 0
    present_session_minutes = set()

    for i, b in enumerate(bars):
        t = b.bar_close_time.astimezone(tpe_tz).replace(microsecond=0)
        if t in seen_times:
            duplicate_count += 1
        seen_times.add(t)

        if i > 0 and t <= bars[i - 1].bar_close_time.astimezone(tpe_tz).replace(microsecond=0):
            monotonic = False

        t_time = t.time()
        if t_time < dt_module.time(9, 1) or t_time > dt_module.time(13, 30):
            out_of_session_count += 1
        else:
            t_min = t.hour * 60 + t.minute
            if t.date() == day and t_min in EXPECTED_SESSION_MINUTES:
                present_session_minutes.add(t_min)

    actual_count = len(bars)
    missing_session_count = 266 - len(present_session_minutes)
    coverage_pct = round((len(present_session_minutes) / 266) * 100.0, 2)

    first_time_str = bars[0].bar_open_time.astimezone(tpe_tz).isoformat()
    last_time_str = bars[-1].bar_close_time.astimezone(tpe_tz).isoformat()

    first_close_time = bars[0].bar_close_time.astimezone(tpe_tz).time()
    last_close_time = bars[-1].bar_close_time.astimezone(tpe_tz).time()

    has_opening_coverage = first_close_time <= dt_module.time(9, 5)
    has_closing_coverage = last_close_time >= dt_module.time(13, 25)

    if observed_large_gap is None:
        large_gap_detected = False
        if len(bars) > 1:
            for i in range(1, len(bars)):
                prev_c = bars[i - 1].close
                curr_o = bars[i].open
                if prev_c > 0 and abs(curr_o - prev_c) / prev_c >= 0.08:
                    large_gap_detected = True
                    break
        observed_large_gap = large_gap_detected

    rejection_reason = None
    if duplicate_count > 0:
        status = StockDayCompletenessStatus.INVALID
        m_type = MissingnessType.DUPLICATE
        rejection_reason = f"DUPLICATE_BARS_DETECTED: {duplicate_count}"
    elif not monotonic:
        status = StockDayCompletenessStatus.INVALID
        m_type = MissingnessType.NON_MONOTONIC
        rejection_reason = "NON_MONOTONIC_TIMESTAMPS"
    elif out_of_session_count > 0:
        status = StockDayCompletenessStatus.INVALID
        m_type = MissingnessType.OUT_OF_SESSION
        rejection_reason = f"OUT_OF_SESSION_BARS: {out_of_session_count}"
    elif actual_count < 10:
        status = StockDayCompletenessStatus.INVALID
        m_type = MissingnessType.INSUFFICIENT_BARS
        rejection_reason = f"INSUFFICIENT_BARS: {actual_count} < 10"
    elif not (has_opening_coverage and has_closing_coverage):
        status = StockDayCompletenessStatus.INVALID
        m_type = MissingnessType.MISSING_SESSION_BOUNDARY
        rejection_reason = f"MISSING_SESSION_BOUNDARY: open_covered={has_opening_coverage}, close_covered={has_closing_coverage}"
    elif missing_session_count == 0:
        status = StockDayCompletenessStatus.COMPLETE
        m_type = MissingnessType.NONE
        rejection_reason = None
    else:
        status = StockDayCompletenessStatus.USABLE_WITH_GAPS
        m_type = MissingnessType.PARTIAL_UNKNOWN_MISSINGNESS
        rejection_reason = "MISSING_SESSION_TIMESTAMPS: 1-minute bars alone cannot distinguish NO_TRADE_MINUTE from MISSING_DATA"

    return StockDayCompletenessReport(
        symbol=symbol,
        date_str=date_str,
        status=status,
        expected_session_bars=266,
        actual_bar_count=actual_count,
        missing_session_bars=missing_session_count,
        session_coverage_pct=coverage_pct,
        first_bar_time=first_time_str,
        last_bar_time=last_time_str,
        has_opening_coverage=has_opening_coverage,
        has_closing_coverage=has_closing_coverage,
        duplicate_count=duplicate_count,
        out_of_session_count=out_of_session_count,
        monotonic_timestamp=monotonic,
        missingness_type=m_type,
        corporate_action_boundary=ca_status,
        observed_large_gap=observed_large_gap,
        rejection_reason=rejection_reason,
    )

