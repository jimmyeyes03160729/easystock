"""Phase 2C F01 Market Context Follow-up Study package.

Architectural boundaries:
- RESEARCH_ONLY = True
- INERT_BY_DEFAULT = True
- No production imports, no real trading, no strategy promotion.
"""
from __future__ import annotations

from .trend_context import (
    TrendContextSnapshot,
    TrendContextAnalyzer,
)

from .volatility_context import (
    VolatilityContextSnapshot,
    VolatilityContextAnalyzer,
)

from .opening_context import (
    OpeningWindowUnavailableError,
    OpeningContextSnapshot,
    OpeningContextAnalyzer,
)

from .breadth_context import (
    BreadthContextSnapshot,
    BreadthContextAnalyzer,
    CausalityOrMetadataFailure,
)

from .official_context import (
    OfficialContextSnapshot,
    OfficialMarketContextProvider,
    StandbyOfficialContextProvider,
)

from .result_store import (
    MechanismTradeRecord,
    MechanismAccumulator,
)

from .mechanism_runner import (
    MechanismRunResult,
    MechanismRunner,
    classify_time_of_day,
    assert_h07_descriptive_only,
)

__all__ = [
    "TrendContextSnapshot",
    "TrendContextAnalyzer",
    "VolatilityContextSnapshot",
    "VolatilityContextAnalyzer",
    "OpeningWindowUnavailableError",
    "OpeningContextSnapshot",
    "OpeningContextAnalyzer",
    "BreadthContextSnapshot",
    "BreadthContextAnalyzer",
    "CausalityOrMetadataFailure",
    "OfficialContextSnapshot",
    "OfficialMarketContextProvider",
    "StandbyOfficialContextProvider",
    "MechanismTradeRecord",
    "MechanismAccumulator",
    "MechanismRunResult",
    "MechanismRunner",
    "classify_time_of_day",
    "assert_h07_descriptive_only",
]
