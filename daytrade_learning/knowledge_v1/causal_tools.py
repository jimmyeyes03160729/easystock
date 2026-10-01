"""Causal timing and look-ahead defense tools for Knowledge V1 research.

Strict Point-In-Time (PIT) requirements:
- Strictly only exposures completed bars where end_time <= t.
- Rejects future bars and partial uncompleted bars from completed stats.
- Causal Swing Segmentation: No future-leaking ZigZag. A swing pivot is confirmed
  only after c subsequent bars close without exceeding the pivot price.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Sequence

TPE = timezone(timedelta(hours=8))


def parse_timestamp(value: Any) -> datetime:
    """Normalize input timestamps to Asia/Taipei timezone."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=TPE) if value.tzinfo is None else value.astimezone(TPE)
    if isinstance(value, (int, float)):
        val = float(value)
        # Handle nanoseconds or seconds
        divisor = 1e9 if abs(val) >= 1e17 else 1e6 if abs(val) >= 1e14 else 1e3 if abs(val) >= 1e11 else 1.0
        return datetime.fromtimestamp(val / divisor, timezone.utc).astimezone(TPE)
    if isinstance(value, str):
        val = value.replace('Z', '+00:00')
        dt = datetime.fromisoformat(val)
        return dt.replace(tzinfo=TPE) if dt.tzinfo is None else dt.astimezone(TPE)
    raise TypeError(f"Unsupported timestamp format: {type(value)}")


@dataclass(frozen=True)
class CompletedBar:
    start_time: datetime
    end_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0

    def __post_init__(self):
        if self.high < self.low:
            raise ValueError(f"High {self.high} cannot be less than low {self.low}")
        if self.start_time > self.end_time:
            raise ValueError("Start time cannot be after end time")


class CausalBarSeries:
    """Encapsulates a series of bars and enforces strictly causal as-of queries."""

    def __init__(self, bars: Sequence[dict | CompletedBar]):
        self._bars: list[CompletedBar] = []
        for b in bars:
            if isinstance(b, CompletedBar):
                self._bars.append(b)
            elif isinstance(b, dict):
                # Standardize dictionary bars
                end = parse_timestamp(b.get("at") or b.get("end_time") or b.get("ts"))
                start = parse_timestamp(b.get("start_time") or (end - timedelta(minutes=1)))
                self._bars.append(CompletedBar(
                    start_time=start,
                    end_time=end,
                    open=float(b.get("open") or b.get("Open")),
                    high=float(b.get("high") or b.get("High")),
                    low=float(b.get("low") or b.get("Low")),
                    close=float(b.get("close") or b.get("Close")),
                    volume=float(b.get("volume") or b.get("Volume") or 0.0),
                    amount=float(b.get("amount") or b.get("Amount") or 0.0),
                ))
            else:
                raise TypeError(f"Invalid bar type: {type(b)}")
        # Sort chronologically
        self._bars.sort(key=lambda x: x.end_time)

    def as_of(self, t: Any) -> list[CompletedBar]:
        """Return all completed bars whose completion end_time <= t."""
        ts = parse_timestamp(t)
        return [b for b in self._bars if b.end_time <= ts]

    def latest_completed(self, t: Any) -> Optional[CompletedBar]:
        valid = self.as_of(t)
        return valid[-1] if valid else None


@dataclass(frozen=True)
class CausalSwingPivot:
    pivot_type: str  # 'HIGH' or 'LOW'
    pivot_index: int
    pivot_bar: CompletedBar
    confirmed_index: int
    confirmed_bar: CompletedBar
    pivot_price: float
    confirmed_time: datetime


class CausalSwingSegmenter:
    """Detects swing pivots strictly without look-ahead bias.

    A swing high at bar k is confirmed at bar k+c if all bars in [k-c, k+c]
    have high <= bar[k].high.
    Crucially, the pivot is NOT available at time bar[k].end_time;
    it only becomes available to strategies at time bar[k+c].end_time.
    """

    @staticmethod
    def find_latest_confirmed_pivot(
        bars: Sequence[CompletedBar],
        confirmation_bars: int = 2,
        pivot_type: str = "HIGH"
    ) -> Optional[CausalSwingPivot]:
        c = max(1, int(confirmation_bars))
        n = len(bars)
        if n < 2 * c + 1:
            return None

        # Search backwards from the most recently confirmed index
        for k in range(n - c - 1, c - 1, -1):
            target = bars[k]
            is_pivot = True
            if pivot_type.upper() == "HIGH":
                target_price = target.high
                for j in range(k - c, k + c + 1):
                    if j != k and bars[j].high > target_price:
                        is_pivot = False
                        break
            elif pivot_type.upper() == "LOW":
                target_price = target.low
                for j in range(k - c, k + c + 1):
                    if j != k and bars[j].low < target_price:
                        is_pivot = False
                        break
            else:
                raise ValueError(f"Unknown pivot type: {pivot_type}")

            if is_pivot:
                confirmed_bar = bars[k + c]
                return CausalSwingPivot(
                    pivot_type=pivot_type.upper(),
                    pivot_index=k,
                    pivot_bar=target,
                    confirmed_index=k + c,
                    confirmed_bar=confirmed_bar,
                    pivot_price=target_price,
                    confirmed_time=confirmed_bar.end_time
                )
        return None

    @staticmethod
    def volume_decay_ratio(
        bars: Sequence[CompletedBar],
        confirmation_bars: int = 2
    ) -> Optional[float]:
        """Calculates causal pullback volume decay ratio:
        pullback_shares_per_second / impulse_shares_per_second.
        """
        high_pivot = CausalSwingSegmenter.find_latest_confirmed_pivot(
            bars, confirmation_bars=confirmation_bars, pivot_type="HIGH"
        )
        if not high_pivot:
            return None

        k = high_pivot.pivot_index
        # Look for preceding low pivot before high pivot
        prior_bars = bars[:k]
        low_pivot = CausalSwingSegmenter.find_latest_confirmed_pivot(
            prior_bars, confirmation_bars=max(1, confirmation_bars // 2), pivot_type="LOW"
        )

        low_index = low_pivot.pivot_index if low_pivot else max(0, k - 5)
        impulse_bars = bars[low_index:k + 1]
        pullback_bars = bars[k + 1:]

        if not impulse_bars or not pullback_bars:
            return None

        impulse_vol = sum(b.volume for b in impulse_bars)
        pullback_vol = sum(b.volume for b in pullback_bars)

        impulse_sec = max(1.0, (impulse_bars[-1].end_time - impulse_bars[0].start_time).total_seconds())
        pullback_sec = max(1.0, (pullback_bars[-1].end_time - pullback_bars[0].start_time).total_seconds())

        impulse_rate = impulse_vol / impulse_sec
        pullback_rate = pullback_vol / pullback_sec

        if impulse_rate <= 0:
            return None

        return round(pullback_rate / impulse_rate, 4)
