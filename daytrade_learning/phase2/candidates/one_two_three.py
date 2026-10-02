"""Candidate P2B_04: 1-2-3 Reversal Rule.

Research Concept (Victor Sperandeo 1-2-3 Trend Change):
- A classic trend reversal pattern consisting of 3 sequential events:
  1. Point 1: Market reaches a trend extreme (high in uptrend, low in downtrend).
  2. Event / Point 2: Price breaks the trendline and forms a swing reaction point.
  3. Event / Point 3: Retracement test that fails to make a new extreme (lower high or higher low).
  4. Confirmation: Price subsequently breaks through the Point 2 level, confirming trend reversal.

Strict Causality:
- No future pivots backfilled to historical signals.
- Events must occur in strict chronological order:
  point1_time <= point2_time <= point3_time <= signal_time <= decision_available_time < execution_time.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from daytrade_learning.knowledge_v1.causal_tools import CompletedBar, CausalSwingSegmenter
from ..execution import MarketBar


@dataclass(frozen=True)
class OneTwoThreeSignal:
    candidate_id: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    point1_time: datetime
    point2_time: datetime
    point3_time: datetime
    signal_time: datetime
    feature_time: datetime
    point1_price: float
    point2_price: float
    point3_price: float
    stop_loss_price: float
    trigger_bar: MarketBar
    features: dict[str, Any]


class OneTwoThreeDetector:
    """Detects strictly chronological 1-2-3 trend reversal patterns."""

    CANDIDATE_ID = "P2B_04_1_2_3_REVERSAL"

    def __init__(self, confirmation_bars: int = 2):
        self.confirmation_bars = confirmation_bars

    def detect_signals(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
        direction: str = "SHORT",  # Default bearish 1-2-3 reversal
    ) -> list[OneTwoThreeSignal]:
        signals: list[OneTwoThreeSignal] = []
        n = len(bars)
        min_required = 4 * self.confirmation_bars + 4
        if n < min_required:
            return signals

        completed_bars = [
            CompletedBar(
                start_time=b.bar_open_time,
                end_time=b.bar_close_time,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
            )
            for b in bars
        ]

        dir_upper = direction.upper()

        for i in range(min_required, n + 1):
            history = completed_bars[:i]
            latest_bar = bars[i - 1]

            if dir_upper == "SHORT":
                # 1. Find Point 1: Confirmed Swing High
                p1 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    history[: i - 2 * self.confirmation_bars - 2],
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="HIGH",
                )
                if p1 is None:
                    continue

                # 2. Find Point 2: Confirmed Swing Low occurring after Point 1
                bars_after_p1 = history[p1.pivot_index + 1 : i - self.confirmation_bars]
                if len(bars_after_p1) < 2 * self.confirmation_bars + 1:
                    continue

                p2 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    bars_after_p1,
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="LOW",
                )
                if p2 is None:
                    continue

                # 3. Find Point 3: Retracement High after Point 2, failing to exceed Point 1
                p2_global_idx = p1.pivot_index + 1 + p2.pivot_index
                bars_after_p2 = history[p2_global_idx + 1 : i - 1]
                if len(bars_after_p2) < 2 * self.confirmation_bars + 1:
                    continue

                p3 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    bars_after_p2,
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="HIGH",
                )
                if p3 is None:
                    continue

                # Condition 3 check: Point 3 high must be lower than Point 1 high
                if p3.pivot_price >= p1.pivot_price:
                    continue

                # 4. Confirmation: Latest bar breaks below Point 2 low
                p2_price = p2.pivot_price
                if latest_bar.close >= p2_price:
                    continue
                # Ensure prior bar was above or at p2_price
                prior_bar = bars[i - 2]
                if prior_bar.close < p2_price:
                    continue

                st = latest_bar.bar_close_time
                ft = st
                stop_loss = round(p3.pivot_price, 4)
                if stop_loss <= latest_bar.close:
                    continue

                features = {
                    "p1_price": p1.pivot_price,
                    "p2_price": p2.pivot_price,
                    "p3_price": p3.pivot_price,
                    "breakout_depth": round(p2.pivot_price - latest_bar.close, 4),
                }

                signals.append(
                    OneTwoThreeSignal(
                        candidate_id=self.CANDIDATE_ID,
                        symbol=symbol,
                        direction="SHORT",
                        point1_time=p1.pivot_bar.end_time,
                        point2_time=p2.pivot_bar.end_time,
                        point3_time=p3.pivot_bar.end_time,
                        signal_time=st,
                        feature_time=ft,
                        point1_price=p1.pivot_price,
                        point2_price=p2.pivot_price,
                        point3_price=p3.pivot_price,
                        stop_loss_price=stop_loss,
                        trigger_bar=latest_bar,
                        features=features,
                    )
                )

            elif dir_upper == "LONG":
                # Bullish 1-2-3 reversal
                p1 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    history[: i - 2 * self.confirmation_bars - 2],
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="LOW",
                )
                if p1 is None:
                    continue

                bars_after_p1 = history[p1.pivot_index + 1 : i - self.confirmation_bars]
                if len(bars_after_p1) < 2 * self.confirmation_bars + 1:
                    continue

                p2 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    bars_after_p1,
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="HIGH",
                )
                if p2 is None:
                    continue

                p2_global_idx = p1.pivot_index + 1 + p2.pivot_index
                bars_after_p2 = history[p2_global_idx + 1 : i - 1]
                if len(bars_after_p2) < 2 * self.confirmation_bars + 1:
                    continue

                p3 = CausalSwingSegmenter.find_latest_confirmed_pivot(
                    bars_after_p2,
                    confirmation_bars=self.confirmation_bars,
                    pivot_type="LOW",
                )
                if p3 is None:
                    continue

                # Point 3 low must be higher than Point 1 low
                if p3.pivot_price <= p1.pivot_price:
                    continue

                p2_price = p2.pivot_price
                if latest_bar.close <= p2_price:
                    continue
                prior_bar = bars[i - 2]
                if prior_bar.close > p2_price:
                    continue

                st = latest_bar.bar_close_time
                ft = st
                stop_loss = round(p3.pivot_price, 4)
                if stop_loss >= latest_bar.close:
                    continue

                features = {
                    "p1_price": p1.pivot_price,
                    "p2_price": p2.pivot_price,
                    "p3_price": p3.pivot_price,
                    "breakout_depth": round(latest_bar.close - p2.pivot_price, 4),
                }

                signals.append(
                    OneTwoThreeSignal(
                        candidate_id=self.CANDIDATE_ID,
                        symbol=symbol,
                        direction="LONG",
                        point1_time=p1.pivot_bar.end_time,
                        point2_time=p2.pivot_bar.end_time,
                        point3_time=p3.pivot_bar.end_time,
                        signal_time=st,
                        feature_time=ft,
                        point1_price=p1.pivot_price,
                        point2_price=p2.pivot_price,
                        point3_price=p3.pivot_price,
                        stop_loss_price=stop_loss,
                        trigger_bar=latest_bar,
                        features=features,
                    )
                )

        return signals
