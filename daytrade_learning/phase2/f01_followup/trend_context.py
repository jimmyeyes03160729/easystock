"""Phase 2C F01 Follow-up: Market Trend Strength Context (H01).

Calculates causal trend features for the leave-one-out market proxy up to signal_time:
1. proxy_intraday_return: (proxy_close_t - proxy_open_0901) / proxy_open_0901
2. proxy_direction_consistency: fraction of causal 1m bars aligned with overall direction
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class TrendContextSnapshot:
    proxy_intraday_return: float
    proxy_direction_consistency: float
    n_bars_observed: int


class TrendContextAnalyzer:
    """Computes causal trend strength from completed proxy 1m return series."""

    @staticmethod
    def compute(proxy_1m_returns: Sequence[float], proxy_open: float, proxy_current: float) -> TrendContextSnapshot:
        """Computes trend metrics strictly from observations up to signal_time.
        
        Args:
            proxy_1m_returns: Sequence of causal 1m returns from 09:01 to signal_time.
            proxy_open: Proxy level at session open (09:01).
            proxy_current: Proxy level at current bar close (signal_time).
        """
        n = len(proxy_1m_returns)
        if n == 0 or proxy_open <= 0.0:
            return TrendContextSnapshot(
                proxy_intraday_return=0.0,
                proxy_direction_consistency=0.0,
                n_bars_observed=0,
            )

        intraday_ret = (proxy_current - proxy_open) / proxy_open
        overall_sign = 1 if intraday_ret > 0 else (-1 if intraday_ret < 0 else 0)

        if overall_sign == 0:
            consistency = 0.5
        else:
            aligned = sum(1 for r in proxy_1m_returns if (r > 0 and overall_sign > 0) or (r < 0 and overall_sign < 0))
            consistency = aligned / n

        return TrendContextSnapshot(
            proxy_intraday_return=round(intraday_ret, 6),
            proxy_direction_consistency=round(consistency, 4),
            n_bars_observed=n,
        )
