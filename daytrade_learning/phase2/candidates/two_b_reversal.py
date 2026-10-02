"""Candidate P2B_03: 2B Reversal Pattern.

Research Concept (Victor Sperandeo / Trader Vic 2B Rule):
- In an uptrend/downtrend, price makes a new high/low beyond a previously confirmed swing pivot.
- However, price immediately fails to sustain the breakout and within 1-3 bars closes back
  within the prior range, trapping breakout traders and triggering a sharp reversal.
- Strict Causality Requirements:
  - Pivot must be confirmed before breakout evaluation: pivot_time <= confirmation_time.
  - Breakout occurs strictly after confirmation_time.
  - Reversal confirmation occurs when bar closes back inside the level: signal_time.
  - Strict ordering: pivot_time <= confirmation_time <= breakout_time <= signal_time.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from daytrade_learning.knowledge_v1.causal_tools import CompletedBar, CausalSwingSegmenter
from ..execution import MarketBar


@dataclass(frozen=True)
class TwoBSignal:
    candidate_id: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    pivot_time: datetime
    confirmation_time: datetime
    signal_time: datetime
    feature_time: datetime
    pivot_price: float
    breakout_price: float
    stop_loss_price: float
    trigger_bar: MarketBar
    features: dict[str, Any]


class TwoBReversalDetector:
    """Detects causal 2B false breakout reversal signals."""

    CANDIDATE_ID = "P2B_03_2B_REVERSAL"

    def __init__(
        self,
        pivot_confirmation_bars: int = 2,
        max_failure_bars: int = 3,
    ):
        self.pivot_confirmation_bars = pivot_confirmation_bars
        self.max_failure_bars = max_failure_bars

    def detect_signals(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
        direction: str = "SHORT",  # Default bearish 2B at high
    ) -> list[TwoBSignal]:
        """Scans a series of completed MarketBars causally for 2B reversal signals."""
        signals: list[TwoBSignal] = []
        n = len(bars)
        min_required = 2 * self.pivot_confirmation_bars + 3
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
        pivot_type = "HIGH" if dir_upper == "SHORT" else "LOW"

        for i in range(min_required, n + 1):
            history_slice = completed_bars[:i]
            latest_bar = bars[i - 1]

            # Find latest causally confirmed pivot strictly prior to the current test window
            # Lookback up to i - 1 to find a confirmed pivot
            pivot = CausalSwingSegmenter.find_latest_confirmed_pivot(
                history_slice[: -1],  # Exclude latest bar
                confirmation_bars=self.pivot_confirmation_bars,
                pivot_type=pivot_type,
            )
            if pivot is None:
                continue

            conf_idx = pivot.confirmed_index
            # Check bars strictly after confirmation for false breakout
            post_conf_bars = history_slice[conf_idx + 1 : i]
            if not post_conf_bars or len(post_conf_bars) > self.max_failure_bars + 2:
                continue

            if dir_upper == "SHORT":
                # Bearish 2B: broke above pivot_price, then latest bar closed back below
                breakout_found = any(b.high > pivot.pivot_price for b in post_conf_bars)
                if not breakout_found:
                    continue

                # Latest bar must fail and close below pivot_price
                if latest_bar.close >= pivot.pivot_price:
                    continue

                # Ensure previous bar actually penetrated above
                prior_penetration = max(b.high for b in post_conf_bars)
                stop_loss = round(prior_penetration, 4)
                if stop_loss <= latest_bar.close:
                    # Inconsistent stop
                    continue

                st = latest_bar.bar_close_time
                ft = st

                features = {
                    "pivot_price": pivot.pivot_price,
                    "breakout_high": prior_penetration,
                    "close_below_pivot": round(pivot.pivot_price - latest_bar.close, 4),
                    "pivot_time": pivot.confirmed_time.isoformat(),
                }

                signals.append(
                    TwoBSignal(
                        candidate_id=self.CANDIDATE_ID,
                        symbol=symbol,
                        direction="SHORT",
                        pivot_time=pivot.pivot_bar.end_time,
                        confirmation_time=pivot.confirmed_time,
                        signal_time=st,
                        feature_time=ft,
                        pivot_price=pivot.pivot_price,
                        breakout_price=prior_penetration,
                        stop_loss_price=stop_loss,
                        trigger_bar=latest_bar,
                        features=features,
                    )
                )

            elif dir_upper == "LONG":
                # Bullish 2B: broke below pivot_price, then latest bar closed back above
                breakdown_found = any(b.low < pivot.pivot_price for b in post_conf_bars)
                if not breakdown_found:
                    continue

                if latest_bar.close <= pivot.pivot_price:
                    continue

                prior_penetration = min(b.low for b in post_conf_bars)
                stop_loss = round(prior_penetration, 4)
                if stop_loss >= latest_bar.close:
                    continue

                st = latest_bar.bar_close_time
                ft = st

                features = {
                    "pivot_price": pivot.pivot_price,
                    "breakout_low": prior_penetration,
                    "close_above_pivot": round(latest_bar.close - pivot.pivot_price, 4),
                    "pivot_time": pivot.confirmed_time.isoformat(),
                }

                signals.append(
                    TwoBSignal(
                        candidate_id=self.CANDIDATE_ID,
                        symbol=symbol,
                        direction="LONG",
                        pivot_time=pivot.pivot_bar.end_time,
                        confirmation_time=pivot.confirmed_time,
                        signal_time=st,
                        feature_time=ft,
                        pivot_price=pivot.pivot_price,
                        breakout_price=prior_penetration,
                        stop_loss_price=stop_loss,
                        trigger_bar=latest_bar,
                        features=features,
                    )
                )

        return signals
