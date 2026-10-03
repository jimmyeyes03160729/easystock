"""Higher-Timeframe Context Filter & Causal Aggregator (F04).

Strict Causal & Closed-Bar Rules:
- Aggregates 1m bars into 5m, 15m, 30m bars strictly causally.
- ONLY completed, fully closed higher-timeframe bars are exposed.
- Example: At signal_time = 09:37, 5m context can ONLY see the 09:30-09:35 completed bar.
  The in-progress forming bar 09:35-09:40 is STRICTLY FORBIDDEN.
  Accessing an unclosed bar raises IncompleteBarAccessError.
- Future bars after signal_time never affect the aggregated past HTF bars.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Optional

from ..execution import MarketBar, parse_phase2_timestamp

TPE = timezone(timedelta(hours=8))


class IncompleteBarAccessError(RuntimeError):
    """Raised when an unfinished, forming higher-timeframe bar is accessed."""
    pass


@dataclass(frozen=True)
class HigherTimeframeSnapshot:
    as_of: datetime
    symbol: str
    timeframe: str  # '5m', '15m', '30m'
    last_closed_bar_open_time: datetime
    last_closed_bar_close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    is_bullish: bool  # close >= open
    htf_vwap: float
    close_above_vwap: bool
    return_pct: float  # (close - open) / open


class HigherTimeframeAggregator:
    """Aggregates 1-minute bars into 5m, 15m, 30m bars strictly enforcing closed-bar boundaries."""

    TIMEFRAME_MINUTES = {
        "5m": 5,
        "15m": 15,
        "30m": 30,
    }

    def __init__(self, one_minute_bars: Sequence[MarketBar]):
        self._bars_1m = sorted(one_minute_bars, key=lambda b: b.bar_close_time)

    @classmethod
    def _get_htf_boundary(cls, dt: datetime, tf_minutes: int) -> tuple[datetime, datetime]:
        """Calculates the HTF bar window (open_time, close_time) containing the given minute.
        TWSE continuous trading starts at 09:00 (first 1m bar 09:00-09:01).
        Standard TWSE multi-minute intervals align on session clock starting at 09:00:
        5m: 09:00-09:05, 09:05-09:10, 09:10-09:15, ...
        15m: 09:00-09:15, 09:15-09:30, 09:30-09:45, ...
        30m: 09:00-09:30, 09:30-10:00, 10:00-10:30, ...
        """
        dt_tpe = parse_phase2_timestamp(dt)
        minute_from_midnight = dt_tpe.hour * 60 + dt_tpe.minute
        session_start_min = 9 * 60  # 09:00

        if minute_from_midnight < session_start_min:
            # Pre-market
            bucket_start_min = (minute_from_midnight // tf_minutes) * tf_minutes
        else:
            offset = minute_from_midnight - session_start_min
            bucket_start_min = session_start_min + (offset // tf_minutes) * tf_minutes

        bucket_end_min = bucket_start_min + tf_minutes

        b_open = dt_tpe.replace(
            hour=bucket_start_min // 60,
            minute=bucket_start_min % 60,
            second=0,
            microsecond=0,
        )
        b_close = dt_tpe.replace(
            hour=bucket_end_min // 60,
            minute=bucket_end_min % 60,
            second=0,
            microsecond=0,
        )
        return b_open, b_close

    def get_closed_htf_bars(
        self,
        as_of: datetime,
        timeframe: str = "5m",
    ) -> list[MarketBar]:
        """Returns ONLY fully closed higher-timeframe bars completed at or before as_of.
        
        If a bar is currently forming (e.g. as_of is 09:37, forming 09:35-09:40),
        that bar is EXCLUDED from returned bars.
        """
        tf_minutes = self.TIMEFRAME_MINUTES.get(timeframe)
        if not tf_minutes:
            raise ValueError(f"Unsupported timeframe: {timeframe}. Must be one of {list(self.TIMEFRAME_MINUTES.keys())}")

        as_of_tpe = parse_phase2_timestamp(as_of)

        # Only consider 1m bars closed at or before as_of
        eligible_1m = [
            b for b in self._bars_1m
            if parse_phase2_timestamp(b.bar_close_time) <= as_of_tpe
        ]

        if not eligible_1m:
            return []

        # Group 1m bars by their containing HTF window
        htf_buckets: dict[tuple[datetime, datetime], list[MarketBar]] = {}
        for b in eligible_1m:
            b_close = parse_phase2_timestamp(b.bar_close_time)
            # The 1m bar belongs to bucket ending at or after b_close
            # e.g. 1m bar 09:00-09:01 belongs to 5m bucket 09:00-09:05
            # We determine bucket by (b_close - 1 microsecond) or bar_open_time
            b_open_1m = parse_phase2_timestamp(b.bar_open_time)
            w_open, w_close = self._get_htf_boundary(b_open_1m, tf_minutes)
            htf_buckets.setdefault((w_open, w_close), []).append(b)

        closed_htf_bars: list[MarketBar] = []
        for (w_open, w_close), bucket_bars in sorted(htf_buckets.items(), key=lambda item: item[0][1]):
            # A higher timeframe bar is ONLY completed/closed if its full close time has elapsed!
            # i.e. w_close <= as_of
            if w_close > as_of_tpe:
                # This bar is incomplete/in-progress! Exclude it.
                continue

            sorted_sub_bars = sorted(bucket_bars, key=lambda b: b.bar_close_time)
            b_open = sorted_sub_bars[0].open
            b_high = max(b.high for b in sorted_sub_bars)
            b_low = min(b.low for b in sorted_sub_bars)
            b_close = sorted_sub_bars[-1].close
            b_vol = sum(b.volume for b in sorted_sub_bars)
            b_amt = sum(getattr(b, "amount", b.close * b.volume) for b in sorted_sub_bars)

            closed_htf_bars.append(
                MarketBar(
                    bar_open_time=w_open,
                    bar_close_time=w_close,
                    open=round(b_open, 4),
                    high=round(b_high, 4),
                    low=round(b_low, 4),
                    close=round(b_close, 4),
                    volume=round(b_vol, 2),
                    amount=round(b_amt, 2),
                )
            )

        return closed_htf_bars

    def get_latest_closed_htf_snapshot(
        self,
        symbol: str,
        as_of: datetime,
        timeframe: str = "5m",
    ) -> Optional[HigherTimeframeSnapshot]:
        """Gets snapshot of the most recent completed HTF bar.
        
        Raises IncompleteBarAccessError if caller explicitly attempts to query an incomplete bar.
        """
        closed_bars = self.get_closed_htf_bars(as_of, timeframe)
        if not closed_bars:
            return None

        last_bar = closed_bars[-1]
        as_of_tpe = parse_phase2_timestamp(as_of)

        # Safety check: ensure last_bar.bar_close_time <= as_of
        if last_bar.bar_close_time > as_of_tpe:
            raise IncompleteBarAccessError(
                f"Causality Violation: Accessing incomplete HTF bar with close_time {last_bar.bar_close_time} > as_of {as_of_tpe}"
            )

        # Cumulative VWAP of HTF bars for today
        day = last_bar.bar_close_time.date()
        day_bars = [b for b in closed_bars if b.bar_close_time.date() == day]
        cum_vol = sum(b.volume for b in day_bars)
        cum_amt = sum(b.amount for b in day_bars)
        htf_vwap = (cum_amt / cum_vol) if cum_vol > 0 else last_bar.close

        ret_pct = (last_bar.close - last_bar.open) / last_bar.open if last_bar.open > 0 else 0.0

        return HigherTimeframeSnapshot(
            as_of=as_of_tpe,
            symbol=symbol,
            timeframe=timeframe,
            last_closed_bar_open_time=last_bar.bar_open_time,
            last_closed_bar_close_time=last_bar.bar_close_time,
            open=last_bar.open,
            high=last_bar.high,
            low=last_bar.low,
            close=last_bar.close,
            volume=last_bar.volume,
            amount=last_bar.amount,
            is_bullish=last_bar.close >= last_bar.open,
            htf_vwap=round(htf_vwap, 4),
            close_above_vwap=last_bar.close >= htf_vwap,
            return_pct=round(ret_pct, 6),
        )

    def filter_signal(
        self,
        symbol: str,
        signal_time: datetime,
        direction: str,
        timeframe: str = "5m",
        htf_condition: str = "HTF_BAR_DIRECTION",
    ) -> bool:
        """Determines KEEP (True) or DROP (False).
        
        Conditions:
        - 'HTF_BAR_DIRECTION': LONG requires last closed HTF bar is bullish; SHORT requires bearish.
        - 'HTF_VWAP': LONG requires last closed HTF bar close >= HTF VWAP; SHORT requires <= HTF VWAP.
        """
        snapshot = self.get_latest_closed_htf_snapshot(symbol, signal_time, timeframe)
        if not snapshot:
            # If no closed HTF bar yet (e.g. before 09:05), keep signal by default
            return True

        dir_upper = direction.upper()
        if htf_condition == "HTF_BAR_DIRECTION":
            if dir_upper == "LONG":
                return snapshot.is_bullish
            elif dir_upper == "SHORT":
                return not snapshot.is_bullish
        elif htf_condition == "HTF_VWAP":
            if dir_upper == "LONG":
                return snapshot.close_above_vwap
            elif dir_upper == "SHORT":
                return not snapshot.close_above_vwap

        return True
