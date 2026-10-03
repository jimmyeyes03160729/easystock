"""Research Market Regime Filter (F01).

Strict Research Governance & Integrity Rules:
- RESEARCH_ONLY = True, INERT_BY_DEFAULT = True.
- RESEARCH_PROXY = True, OFFICIAL_INDEX = False.
- NEVER implies TAIEX, OTC Index, or official TWSE market regime.
- NEVER imports or couples with production MarketGate.
- Strictly causal: only processes closed market bars up to signal_time.
- Implements LEAVE_ONE_OUT_PROXY:
  When evaluating regime for target symbol S, S is strictly EXCLUDED from proxy calculations.
- Implements MISSING_CONSTITUENT_POLICY:
  EXCLUDE_FROM_CURRENT_CROSS_SECTION. If a constituent has no bar at timestamp t,
  it is excluded from that cross-section without forward-filling.
- Clearly distinguishes:
  UNIVERSE_PROXY_RETURN, UNIVERSE_PROXY_TREND, UNIVERSE_PROXY_INTRADAY_RETURN.
  Removes ambiguous 'MARKET_VWAP' terminology.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Optional

from ..execution import MarketBar, parse_phase2_timestamp, CausalityViolationError

TPE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    as_of: datetime
    data_source: str
    is_proxy: bool
    is_official_index: bool
    target_excluded: bool
    excluded_symbol: Optional[str]
    proxy_universe_size: int
    constituent_count_at_t: int
    proxy_intraday_return: float
    proxy_trend_slope_15m: float
    proxy_volatility_30m: float
    opening_direction: str  # 'UP', 'DOWN', 'FLAT'
    survivorship_bias: bool = True
    point_in_time_universe: bool = False


class ResearchMarketRegime:
    """Independent research-only market regime evaluator implementing leave-one-out proxy."""

    def __init__(
        self,
        market_bars: Optional[Sequence[MarketBar]] = None,
        universe_bars_by_symbol: Optional[dict[str, Sequence[MarketBar]]] = None,
    ):
        if market_bars:
            self._external_bars = sorted(market_bars, key=lambda b: b.bar_close_time)
            self._universe_bars: dict[str, list[MarketBar]] = {}
            self._data_source = "EXTERNAL_MARKET_SERIES"
            self._is_proxy = False
            self._is_official = True
        elif universe_bars_by_symbol:
            self._external_bars = []
            self._universe_bars = {
                s: sorted(bars, key=lambda b: b.bar_close_time)
                for s, bars in universe_bars_by_symbol.items()
            }
            self._data_source = "UNIVERSE_EQUAL_WEIGHTED_MARKET_PROXY"
            self._is_proxy = True
            self._is_official = False
        else:
            self._external_bars = []
            self._universe_bars = {}
            self._data_source = "DATA_UNAVAILABLE"
            self._is_proxy = False
            self._is_official = False

        # Index universe bars by (bar_close_time, symbol) for fast point-in-time lookup
        self._bars_by_time: dict[datetime, dict[str, MarketBar]] = {}
        for sym, bar_list in self._universe_bars.items():
            for b in bar_list:
                t_close = parse_phase2_timestamp(b.bar_close_time)
                self._bars_by_time.setdefault(t_close, {})[sym] = b

        self._sorted_times = sorted(self._bars_by_time.keys())
        self._cached_proxy_series: dict[Optional[str], list[MarketBar]] = {}

    @property
    def data_source(self) -> str:
        return self._data_source

    @property
    def is_proxy(self) -> bool:
        return self._is_proxy

    @property
    def is_official_index(self) -> bool:
        return self._is_official

    def _get_or_build_proxy_series(self, exclude_symbol: Optional[str]) -> list[MarketBar]:
        if exclude_symbol not in self._cached_proxy_series:
            proxy_bars: list[MarketBar] = []
            cum_idx = 1000.0

            for t_close in self._sorted_times:
                sym_map = self._bars_by_time[t_close]
                active_peers = [
                    b for s, b in sym_map.items()
                    if (exclude_symbol is None or s != exclude_symbol) and b.open > 0
                ]

                if not active_peers:
                    continue

                returns = [(b.close - b.open) / b.open for b in active_peers]
                avg_ret = sum(returns) / len(returns)
                b_open = cum_idx
                b_close = cum_idx * (1.0 + avg_ret)
                b_high = max(b_open, b_close)
                b_low = min(b_open, b_close)
                cum_idx = b_close

                total_vol = sum(b.volume for b in active_peers)
                total_amt = sum(getattr(b, "amount", b.close * b.volume) for b in active_peers)

                t_open = active_peers[0].bar_open_time
                proxy_bars.append(
                    MarketBar(
                        bar_open_time=t_open,
                        bar_close_time=t_close,
                        open=round(b_open, 4),
                        high=round(b_high, 4),
                        low=round(b_low, 4),
                        close=round(b_close, 4),
                        volume=round(total_vol, 2),
                        amount=round(total_amt, 2),
                    )
                )
            self._cached_proxy_series[exclude_symbol] = proxy_bars
        return self._cached_proxy_series[exclude_symbol]

    def get_past_bars(self, as_of: datetime, exclude_symbol: Optional[str] = None) -> list[MarketBar]:
        """Constructs or returns past bars strictly up to as_of, applying leave-one-out."""
        as_of_tpe = parse_phase2_timestamp(as_of)

        if not self._is_proxy:
            return [b for b in self._external_bars if parse_phase2_timestamp(b.bar_close_time) <= as_of_tpe]

        full_series = self._get_or_build_proxy_series(exclude_symbol)
        return [b for b in full_series if parse_phase2_timestamp(b.bar_close_time) <= as_of_tpe]

    def evaluate_regime_for_symbol(
        self,
        as_of: datetime,
        target_symbol: Optional[str] = None,
    ) -> MarketRegimeSnapshot:
        """Evaluates causal market regime indicators as of the specified time, strictly excluding target_symbol."""
        as_of_tpe = parse_phase2_timestamp(as_of)
        past_bars = self.get_past_bars(as_of_tpe, exclude_symbol=target_symbol)

        universe_size = len(self._universe_bars) if self._universe_bars else (1 if self._external_bars else 0)

        # Count constituents active at timestamp as_of
        last_minute_peers = self._bars_by_time.get(as_of_tpe, {})
        if target_symbol and target_symbol in last_minute_peers:
            active_count_at_t = len(last_minute_peers) - 1
        else:
            active_count_at_t = len(last_minute_peers)

        if not past_bars:
            return MarketRegimeSnapshot(
                as_of=as_of_tpe,
                data_source=self._data_source,
                is_proxy=self._is_proxy,
                is_official_index=self._is_official,
                target_excluded=target_symbol is not None,
                excluded_symbol=target_symbol,
                proxy_universe_size=universe_size,
                constituent_count_at_t=active_count_at_t,
                proxy_intraday_return=0.0,
                proxy_trend_slope_15m=0.0,
                proxy_volatility_30m=0.0,
                opening_direction="FLAT",
            )

        as_of_date = as_of_tpe.date()
        session_bars = [
            b for b in past_bars
            if parse_phase2_timestamp(b.bar_close_time).date() == as_of_date
        ]

        if not session_bars:
            session_bars = past_bars[-30:]

        current_close = session_bars[-1].close
        session_open = session_bars[0].open

        # Intraday cumulative proxy return
        intraday_ret = (current_close - session_open) / session_open if session_open > 0 else 0.0

        # 15m trend slope
        if len(session_bars) >= 15:
            ref_bar_15m = session_bars[-15]
            slope_15m = (current_close - ref_bar_15m.close) / ref_bar_15m.close if ref_bar_15m.close > 0 else 0.0
        elif len(session_bars) > 1:
            slope_15m = (current_close - session_bars[0].close) / session_bars[0].close
        else:
            slope_15m = 0.0

        # 30m volatility
        sample_bars = session_bars[-30:] if len(session_bars) >= 30 else session_bars
        if len(sample_bars) >= 2:
            rets = [
                (sample_bars[i].close - sample_bars[i - 1].close) / sample_bars[i - 1].close
                for i in range(1, len(sample_bars))
                if sample_bars[i - 1].close > 0
            ]
            if rets:
                mean_r = sum(rets) / len(rets)
                variance = sum((r - mean_r) ** 2 for r in rets) / len(rets)
                vol_30m = math.sqrt(variance)
            else:
                vol_30m = 0.0
        else:
            vol_30m = 0.0

        # Opening direction
        if intraday_ret > 0.0005:
            op_dir = "UP"
        elif intraday_ret < -0.0005:
            op_dir = "DOWN"
        else:
            op_dir = "FLAT"

        return MarketRegimeSnapshot(
            as_of=as_of_tpe,
            data_source=self._data_source,
            is_proxy=self._is_proxy,
            is_official_index=self._is_official,
            target_excluded=target_symbol is not None,
            excluded_symbol=target_symbol,
            proxy_universe_size=universe_size,
            constituent_count_at_t=active_count_at_t,
            proxy_intraday_return=round(intraday_ret, 6),
            proxy_trend_slope_15m=round(slope_15m, 6),
            proxy_volatility_30m=round(vol_30m, 6),
            opening_direction=op_dir,
        )

    def evaluate_regime(self, as_of: datetime) -> MarketRegimeSnapshot:
        """Standard evaluation without target exclusion (for general universe diagnostics)."""
        return self.evaluate_regime_for_symbol(as_of=as_of, target_symbol=None)

    def filter_signal(
        self,
        symbol: str,
        signal_time: datetime,
        direction: str,
        regime_condition: str = "INTRADAY_DIRECTION",
    ) -> bool:
        """Determines KEEP (True) or DROP (False) using leave-one-out proxy for the given symbol.
        
        regime_condition options:
        - 'INTRADAY_DIRECTION': LONG requires positive proxy intraday return, SHORT requires negative.
        - 'TREND_ALIGNMENT': LONG requires positive proxy 15m trend slope, SHORT requires negative.
        """
        snapshot = self.evaluate_regime_for_symbol(as_of=signal_time, target_symbol=symbol)
        dir_upper = direction.upper()

        if regime_condition == "INTRADAY_DIRECTION":
            if dir_upper == "LONG":
                return snapshot.proxy_intraday_return >= 0.0
            elif dir_upper == "SHORT":
                return snapshot.proxy_intraday_return <= 0.0
        elif regime_condition == "TREND_ALIGNMENT":
            if dir_upper == "LONG":
                return snapshot.proxy_trend_slope_15m >= 0.0
            elif dir_upper == "SHORT":
                return snapshot.proxy_trend_slope_15m <= 0.0

        return True
