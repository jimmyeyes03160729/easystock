"""Candidate P2B_02: Range Expansion.

Research Concept:
- A transition from range compression to range expansion.
- The current bar's High-Low range expands significantly relative to the rolling average range
  of preceding bars (expansion_ratio = current_range / prior_rolling_range).
- Parameter grids: [1.2, 1.5, 1.8] (AI_QUANTIZED, Knowledge V2 Research Parameter Candidate).
- Direction:
  - Bullish expansion: Close > Open and Close Location Value (CLV) >= 0.0 (upper half).
  - Bearish expansion: Close < Open and Close Location Value (CLV) <= 0.0 (lower half).
- Strict causality: Only uses completed bars as-of bar_close_time.
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from daytrade_learning.knowledge_v1.causal_tools import CompletedBar
from daytrade_learning.knowledge_v1.features import KnowledgeV1Features
from ..execution import MarketBar


@dataclass(frozen=True)
class RangeExpansionSignal:
    candidate_id: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    signal_time: datetime
    feature_time: datetime
    threshold: float
    expansion_ratio: float
    stop_loss_price: float
    trigger_bar: MarketBar
    features: dict[str, Any]


class RangeExpansionDetector:
    """Detects causal range expansion signals."""

    CANDIDATE_ID = "P2B_02_RANGE_EXPANSION"

    def __init__(
        self,
        expansion_thresholds: Sequence[float] = (1.2, 1.5, 1.8),
        lookback_bars: int = 10,
    ):
        self.expansion_thresholds = list(expansion_thresholds)
        self.lookback_bars = lookback_bars

    def detect_signals(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
        threshold: float = 1.5,
    ) -> list[RangeExpansionSignal]:
        """Scans a series of completed MarketBars for range expansion signals."""
        signals: list[RangeExpansionSignal] = []
        n = len(bars)
        if n < self.lookback_bars + 1:
            return signals

        for i in range(self.lookback_bars, n):
            current_bar = bars[i]
            prior_bars = bars[i - self.lookback_bars : i]

            current_range = current_bar.high - current_bar.low
            if current_range <= 0:
                continue

            prior_ranges = [b.high - b.low for b in prior_bars if (b.high - b.low) > 0]
            if not prior_ranges:
                continue

            avg_prior_range = sum(prior_ranges) / len(prior_ranges)
            if avg_prior_range <= 0:
                continue

            expansion_ratio = current_range / avg_prior_range
            if expansion_ratio < threshold:
                continue

            # Convert to CompletedBar for CLV evaluation
            comp_bar = CompletedBar(
                start_time=current_bar.bar_open_time,
                end_time=current_bar.bar_close_time,
                open=current_bar.open,
                high=current_bar.high,
                low=current_bar.low,
                close=current_bar.close,
                volume=current_bar.volume,
            )
            clv = KnowledgeV1Features.close_location_value(comp_bar)
            if clv is None:
                continue

            st = current_bar.bar_close_time
            ft = st

            # Determine direction
            if current_bar.close > current_bar.open and clv >= 0.0:
                direction = "LONG"
                stop_loss = round(current_bar.low, 4)
            elif current_bar.close < current_bar.open and clv <= 0.0:
                direction = "SHORT"
                stop_loss = round(current_bar.high, 4)
            else:
                continue

            features = {
                "expansion_ratio": round(expansion_ratio, 4),
                "current_range": round(current_range, 4),
                "avg_prior_range": round(avg_prior_range, 4),
                "close_location_value": clv,
                "threshold": threshold,
            }

            signals.append(
                RangeExpansionSignal(
                    candidate_id=self.CANDIDATE_ID,
                    symbol=symbol,
                    direction=direction,
                    signal_time=st,
                    feature_time=ft,
                    threshold=threshold,
                    expansion_ratio=round(expansion_ratio, 4),
                    stop_loss_price=stop_loss,
                    trigger_bar=current_bar,
                    features=features,
                )
            )

        return signals
