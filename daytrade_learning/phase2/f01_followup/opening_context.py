"""Phase 2C F01 Follow-up: Opening Direction Context (H03).

Computes opening directional features with strict temporal causality and right-edge semantics:
1. 15m opening context: window = [09:00, 09:15), available strictly at or after 09:15:00.
   - For signals emitted at 09:14:59 (or 09:14 in 1-minute resolution), 15m metrics are strictly NOT_AVAILABLE.
   - For signals emitted at 09:15:00 or later, 15m metrics are available.
2. 30m opening context: window = [09:00, 09:30), available strictly at or after 09:30:00.
   - For signals emitted at 09:29:59 (or 09:29 in 1-minute resolution), 30m metrics are strictly NOT_AVAILABLE.
   - For signals emitted at 09:30:00 or later, 30m metrics are available.

Strata labels (pre-registered):
- OPENING_DIRECTION_POSITIVE (return > +0.05%)
- OPENING_DIRECTION_NEUTRAL  (-0.05% <= return <= +0.05%)
- OPENING_DIRECTION_NEGATIVE (return < -0.05%)
- NOT_AVAILABLE              (window not yet completed or missing data)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional


class OpeningWindowUnavailableError(ValueError):
    """Raised when an opening window feature is accessed before the window has completed."""
    pass


@dataclass(frozen=True)
class OpeningContextSnapshot:
    signal_time: datetime
    is_15m_available: bool
    is_30m_available: bool
    opening_15m_return: Optional[float]
    opening_15m_direction: str  # "OPENING_DIRECTION_POSITIVE", "OPENING_DIRECTION_NEGATIVE", "OPENING_DIRECTION_NEUTRAL", or "NOT_AVAILABLE"
    opening_30m_return: Optional[float]
    opening_30m_direction: str


class OpeningContextAnalyzer:
    """Extracts causal opening window metrics strictly after window completion."""

    TIME_0915 = time(9, 15, 0)
    TIME_0930 = time(9, 30, 0)

    @classmethod
    def compute(
        cls,
        signal_dt: datetime,
        proxy_open_0901: float,
        proxy_close_0915: Optional[float],
        proxy_close_0930: Optional[float],
    ) -> OpeningContextSnapshot:
        """Computes opening direction features.
        
        Guards:
            - If signal_dt.time() < 09:15:00, 15m metrics are strictly NOT_AVAILABLE (return is None).
            - If signal_dt.time() < 09:30:00, 30m metrics are strictly NOT_AVAILABLE (return is None).
        """
        sig_time = signal_dt.time()
        is_15m_avail = (sig_time >= cls.TIME_0915) and (proxy_close_0915 is not None) and (proxy_open_0901 > 0.0)
        is_30m_avail = (sig_time >= cls.TIME_0930) and (proxy_close_0930 is not None) and (proxy_open_0901 > 0.0)

        ret_15m = None
        dir_15m = "NOT_AVAILABLE"
        if is_15m_avail:
            ret_15m = round((proxy_close_0915 - proxy_open_0901) / proxy_open_0901, 6)
            if ret_15m > 0.0005:
                dir_15m = "OPENING_DIRECTION_POSITIVE"
            elif ret_15m < -0.0005:
                dir_15m = "OPENING_DIRECTION_NEGATIVE"
            else:
                dir_15m = "OPENING_DIRECTION_NEUTRAL"

        ret_30m = None
        dir_30m = "NOT_AVAILABLE"
        if is_30m_avail:
            ret_30m = round((proxy_close_0930 - proxy_open_0901) / proxy_open_0901, 6)
            if ret_30m > 0.0005:
                dir_30m = "OPENING_DIRECTION_POSITIVE"
            elif ret_30m < -0.0005:
                dir_30m = "OPENING_DIRECTION_NEGATIVE"
            else:
                dir_30m = "OPENING_DIRECTION_NEUTRAL"

        return OpeningContextSnapshot(
            signal_time=signal_dt,
            is_15m_available=is_15m_avail,
            is_30m_available=is_30m_avail,
            opening_15m_return=ret_15m,
            opening_15m_direction=dir_15m,
            opening_30m_return=ret_30m,
            opening_30m_direction=dir_30m,
        )
