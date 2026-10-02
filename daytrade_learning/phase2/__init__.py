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
    CostParameterCategory,
    CostParameterDefinition,
    COST_PARAMETER_REGISTRY,
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
    InvalidTradeParametersError,
    Phase2TradeRecord,
    create_phase2_trade,
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

__all__ = [
    "RESEARCH_ONLY",
    "INERT_BY_DEFAULT",
    "CostParameterCategory",
    "CostParameterDefinition",
    "COST_PARAMETER_REGISTRY",
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
]
