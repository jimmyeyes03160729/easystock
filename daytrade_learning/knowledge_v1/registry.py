"""Research-only Feature Registry for Daytrade Knowledge V1.

Strictly categorizes candidate features into:
- PARTIAL_REUSE: Reused from existing repo implementation via a defensive research wrapper
  (e.g., enforcing None on High <= Low or separating VWAP scopes).
- NEW_RESEARCH: Newly implemented causal research features supported by available OHLCV/Tick data.
- UNSUPPORTED: Blocked due to market/API limitations (e.g., L2 5-depth, order cancellation).
- FUTURE_DATA_REQUIRED: Blocked pending crawler or matrix pipeline extensions.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Optional


class RegistryStatus(str, Enum):
    PARTIAL_REUSE = "PARTIAL_REUSE"
    NEW_RESEARCH = "NEW_RESEARCH"
    UNSUPPORTED = "UNSUPPORTED"
    FUTURE_DATA_REQUIRED = "FUTURE_DATA_REQUIRED"


@dataclass(frozen=True)
class FeatureMetadata:
    feature_id: str
    knowledge_id: str
    source_status: str
    implementation_status: RegistryStatus
    data_source: str
    calculation_function: Optional[str]
    causal_safe: bool
    lookahead_risk: str
    missing_data_policy: str
    reused_symbol: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["implementation_status"] = self.implementation_status.value
        return data


class FeatureRegistry:
    def __init__(self):
        self._registry: dict[str, FeatureMetadata] = {}
        self._init_defaults()

    def register(self, meta: FeatureMetadata) -> None:
        self._registry[meta.feature_id] = meta

    def get(self, feature_id: str) -> Optional[FeatureMetadata]:
        return self._registry.get(feature_id)

    def list_all(self) -> list[FeatureMetadata]:
        return list(self._registry.values())

    def list_by_status(self, status: RegistryStatus) -> list[FeatureMetadata]:
        return [m for m in self._registry.values() if m.implementation_status == status]

    def _init_defaults(self):
        # 1. Partial Reuse Features (Wrapped with research null-safety & scope separation)
        self.register(FeatureMetadata(
            feature_id="F_upper_shadow_ratio",
            knowledge_id="F_upper_shadow_ratio",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.PARTIAL_REUSE,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.upper_shadow_ratio",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None when high <= low (defensive wrapper over strategy_engine.upper_wick_ratio)",
            reused_symbol="strategy_engine.py:upper_wick_ratio",
            description="Upper shadow ratio: (high - max(open, close)) / (high - low)"
        ))

        self.register(FeatureMetadata(
            feature_id="F_close_location_value",
            knowledge_id="F_close_location_value",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.PARTIAL_REUSE,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.close_location_value",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None when high <= low; maps valid bar_position in [0, 1] to [-1, 1]",
            reused_symbol="strategy_engine.py:bar_position",
            description="Close Location Value in [-1, 1], linearly mapped from bar_position"
        ))

        self.register(FeatureMetadata(
            feature_id="F_dist_to_bar_vwap_pct",
            knowledge_id="F_dist_to_vwap_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.PARTIAL_REUSE,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.dist_to_bar_vwap_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if bar vwap <= 0 or volume <= 0",
            reused_symbol="strategy_engine.py:calculate_vwap",
            description="Scope A: Distance to Typical Price K-bar VWAP: ((H+L+C)/3 * V) / sum(V)"
        ))

        self.register(FeatureMetadata(
            feature_id="F_dist_to_broker_avg_price_pct",
            knowledge_id="F_dist_to_vwap_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.PARTIAL_REUSE,
            data_source="live_market_snapshot",
            calculation_function="KnowledgeV1Features.dist_to_broker_avg_price_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if broker average_price is missing or nonpositive",
            reused_symbol="intraday_live.py:price_vs_avg_pct",
            description="Scope B: Distance to exchange official cumulative trade average price"
        ))

        self.register(FeatureMetadata(
            feature_id="F_aggressor_buy_share",
            knowledge_id="F_aggressor_buy_share",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.PARTIAL_REUSE,
            data_source="trades_tick_stream",
            calculation_function="KnowledgeV1Features.aggressor_buy_share",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if classified_volume <= 0 (defensive wrapper over intraday_live.buy_ratio_60s)",
            reused_symbol="intraday_live.py:buy_ratio_60s",
            description="Share of buy-initiated volume over total classified volume in trailing 60s"
        ))

        # 2. New Research Features
        self.register(FeatureMetadata(
            feature_id="F_trade_aggressiveness_ratio",
            knowledge_id="F_trade_aggressiveness_ratio",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="trades_tick_stream",
            calculation_function="KnowledgeV1Features.aggressor_volume_delta / total_classified",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if classified_volume <= 0",
            description="Signed aggressor trade delta in [-1, 1]: (buy - sell) / (buy + sell)"
        ))

        self.register(FeatureMetadata(
            feature_id="F_body_ratio",
            knowledge_id="F_body_ratio",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.body_ratio",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None when high <= low or prices nonpositive; no zero-fill",
            description="Candle body ratio: abs(close - open) / (high - low)"
        ))

        self.register(FeatureMetadata(
            feature_id="F_body_return_pct",
            knowledge_id="F_body_return_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.body_return_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None when open <= 0",
            description="Signed candle return: (close - open) / open"
        ))

        self.register(FeatureMetadata(
            feature_id="F_lower_shadow_ratio",
            knowledge_id="F_lower_shadow_ratio",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_bars",
            calculation_function="KnowledgeV1Features.lower_shadow_ratio",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None when high <= low",
            description="Lower shadow ratio: (min(open, close) - low) / (high - low)"
        ))

        self.register(FeatureMetadata(
            feature_id="F_gap_open_pct",
            knowledge_id="F_gap_open_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="daily_prior_close_and_open_tick",
            calculation_function="KnowledgeV1Features.gap_open_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if prev_close <= 0 or session_open <= 0",
            description="Session gap open: (session_open - prev_close) / prev_close"
        ))

        self.register(FeatureMetadata(
            feature_id="F_relative_volume_open",
            knowledge_id="F_relative_volume_open",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="intraday_cumulative_bars_and_history",
            calculation_function="KnowledgeV1Features.relative_volume_open",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if baseline <= 0 or insufficient history",
            description="Ratio of elapsed open volume to mean elapsed open volume over prior sessions"
        ))

        self.register(FeatureMetadata(
            feature_id="F_volume_ratio_5m",
            knowledge_id="F_volume_ratio_5m",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_1m_bars",
            calculation_function="KnowledgeV1Features.volume_ratio_5m",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if prior 5-minute volume average is zero",
            description="Current 1m volume divided by trailing 5 completed 1m volume mean"
        ))

        self.register(FeatureMetadata(
            feature_id="F_volume_acceleration",
            knowledge_id="F_volume_acceleration",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="equal_interval_volume_buckets",
            calculation_function="KnowledgeV1Features.volume_acceleration",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if fewer than 3 volume intervals available",
            description="Discrete 2nd-order acceleration: (V_t - 2*V_{t-1} + V_{t-2})"
        ))

        self.register(FeatureMetadata(
            feature_id="F_dist_to_prev_high_pct",
            knowledge_id="F_dist_to_prev_high_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="prior_completed_bars",
            calculation_function="KnowledgeV1Features.dist_to_prev_high_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if no historical highs available or price <= 0",
            description="Percentage distance to rolling highest price: (max_high - price) / price"
        ))

        self.register(FeatureMetadata(
            feature_id="F_dist_to_prev_low_pct",
            knowledge_id="F_dist_to_prev_low_pct",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="prior_completed_bars",
            calculation_function="KnowledgeV1Features.dist_to_prev_low_pct",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if no historical lows available or price <= 0",
            description="Percentage distance to rolling lowest price: (price - min_low) / price"
        ))

        self.register(FeatureMetadata(
            feature_id="F_intraday_return_1m",
            knowledge_id="F_intraday_return_1m",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="sequenced_prices",
            calculation_function="KnowledgeV1Features.intraday_return_nm",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if price 1 minute ago is missing",
            description="1-minute trailing price return"
        ))

        self.register(FeatureMetadata(
            feature_id="F_intraday_return_3m",
            knowledge_id="F_intraday_return_3m",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="sequenced_prices",
            calculation_function="KnowledgeV1Features.intraday_return_nm",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if price 3 minutes ago is missing",
            description="3-minute trailing price return"
        ))

        self.register(FeatureMetadata(
            feature_id="F_intraday_return_5m",
            knowledge_id="F_intraday_return_5m",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="sequenced_prices",
            calculation_function="KnowledgeV1Features.intraday_return_nm",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if price 5 minutes ago is missing",
            description="5-minute trailing price return"
        ))

        self.register(FeatureMetadata(
            feature_id="F_vwap_touch_count",
            knowledge_id="F_vwap_touch_count",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_bars_and_vwap",
            calculation_function="KnowledgeV1Features.vwap_touch_count",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns 0 if no prior touches",
            description="Causal count of price touches into VWAP +/- band from session open to t"
        ))

        self.register(FeatureMetadata(
            feature_id="F_vwap_cross_count",
            knowledge_id="F_vwap_cross_count",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="closed_bars_and_vwap",
            calculation_function="KnowledgeV1Features.vwap_cross_count",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns 0 if no prior crosses",
            description="Causal count of price crosses above/below VWAP from session open to t"
        ))

        self.register(FeatureMetadata(
            feature_id="F_pullback_vol_decay_ratio",
            knowledge_id="F_pullback_vol_decay_ratio",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="causal_segmented_bars",
            calculation_function="CausalSwingSegmenter.volume_decay_ratio",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if no confirmed swing pivot exists or impulse volume <= 0",
            description="Ratio of pullback volume rate to impulse volume rate using causal swing confirmation"
        ))

        self.register(FeatureMetadata(
            feature_id="F_aggressor_sell_share",
            knowledge_id="F_aggressor_sell_share",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="trades_tick_stream",
            calculation_function="KnowledgeV1Features.aggressor_sell_share",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if classified_volume <= 0",
            description="Share of sell-initiated volume: 1.0 - aggressor_buy_share"
        ))

        self.register(FeatureMetadata(
            feature_id="F_aggressor_volume_delta",
            knowledge_id="F_aggressor_volume_delta",
            source_status="AI_QUANTIZED",
            implementation_status=RegistryStatus.NEW_RESEARCH,
            data_source="trades_tick_stream",
            calculation_function="KnowledgeV1Features.aggressor_volume_delta",
            causal_safe=True,
            lookahead_risk="NONE",
            missing_data_policy="Returns None if no classified volume in window",
            description="Net signed trade volume: buy_volume - sell_volume in trailing window"
        ))

        # 3. Unsupported Features (Hard limitations)
        for fid in ("F_order_book_imbalance_5", "F_order_book_imbalance_weighted",
                    "F_bid_wall_thickness_ratio", "F_bid_wall_mean_ratio",
                    "F_quote_flip_rate_1m", "F_wall_depletion_velocity",
                    "F_tx_traded_lots_spread", "F_futures_bid_ask_spread_pct_book"):
            self.register(FeatureMetadata(
                feature_id=fid, knowledge_id=fid, source_status="AI_QUANTIZED",
                implementation_status=RegistryStatus.UNSUPPORTED,
                data_source="unsupported_external_feed", calculation_function=None,
                causal_safe=False, lookahead_risk="HIGH_UNSUPPORTED",
                missing_data_policy="Strictly unsupported; no synthetic proxy allowed"
            ))

        # 4. Future Data Required
        for fid in ("F_dealer_hedging_share_ratio_eod", "F_dealer_hedging_ratio_eod",
                    "F_futures_basis_pct", "F_sector_lead_lag_return_diff",
                    "F_turnover_rate_intraday"):
            self.register(FeatureMetadata(
                feature_id=fid, knowledge_id=fid, source_status="AI_QUANTIZED",
                implementation_status=RegistryStatus.FUTURE_DATA_REQUIRED,
                data_source="pending_pipeline_extension", calculation_function=None,
                causal_safe=True, lookahead_risk="LOW_AFTER_PARSER_UPDATE",
                missing_data_policy="Blocked pending crawler or matrix pipeline extension"
            ))
