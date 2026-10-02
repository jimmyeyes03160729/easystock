"""EasyStock Daytrade Research Phase 2A - Research Foundation.

CRITICAL ARCHITECTURAL CONSTRAINTS:
- RESEARCH_ONLY = True
- INERT_BY_DEFAULT = True

Prohibitions:
- NO production strategy modification
- NO live entry trigger modification
- NO paper entry trigger modification
- NO MarketGate behavior modification
- NO PositionManager production behavior modification
- NO AI model gate enablement
- NO real trading enablement
- NO Chrome/Web UI modification
- NO VM service modification
- NO Phase 2B execution
"""
from __future__ import annotations

RESEARCH_ONLY: bool = True
INERT_BY_DEFAULT: bool = True

from .costs import (
    BASE_COMMISSION_REFERENCE_RATE,
    PARAM_BASE_COMMISSION_REFERENCE_RATE,
    PARAM_BROKER_DISCOUNT,
    PARAM_MINIMUM_FEE,
    PARAM_DAYTRADE_TAX_RATE,
    PARAM_NORMAL_TAX_RATE,
    CostParameterCategory,
    CostParameterDefinition,
    COST_PARAMETER_REGISTRY,
    PARAM_SLIPPAGE_GRID_TICKS,
    PARAM_SLIPPAGE_GRID,
    get_twse_tick_size,
    round_to_twse_tick,
    TransactionCostModel,
    calculate_derived_slippage_cost,
    calculate_single_source_pnl,
)

from .execution import (
    CausalityViolationError,
    ExecutionOrderError,
    MarketBar,
    TickExecutionPoint,
    parse_phase2_timestamp,
    validate_causal_order,
    CausalExecutionClock,
)

from .dataset import (
    HISTORICAL_KBAR_LABEL,
    STREAMING_KBAR_LABEL,
    OBSERVED_LARGE_GAP_THRESHOLD,
    OBSERVED_LARGE_GAP_PROVENANCE,
    InvalidTradeParametersError,
    Phase2TradeRecord,
    create_phase2_trade,
    StockDayCompletenessStatus,
    MissingnessType,
    CorporateActionBoundaryStatus,
    StockDayCompletenessReport,
    assess_stock_day_completeness,
)

from .metrics import (
    calculate_trade_metrics,
)

from .comparator import (
    ResearchVerdict,
    ComparisonResult,
    BaselineComparator,
)

from .walkforward import (
    WalkForwardFold,
    IndexWalkForwardSplitter,
    EventWalkForwardSplitter,
)

from .provenance import (
    ProvenanceStatus,
    ProvenanceRecord,
    PHASE2_PROVENANCE_REGISTRY,
    audit_parameter_provenance,
)

from .candidates import (
    PullbackVolumeDecayDetector,
    PullbackSignal,
    RangeExpansionDetector,
    RangeExpansionSignal,
    TwoBReversalDetector,
    TwoBSignal,
    OneTwoThreeDetector,
    OneTwoThreeSignal,
)

from .research_runner import (
    ResearchRunner,
    ResearchExitPolicy,
    EXIT_FIXED_5M,
    EXIT_FIXED_15M,
    EXIT_FIXED_30M,
    EXIT_FIXED_60M,
    EXIT_STOP_TARGET_1_5R,
)

from .result_store import (
    ResearchResultStore,
    CandidateParameterResult,
)

__all__ = [
    "RESEARCH_ONLY",
    "INERT_BY_DEFAULT",
    "CostParameterCategory",
    "CostParameterDefinition",
    "COST_PARAMETER_REGISTRY",
    "PARAM_SLIPPAGE_GRID_TICKS",
    "PARAM_SLIPPAGE_GRID",
    "get_twse_tick_size",
    "round_to_twse_tick",
    "TransactionCostModel",
    "calculate_derived_slippage_cost",
    "calculate_single_source_pnl",
    "CausalityViolationError",
    "ExecutionOrderError",
    "MarketBar",
    "TickExecutionPoint",
    "parse_phase2_timestamp",
    "validate_causal_order",
    "CausalExecutionClock",
    "InvalidTradeParametersError",
    "Phase2TradeRecord",
    "create_phase2_trade",
    "StockDayCompletenessStatus",
    "MissingnessType",
    "CorporateActionBoundaryStatus",
    "StockDayCompletenessReport",
    "assess_stock_day_completeness",
    "calculate_trade_metrics",
    "ResearchVerdict",
    "ComparisonResult",
    "BaselineComparator",
    "WalkForwardFold",
    "IndexWalkForwardSplitter",
    "EventWalkForwardSplitter",
    "ProvenanceStatus",
    "ProvenanceRecord",
    "PHASE2_PROVENANCE_REGISTRY",
    "audit_parameter_provenance",
    "PullbackVolumeDecayDetector",
    "PullbackSignal",
    "RangeExpansionDetector",
    "RangeExpansionSignal",
    "TwoBReversalDetector",
    "TwoBSignal",
    "OneTwoThreeDetector",
    "OneTwoThreeSignal",
    "ResearchRunner",
    "ResearchExitPolicy",
    "EXIT_FIXED_5M",
    "EXIT_FIXED_15M",
    "EXIT_FIXED_30M",
    "EXIT_FIXED_60M",
    "EXIT_STOP_TARGET_1_5R",
    "ResearchResultStore",
    "CandidateParameterResult",
]
