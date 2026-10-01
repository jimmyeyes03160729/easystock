"""Phase 1 Feature Implementations and Research Wrappers for Knowledge V1.

Strictly follows research causality semantics:
1. Candle geometry: If High <= Low, upper_shadow_ratio, lower_shadow_ratio, and
   close_location_value MUST return None. Never substitutes 0.0 or 0.5.
   Reuses strategy_engine.py functions through a defensive partial-reuse wrapper.
2. VWAP: Strictly distinguishes two different calculation scopes:
   - dist_to_bar_vwap_pct: K-bar typical price weighted average ((H+L+C)/3 * V).
   - dist_to_broker_avg_price_pct: Cumulative tick-weighted official trade average.
3. Aggressor Share: Returns None on zero classified volume; never returns 0.0.
"""
from __future__ import annotations
import math
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from .causal_tools import CompletedBar, CausalSwingSegmenter, parse_timestamp

# Defensive reuse of existing implementations without modifying their production behavior
try:
    from strategy_engine import (
        upper_wick_ratio as _production_upper_wick_ratio,
        bar_position as _production_bar_position,
        calculate_vwap as _production_calculate_vwap,
    )
except ImportError:
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from strategy_engine import (
        upper_wick_ratio as _production_upper_wick_ratio,
        bar_position as _production_bar_position,
        calculate_vwap as _production_calculate_vwap,
    )


def safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (TypeError, ValueError, OverflowError):
        return None


class KnowledgeV1Features:
    """Namespace for Phase 1 research features and partial-reuse wrappers."""

    # ---------------------------------------------------------
    # 1. Candle Geometry (Strict Null-Policy Wrappers)
    # ---------------------------------------------------------

    @staticmethod
    def _extract_ohlc(bar: CompletedBar | dict) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        o = safe_float(bar.open if isinstance(bar, CompletedBar) else bar.get("open") or bar.get("Open"))
        c = safe_float(bar.close if isinstance(bar, CompletedBar) else bar.get("close") or bar.get("Close"))
        h = safe_float(bar.high if isinstance(bar, CompletedBar) else bar.get("high") or bar.get("High"))
        l = safe_float(bar.low if isinstance(bar, CompletedBar) else bar.get("low") or bar.get("Low"))
        return o, c, h, l

    @classmethod
    def body_ratio(cls, bar: CompletedBar | dict) -> Optional[float]:
        """abs(close - open) / (high - low). Returns None if high <= low."""
        o, c, h, l = cls._extract_ohlc(bar)
        if o is None or c is None or h is None or l is None or h <= l or min(o, c, h, l) <= 0:
            return None
        return round(abs(c - o) / (h - l), 4)

    @classmethod
    def body_return_pct(cls, bar: CompletedBar | dict) -> Optional[float]:
        """(close - open) / open. Returns None if open <= 0."""
        o, c, _, _ = cls._extract_ohlc(bar)
        if o is None or c is None or o <= 0:
            return None
        return round((c - o) / o, 6)

    @classmethod
    def upper_shadow_ratio(cls, bar: CompletedBar | dict) -> Optional[float]:
        """PARTIAL_REUSE WRAPPER of strategy_engine.upper_wick_ratio.
        Strict Knowledge V1 semantics:
        Returns None if high <= low. Only invokes production logic when high > low.
        """
        o, c, h, l = cls._extract_ohlc(bar)
        if o is None or c is None or h is None or l is None or h <= l or min(o, c, h, l) <= 0:
            return None
        res = _production_upper_wick_ratio({"open": o, "close": c, "high": h, "low": l})
        return round(float(res), 4) if res is not None else None

    @classmethod
    def lower_shadow_ratio(cls, bar: CompletedBar | dict) -> Optional[float]:
        """(min(open, close) - low) / (high - low). Returns None if high <= low."""
        o, c, h, l = cls._extract_ohlc(bar)
        if o is None or c is None or h is None or l is None or h <= l or min(o, c, h, l) <= 0:
            return None
        return round((min(o, c) - l) / (h - l), 4)

    @classmethod
    def close_location_value(cls, bar: CompletedBar | dict) -> Optional[float]:
        """PARTIAL_REUSE WRAPPER of strategy_engine.bar_position.
        Strict Knowledge V1 semantics:
        Returns None if high <= low. Linearly maps valid bar_position in [0, 1] to [-1, 1].
        """
        o, c, h, l = cls._extract_ohlc(bar)
        if o is None or c is None or h is None or l is None or h <= l or min(o, c, h, l) <= 0:
            return None
        pos = _production_bar_position({"open": o, "close": c, "high": h, "low": l})
        if pos is None:
            return None
        clv = 2.0 * float(pos) - 1.0
        return round(max(-1.0, min(1.0, clv)), 4)

    @staticmethod
    def gap_open_pct(session_open: float, prev_session_close: float) -> Optional[float]:
        """(session_open - prev_session_close) / prev_session_close."""
        so = safe_float(session_open)
        pc = safe_float(prev_session_close)
        if so is None or pc is None or min(so, pc) <= 0:
            return None
        return round((so - pc) / pc, 6)

    # ---------------------------------------------------------
    # 2. Volume & Relative Activity
    # ---------------------------------------------------------

    @staticmethod
    def relative_volume_open(
        elapsed_open_volume: float,
        prior_sessions_same_elapsed_volume: Sequence[float]
    ) -> Optional[float]:
        """elapsed_open_volume / mean(same_elapsed_open_volume_previous_sessions)."""
        ev = safe_float(elapsed_open_volume)
        valid_priors = [safe_float(v) for v in prior_sessions_same_elapsed_volume if safe_float(v) is not None and v > 0]
        if ev is None or ev < 0 or not valid_priors:
            return None
        mean_prior = sum(valid_priors) / len(valid_priors)
        if mean_prior <= 0:
            return None
        return round(ev / mean_prior, 4)

    @staticmethod
    def volume_ratio_5m(completed_1m_bars: Sequence[CompletedBar]) -> Optional[float]:
        """Current 1m volume / mean(previous 5 completed 1m volumes)."""
        if len(completed_1m_bars) < 6:
            return None
        current_vol = completed_1m_bars[-1].volume
        prior_5 = completed_1m_bars[-6:-1]
        prior_mean = sum(b.volume for b in prior_5) / 5.0
        if prior_mean <= 0:
            return None
        return round(current_vol / prior_mean, 4)

    @staticmethod
    def volume_acceleration(recent_volumes: Sequence[float]) -> Optional[float]:
        """2nd-order discrete acceleration: (V_t - 2*V_{t-1} + V_{t-2})."""
        if len(recent_volumes) < 3:
            return None
        v0 = safe_float(recent_volumes[-1])
        v1 = safe_float(recent_volumes[-2])
        v2 = safe_float(recent_volumes[-3])
        if v0 is None or v1 is None or v2 is None:
            return None
        return round(v0 - 2.0 * v1 + v2, 4)

    @staticmethod
    def pullback_vol_decay_ratio(bars: Sequence[CompletedBar]) -> Optional[float]:
        """Causal swing segmentation pullback volume decay."""
        return CausalSwingSegmenter.volume_decay_ratio(bars)

    # ---------------------------------------------------------
    # 3. Price Distance & Dual-Scope VWAP
    # ---------------------------------------------------------

    @staticmethod
    def dist_to_prev_high_pct(current_price: float, prior_highs: Sequence[float]) -> Optional[float]:
        """(max(prior_highs) - current_price) / current_price."""
        cp = safe_float(current_price)
        valid = [safe_float(h) for h in prior_highs if safe_float(h) is not None and h > 0]
        if cp is None or cp <= 0 or not valid:
            return None
        return round((max(valid) - cp) / cp, 6)

    @staticmethod
    def dist_to_prev_low_pct(current_price: float, prior_lows: Sequence[float]) -> Optional[float]:
        """(current_price - min(prior_lows)) / current_price."""
        cp = safe_float(current_price)
        valid = [safe_float(l) for l in prior_lows if safe_float(l) is not None and l > 0]
        if cp is None or cp <= 0 or not valid:
            return None
        return round((cp - min(valid)) / cp, 6)

    @staticmethod
    def dist_to_vwap_pct(current_price: float, vwap: float) -> Optional[float]:
        """Generic (current_price - vwap) / vwap calculator."""
        cp = safe_float(current_price)
        vw = safe_float(vwap)
        if cp is None or vw is None or min(cp, vw) <= 0:
            return None
        return round((cp - vw) / vw, 6)

    @staticmethod
    def dist_to_bar_vwap_pct(current_price: float, bars: Sequence[CompletedBar | dict]) -> Optional[float]:
        """Scope A: Distance to Typical Price K-bar VWAP (strategy_engine.calculate_vwap)."""
        rows = [
            {
                "high": b.high if isinstance(b, CompletedBar) else b["high"],
                "low": b.low if isinstance(b, CompletedBar) else b["low"],
                "close": b.close if isinstance(b, CompletedBar) else b["close"],
                "volume": b.volume if isinstance(b, CompletedBar) else b.get("volume", 0),
            }
            for b in bars
        ]
        vwap = _production_calculate_vwap(rows)
        return KnowledgeV1Features.dist_to_vwap_pct(current_price, vwap)

    @staticmethod
    def dist_to_broker_avg_price_pct(current_price: float, broker_average_price: float) -> Optional[float]:
        """Scope B: Distance to exchange official trade average price (intraday_live.price_vs_avg_pct)."""
        return KnowledgeV1Features.dist_to_vwap_pct(current_price, broker_average_price)

    @staticmethod
    def calculate_vwap_from_bars(bars: Sequence[CompletedBar | dict]) -> Optional[float]:
        """Computes K-bar VWAP using strategy_engine.calculate_vwap."""
        rows = [
            {
                "high": b.high if isinstance(b, CompletedBar) else b["high"],
                "low": b.low if isinstance(b, CompletedBar) else b["low"],
                "close": b.close if isinstance(b, CompletedBar) else b["close"],
                "volume": b.volume if isinstance(b, CompletedBar) else b.get("volume", 0),
            }
            for b in bars
        ]
        return _production_calculate_vwap(rows)

    @classmethod
    def calculate_bar_typical_vwap(cls, bars: Sequence[CompletedBar | dict]) -> Optional[float]:
        """Alias for calculate_vwap_from_bars (Scope A: BAR_TYPICAL_PRICE_VWAP)."""
        return cls.calculate_vwap_from_bars(bars)

    # ---------------------------------------------------------
    # 4. Intraday Returns
    # ---------------------------------------------------------

    @staticmethod
    def intraday_return_nm(
        current_price: float,
        historical_price_at_n_minutes_ago: float
    ) -> Optional[float]:
        """Trailing N-minute backward return: (current_price - prior_price) / prior_price."""
        cp = safe_float(current_price)
        pp = safe_float(historical_price_at_n_minutes_ago)
        if cp is None or pp is None or min(cp, pp) <= 0:
            return None
        return round((cp - pp) / pp, 6)

    # ---------------------------------------------------------
    # 5. VWAP Interactions
    # ---------------------------------------------------------

    @staticmethod
    def vwap_touch_count(
        bars: Sequence[CompletedBar],
        vwap_series: Sequence[float],
        band_fraction: float = 0.003
    ) -> int:
        if len(bars) != len(vwap_series) or not bars:
            return 0
        touches = 0
        for b, v in zip(bars, vwap_series):
            if v and v > 0:
                band_lo = v * (1.0 - band_fraction)
                band_hi = v * (1.0 + band_fraction)
                if not (b.high < band_lo or b.low > band_hi):
                    touches += 1
        return touches

    @staticmethod
    def vwap_cross_count(
        bars: Sequence[CompletedBar],
        vwap_series: Sequence[float]
    ) -> int:
        if len(bars) != len(vwap_series) or len(bars) < 2:
            return 0
        crosses = 0
        for i in range(1, len(bars)):
            prev_c, prev_v = bars[i - 1].close, vwap_series[i - 1]
            curr_c, curr_v = bars[i].close, vwap_series[i]
            if prev_v and curr_v and prev_v > 0 and curr_v > 0:
                if (prev_c < prev_v and curr_c > curr_v) or (prev_c > prev_v and curr_c < curr_v):
                    crosses += 1
        return crosses

    # ---------------------------------------------------------
    # 6. Aggressor Flow (Strict Null Handling Wrapper)
    # ---------------------------------------------------------

    @staticmethod
    def aggressor_buy_share(buy_volume: float, sell_volume: float) -> Optional[float]:
        """PARTIAL_REUSE WRAPPER of intraday_live.buy_ratio_60s logic.
        Strict Knowledge V1 semantics:
        Returns None when classified volume <= 0 (never returns 0.0 to prevent misleading false sell).
        """
        bv = safe_float(buy_volume) or 0.0
        sv = safe_float(sell_volume) or 0.0
        tot = bv + sv
        if tot <= 0:
            return None
        return round(bv / tot, 4)

    @staticmethod
    def aggressor_sell_share(buy_volume: float, sell_volume: float) -> Optional[float]:
        bs = KnowledgeV1Features.aggressor_buy_share(buy_volume, sell_volume)
        if bs is None:
            return None
        return round(1.0 - bs, 4)

    @staticmethod
    def aggressor_volume_delta(buy_volume: float, sell_volume: float) -> Optional[float]:
        bv = safe_float(buy_volume) or 0.0
        sv = safe_float(sell_volume) or 0.0
        if bv + sv <= 0:
            return None
        return round(bv - sv, 2)
