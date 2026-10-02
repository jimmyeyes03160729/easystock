"""Candidate P2B_01: Pullback Volume Decay.

Research Concept:
- Strong impulse move followed by a consolidation/pullback.
- During the pullback, trading volume contracts significantly relative to impulse volume,
  signaling absence of aggressive selling (Low Volume Test).
- Provenance: Anna Coulling, Chapter 7 (A Complete Guide To Volume Price Analysis).
- Parameter grids: [0.35, 0.45, 0.50] (AI_QUANTIZED, Knowledge V2 Research Parameter Candidate).
- Strict causality: Evaluates only completed bars as-of signal_time.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from daytrade_learning.knowledge_v1.causal_tools import CompletedBar
from daytrade_learning.knowledge_v1.features import KnowledgeV1Features
from ..execution import MarketBar, parse_phase2_timestamp


@dataclass(frozen=True)
class PullbackSignal:
    candidate_id: str
    symbol: str
    direction: str  # 'LONG'
    signal_time: datetime
    feature_time: datetime
    threshold: float
    decay_ratio: float
    stop_loss_price: float
    trigger_bar: MarketBar
    features: dict[str, Any]


class PullbackVolumeDecayDetector:
    """Detects causal pullback volume decay patterns."""

    CANDIDATE_ID = "P2B_01_PULLBACK_VOLUME_DECAY"

    def __init__(
        self,
        decay_thresholds: Sequence[float] = (0.35, 0.45, 0.50),
        min_pullback_bars: int = 2,
        max_pullback_bars: int = 5,
        impulse_bars_count: int = 2,
    ):
        self.decay_thresholds = list(decay_thresholds)
        self.min_pullback_bars = min_pullback_bars
        self.max_pullback_bars = max_pullback_bars
        self.impulse_bars_count = impulse_bars_count

    def detect_signals(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
        threshold: float = 0.50,
    ) -> list[PullbackSignal]:
        """Scans a series of completed MarketBars causally for pullback volume decay signals."""
        signals: list[PullbackSignal] = []
        n = len(bars)
        min_required = self.impulse_bars_count + self.min_pullback_bars
        if n < min_required:
            return signals

        # Convert to CompletedBar for feature reuse
        completed_bars = [
            CompletedBar(
                start_time=b.bar_open_time,
                end_time=b.bar_close_time,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                amount=b.amount,
            )
            for b in bars
        ]

        for i in range(min_required, n + 1):
            window = completed_bars[:i]
            mb_window = bars[:i]
            latest_bar = mb_window[-1]

            # Try different pullback lengths
            for pb_len in range(self.min_pullback_bars, min(self.max_pullback_bars + 1, i - self.impulse_bars_count + 1)):
                pullback = window[-pb_len:]
                impulse = window[-pb_len - self.impulse_bars_count : -pb_len]

                # Check bullish impulse: Close of impulse > Open of impulse
                impulse_open = impulse[0].open
                impulse_close = impulse[-1].close
                if impulse_close <= impulse_open:
                    continue

                # Check pullback: consolidation below impulse high, but staying above impulse low
                impulse_high = max(b.high for b in impulse)
                impulse_low = min(b.low for b in impulse)
                pullback_low = min(b.low for b in pullback)
                if pullback_low <= impulse_low:
                    continue

                # Calculate volume decay ratio reusing KnowledgeV1Features
                decay = KnowledgeV1Features.pullback_vol_decay_ratio(window)
                if decay is None:
                    # Fallback to direct window volume decay ratio
                    pullback_avg = sum(b.volume for b in pullback) / max(1, len(pullback))
                    impulse_avg = sum(b.volume for b in impulse) / max(1, len(impulse))
                    if impulse_avg <= 0:
                        continue
                    decay = round(pullback_avg / impulse_avg, 4)

                if decay > threshold:
                    continue

                # Signal confirmed on the close of the pullback bar
                st = latest_bar.bar_close_time
                ft = st
                stop_loss = round(pullback_low, 4)

                clv = KnowledgeV1Features.close_location_value(pullback[-1])
                vwap_dist = KnowledgeV1Features.dist_to_bar_vwap_pct(latest_bar.close, window)

                features = {
                    "decay_ratio": round(decay, 4),
                    "pullback_bars": pb_len,
                    "impulse_gain_pct": round((impulse_close - impulse_open) / impulse_open * 100.0, 4),
                    "close_location_value": clv,
                    "dist_to_bar_vwap_pct": vwap_dist,
                    "threshold": threshold,
                }

                signals.append(
                    PullbackSignal(
                        candidate_id=self.CANDIDATE_ID,
                        symbol=symbol,
                        direction="LONG",
                        signal_time=st,
                        feature_time=ft,
                        threshold=threshold,
                        decay_ratio=round(decay, 4),
                        stop_loss_price=stop_loss,
                        trigger_bar=latest_bar,
                        features=features,
                    )
                )
                break  # Take first matching pullback pattern for this bar

        return signals
