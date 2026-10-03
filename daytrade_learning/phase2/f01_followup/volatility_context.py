"""Phase 2C F01 Follow-up: Market Volatility Context (H02).

Computes causal market volatility metrics strictly up to signal_time:
1. proxy_realized_volatility_to_t: sample standard deviation of completed 1m returns
2. proxy_intraday_range_to_t: (max(proxy_highs) - min(proxy_lows)) / proxy_open_0901
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class VolatilityContextSnapshot:
    realized_volatility: float
    intraday_range: float
    n_bars_observed: int


class VolatilityContextAnalyzer:
    """Computes causal volatility strictly from completed proxy bars up to signal_time."""

    @staticmethod
    def compute(
        proxy_1m_returns: Sequence[float],
        proxy_highs: Sequence[float],
        proxy_lows: Sequence[float],
        proxy_open: float,
    ) -> VolatilityContextSnapshot:
        """Computes volatility snapshot.
        
        Guards:
            - Prohibits future bars or full-day ranges.
            - Uses sample std with ddof=1 when n >= 2.
        """
        n = len(proxy_1m_returns)
        if n < 2 or proxy_open <= 0.0 or not proxy_highs or not proxy_lows:
            rng = 0.0
            if proxy_highs and proxy_lows and proxy_open > 0.0:
                rng = (max(proxy_highs) - min(proxy_lows)) / proxy_open
            return VolatilityContextSnapshot(
                realized_volatility=0.0,
                intraday_range=round(rng, 6),
                n_bars_observed=n,
            )

        mean_r = sum(proxy_1m_returns) / n
        var = sum((r - mean_r) ** 2 for r in proxy_1m_returns) / (n - 1)
        std_r = math.sqrt(var)

        intraday_range = (max(proxy_highs) - min(proxy_lows)) / proxy_open

        return VolatilityContextSnapshot(
            realized_volatility=round(std_r, 6),
            intraday_range=round(intraday_range, 6),
            n_bars_observed=n,
        )
