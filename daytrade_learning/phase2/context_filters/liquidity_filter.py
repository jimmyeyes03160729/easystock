"""Liquidity & Candidate Pool Filter (F05).

Strict Rules:
- Uses only past closed bars up to signal_time.
- Computes rolling volume and rolling traded value (sum of close * volume).
- FORBIDDEN:
  - End-of-day total volume
  - Post-market rank
  - Future minutes volume leakage
- Universally records:
  survivorship_bias = True
  point_in_time_universe = False
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Optional

from ..execution import MarketBar, parse_phase2_timestamp

TPE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class LiquiditySnapshot:
    as_of: datetime
    symbol: str
    lookback_minutes: int
    rolling_volume: float
    rolling_traded_value: float  # TWD (estimated via sum of close * volume)
    cumulative_session_volume: float
    cumulative_session_value: float
    survivorship_bias: bool = True
    point_in_time_universe: bool = False


class LiquidityFilter:
    """Evaluates intraday causal liquidity indicators prior to signal."""

    def __init__(self, stock_bars_by_symbol: dict[str, Sequence[MarketBar]]):
        self._stock_bars: dict[str, list[MarketBar]] = {
            s: sorted(bars, key=lambda b: b.bar_close_time)
            for s, bars in stock_bars_by_symbol.items()
        }

    def _get_past_bars(self, symbol: str, as_of: datetime) -> list[MarketBar]:
        bars = self._stock_bars.get(symbol, [])
        as_of_tpe = parse_phase2_timestamp(as_of)
        return [b for b in bars if parse_phase2_timestamp(b.bar_close_time) <= as_of_tpe]

    def compute_liquidity_snapshot(
        self,
        symbol: str,
        as_of: datetime,
        lookback_minutes: int = 30,
    ) -> LiquiditySnapshot:
        as_of_tpe = parse_phase2_timestamp(as_of)
        past_bars = self._get_past_bars(symbol, as_of_tpe)

        if not past_bars:
            return LiquiditySnapshot(
                as_of=as_of_tpe,
                symbol=symbol,
                lookback_minutes=lookback_minutes,
                rolling_volume=0.0,
                rolling_traded_value=0.0,
                cumulative_session_volume=0.0,
                cumulative_session_value=0.0,
            )

        as_of_date = as_of_tpe.date()
        session_bars = [
            b for b in past_bars
            if parse_phase2_timestamp(b.bar_close_time).date() == as_of_date
        ]

        if not session_bars:
            session_bars = past_bars[-lookback_minutes:]

        # Cumulative session volume & value up to as_of
        cum_vol = sum(b.volume for b in session_bars)
        cum_val = sum(
            (b.close * b.volume if getattr(b, "amount", 0.0) == 0.0 else b.amount)
            for b in session_bars
        )

        # Rolling window volume & value
        w_bars = session_bars[-lookback_minutes:]
        roll_vol = sum(b.volume for b in w_bars)
        roll_val = sum(
            (b.close * b.volume if getattr(b, "amount", 0.0) == 0.0 else b.amount)
            for b in w_bars
        )

        return LiquiditySnapshot(
            as_of=as_of_tpe,
            symbol=symbol,
            lookback_minutes=lookback_minutes,
            rolling_volume=round(roll_vol, 2),
            rolling_traded_value=round(roll_val, 2),
            cumulative_session_volume=round(cum_vol, 2),
            cumulative_session_value=round(cum_val, 2),
        )

    def filter_signal(
        self,
        symbol: str,
        signal_time: datetime,
        min_rolling_traded_value_twd: float = 10_000_000.0,
        lookback_minutes: int = 30,
    ) -> bool:
        """Determines KEEP (True) if rolling traded value exceeds threshold."""
        snapshot = self.compute_liquidity_snapshot(symbol, signal_time, lookback_minutes)
        return snapshot.rolling_traded_value >= min_rolling_traded_value_twd
