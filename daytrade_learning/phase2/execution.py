"""Phase 2A Causal Execution Clock & Bar Time Semantics.

Major Fixes Enforced:
1. Strict Bar Time Semantics:
   - MarketBar explicitly separates bar_open_time and bar_close_time.
   - Ambiguous MarketBar.timestamp is forbidden.
   - Bar execution requires bar_open_time >= earliest_legal_execution_time to execute at bar.open.
   - Using bar_close_time to judge legality while filling at bar.open is strictly rejected.
   - Tick execution is separated into TickExecutionPoint.
2. Full Causal Order:
   - Strictly enforces: feature_time <= signal_time <= decision_available_time < execution_time.
   - Rejects feature_after_signal, signal_after_decision, execution_equal_decision, execution_before_decision.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Sequence

TPE = timezone(timedelta(hours=8))


class CausalityViolationError(ValueError):
    """Raised when strict chronological causality is violated."""
    pass


class ExecutionOrderError(ValueError):
    """Raised when execution sequencing or bar timing is invalid."""
    pass


def parse_phase2_timestamp(value: Any) -> datetime:
    """Normalize timestamp to Asia/Taipei timezone."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=TPE) if value.tzinfo is None else value.astimezone(TPE)
    if isinstance(value, (int, float)):
        val = float(value)
        divisor = 1e9 if abs(val) >= 1e17 else 1e6 if abs(val) >= 1e14 else 1e3 if abs(val) >= 1e11 else 1.0
        return datetime.fromtimestamp(val / divisor, timezone.utc).astimezone(TPE)
    if isinstance(value, str):
        val = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(val)
        return dt.replace(tzinfo=TPE) if dt.tzinfo is None else dt.astimezone(TPE)
    raise TypeError(f"Unsupported timestamp format: {type(value)}")


@dataclass(frozen=True)
class MarketBar:
    """Unambiguous OHLCV Bar with explicit open and close timestamps."""
    bar_open_time: datetime
    bar_close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0

    def __post_init__(self):
        if self.bar_open_time >= self.bar_close_time:
            raise ExecutionOrderError(
                f"bar_open_time ({self.bar_open_time}) must be strictly before bar_close_time ({self.bar_close_time})"
            )
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if min(self.open, self.high, self.low, self.close) < 0:
            raise ValueError("Bar prices must be non-negative")


@dataclass(frozen=True)
class TickExecutionPoint:
    """Distinct tick-level execution point, never conflated with OHLC bar."""
    tick_time: datetime
    price: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None

    def __post_init__(self):
        if self.price <= 0:
            raise ValueError(f"Tick price must be positive: {self.price}")
        if self.volume < 0:
            raise ValueError(f"Tick volume cannot be negative: {self.volume}")


def validate_causal_order(
    feature_time: datetime,
    signal_time: datetime,
    decision_available_time: datetime,
    execution_time: datetime,
) -> None:
    """Strictly validates chronological ordering:
    feature_time <= signal_time <= decision_available_time < execution_time
    """
    ft = parse_phase2_timestamp(feature_time)
    st = parse_phase2_timestamp(signal_time)
    dt = parse_phase2_timestamp(decision_available_time)
    et = parse_phase2_timestamp(execution_time)

    if ft > st:
        raise CausalityViolationError(
            f"feature_after_signal_rejected: feature_time ({ft}) > signal_time ({st})"
        )
    if st > dt:
        raise CausalityViolationError(
            f"signal_after_decision_rejected: signal_time ({st}) > decision_available_time ({dt})"
        )
    if et == dt:
        raise CausalityViolationError(
            f"execution_equal_decision_rejected: execution_time ({et}) cannot equal decision_available_time ({dt})"
        )
    if et < dt:
        raise CausalityViolationError(
            f"execution_before_decision_rejected: execution_time ({et}) cannot precede decision_available_time ({dt})"
        )


class CausalExecutionClock:
    """Calculates legal execution boundaries and finds strictly legal fills."""

    def __init__(self, safety_buffer_seconds: int = 2):
        if safety_buffer_seconds < 0:
            raise ValueError("safety_buffer_seconds cannot be negative")
        self.safety_buffer_seconds = safety_buffer_seconds

    def compute_causal_times(self, signal_time: datetime) -> tuple[datetime, datetime]:
        """Given a signal_time, computes:
        1. decision_available_time = signal_time + safety_buffer_seconds
        2. earliest_legal_execution_time = start of the next full minute bar strictly after decision_available_time
        
        Examples:
        - 09:30:00 + 2s -> 09:30:02 -> next minute start is 09:31:00
        - 09:30:59 + 2s -> 09:31:01 -> next minute start is 09:32:00 (crossed minute boundary)
        """
        st = parse_phase2_timestamp(signal_time)
        decision_time = st + timedelta(seconds=self.safety_buffer_seconds)
        # Next full minute start strictly after decision_time
        earliest_exec = decision_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return decision_time, earliest_exec

    def find_next_legal_bar(
        self,
        bars: Sequence[MarketBar],
        earliest_legal_execution_time: datetime,
    ) -> Optional[MarketBar]:
        """Finds the first bar whose bar_open_time >= earliest_legal_execution_time.
        
        Strictly forbids filling at bar.open if bar_open_time < earliest_legal_execution_time,
        even if bar_close_time >= earliest_legal_execution_time.
        """
        earliest = parse_phase2_timestamp(earliest_legal_execution_time)
        # Sort chronologically by bar_open_time
        sorted_bars = sorted(bars, key=lambda b: b.bar_open_time)
        for b in sorted_bars:
            if b.bar_open_time >= earliest:
                return b
        return None

    def execute_market_entry(
        self,
        signal_time: datetime,
        bars: Sequence[MarketBar],
        direction: str = "LONG",
        slippage_bps: float = 0.0,
        feature_time: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Simulates market entry on the next legal bar open.
        
        Returns a dict containing all timing, fill prices, and status.
        If no legal bar exists, status is 'NO_CAUSAL_EXECUTION' with prices set to None.
        """
        st = parse_phase2_timestamp(signal_time)
        ft = parse_phase2_timestamp(feature_time) if feature_time is not None else st
        dt, earliest_et = self.compute_causal_times(st)

        legal_bar = self.find_next_legal_bar(bars, earliest_et)
        if legal_bar is None:
            return {
                "status": "NO_CAUSAL_EXECUTION",
                "feature_time": ft.isoformat(),
                "signal_time": st.isoformat(),
                "decision_available_time": dt.isoformat(),
                "execution_time": None,
                "theoretical_entry_price": None,
                "actual_entry_price": None,
                "bar": None,
            }

        actual_et = legal_bar.bar_open_time
        validate_causal_order(
            feature_time=ft,
            signal_time=st,
            decision_available_time=dt,
            execution_time=actual_et,
        )

        theoretical_price = legal_bar.open
        dir_upper = direction.upper()
        if dir_upper == "LONG":
            actual_price = theoretical_price * (1.0 + slippage_bps / 10000.0)
        elif dir_upper == "SHORT":
            actual_price = theoretical_price * (1.0 - slippage_bps / 10000.0)
        else:
            raise ValueError(f"Unsupported direction: {direction}")

        return {
            "status": "FILLED",
            "feature_time": ft.isoformat(),
            "signal_time": st.isoformat(),
            "decision_available_time": dt.isoformat(),
            "execution_time": actual_et.isoformat(),
            "theoretical_entry_price": round(theoretical_price, 4),
            "actual_entry_price": round(actual_price, 4),
            "bar": legal_bar,
        }
