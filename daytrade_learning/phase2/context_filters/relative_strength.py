"""Relative Strength Filter (F02) with Leave-One-Out Market Reference.

Strict Governance:
- Computes: stock_return - leave_one_out_market_proxy_return.
- Strictly excludes target symbol from the peer market benchmark.
- Strictly causal: only uses closed bars up to signal_time.
- Records metadata:
  RESEARCH_PROXY = True, OFFICIAL_INDEX = False,
  TARGET_EXCLUDED = True, SURVIVORSHIP_BIAS = True,
  POINT_IN_TIME_UNIVERSE = False.
- Keeps full three-tier segmentation:
  POSITIVE, NEUTRAL, NEGATIVE.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Optional

from ..execution import MarketBar, parse_phase2_timestamp
from .market_regime import ResearchMarketRegime

TPE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RelativeStrengthSnapshot:
    as_of: datetime
    symbol: str
    window_minutes: int
    stock_return: float
    market_return: float
    relative_strength: float  # stock_return - market_return
    tier: str  # 'POSITIVE', 'NEUTRAL', 'NEGATIVE'
    target_excluded: bool = True
    is_proxy: bool = True
    survivorship_bias: bool = True
    point_in_time_universe: bool = False


class RelativeStrengthFilter:
    """Evaluates causal relative strength between individual stock and leave-one-out market proxy."""

    def __init__(
        self,
        market_regime: ResearchMarketRegime,
        stock_bars_by_symbol: dict[str, Sequence[MarketBar]],
    ):
        self._regime = market_regime
        self._stock_bars: dict[str, list[MarketBar]] = {
            s: sorted(bars, key=lambda b: b.bar_close_time)
            for s, bars in stock_bars_by_symbol.items()
        }

    def _get_past_stock_bars(self, symbol: str, as_of: datetime) -> list[MarketBar]:
        bars = self._stock_bars.get(symbol, [])
        as_of_tpe = parse_phase2_timestamp(as_of)
        return [b for b in bars if parse_phase2_timestamp(b.bar_close_time) <= as_of_tpe]

    def compute_relative_strength(
        self,
        symbol: str,
        as_of: datetime,
        window_minutes: int = 15,
        neutral_band: float = 0.001,
    ) -> RelativeStrengthSnapshot:
        """Computes causal relative strength over the specified rolling window, strictly excluding symbol from peer proxy."""
        as_of_tpe = parse_phase2_timestamp(as_of)
        stock_bars = self._get_past_stock_bars(symbol, as_of_tpe)
        # Crucial: pass exclude_symbol=symbol to enforce LEAVE_ONE_OUT
        market_bars = self._regime.get_past_bars(as_of_tpe, exclude_symbol=symbol)

        if len(stock_bars) < 2 or len(market_bars) < 2:
            return RelativeStrengthSnapshot(
                as_of=as_of_tpe,
                symbol=symbol,
                window_minutes=window_minutes,
                stock_return=0.0,
                market_return=0.0,
                relative_strength=0.0,
                tier="NEUTRAL",
                target_excluded=True,
                is_proxy=self._regime.is_proxy,
            )

        # Stock return over window
        w_stock = min(window_minutes, len(stock_bars))
        s_now = stock_bars[-1].close
        s_prev = stock_bars[-w_stock].close
        s_ret = (s_now - s_prev) / s_prev if s_prev > 0 else 0.0

        # Market peer proxy return over window
        w_mkt = min(window_minutes, len(market_bars))
        m_now = market_bars[-1].close
        m_prev = market_bars[-w_mkt].close
        m_ret = (m_now - m_prev) / m_prev if m_prev > 0 else 0.0

        rs = s_ret - m_ret

        if rs > neutral_band:
            tier = "POSITIVE"
        elif rs < -neutral_band:
            tier = "NEGATIVE"
        else:
            tier = "NEUTRAL"

        return RelativeStrengthSnapshot(
            as_of=as_of_tpe,
            symbol=symbol,
            window_minutes=window_minutes,
            stock_return=round(s_ret, 6),
            market_return=round(m_ret, 6),
            relative_strength=round(rs, 6),
            tier=tier,
            target_excluded=True,
            is_proxy=self._regime.is_proxy,
        )

    def filter_signal(
        self,
        symbol: str,
        signal_time: datetime,
        direction: str,
        window_minutes: int = 15,
        required_tier: Optional[str] = None,
        neutral_band: float = 0.001,
    ) -> bool:
        """Determines KEEP or DROP based on causal relative strength.
        
        Default logic if required_tier is None:
        - LONG requires tier != 'NEGATIVE' (or tier == 'POSITIVE')
        - SHORT requires tier != 'POSITIVE' (or tier == 'NEGATIVE')
        """
        snapshot = self.compute_relative_strength(
            symbol=symbol,
            as_of=signal_time,
            window_minutes=window_minutes,
            neutral_band=neutral_band,
        )

        dir_upper = direction.upper()
        if required_tier:
            return snapshot.tier == required_tier.upper()

        if dir_upper == "LONG":
            return snapshot.tier in ("POSITIVE", "NEUTRAL")
        elif dir_upper == "SHORT":
            return snapshot.tier in ("NEGATIVE", "NEUTRAL")

        return True
