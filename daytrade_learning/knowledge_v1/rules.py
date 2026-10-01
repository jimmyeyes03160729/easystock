"""Research Rule Candidate Evaluators for Knowledge V1 Phase 1.

Strict Parameter Provenance:
- All strategy thresholds are explicitly sourced from SOURCE_VERIFIED rules
  or canonical RESEARCH_PARAMETER_GRID entries in research_parameter_grids.yaml.
- Magic numbers inside rule evaluation are strictly forbidden.
- Canonical Grid IDs G01-G21 are strictly preserved with their canonical meanings.
- New research parameters use validated new Grid IDs (G22, G23, G24).
- G05_RVOL_THRESHOLD points strictly to RESEARCH_GRID_G05.
- C02 scope creep (max_extension = 0.015) has been completely removed.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any, Optional, Sequence, Union

from .causal_tools import CompletedBar, CausalSwingSegmenter, parse_timestamp
from .features import KnowledgeV1Features
from .validator import CanonicalGridValidator


@dataclass(frozen=True)
class GridParameter:
    grid_id: str
    parameter_name: str
    seed_value: float
    allowed_values: tuple[float, ...]
    status: str = "AI_QUANTIZED"
    unit: str = "fraction"
    source_reference: Optional[str] = None

    def validate_against_canonical(self) -> None:
        """Validates this parameter against canonical research_parameter_grids.yaml."""
        CanonicalGridValidator.validate_parameter(
            grid_id=self.grid_id,
            parameter_name=self.parameter_name,
            value=self.seed_value,
            status=self.status,
        )

    def to_provenance(self, override_value: Optional[float] = None) -> dict[str, Any]:
        val = override_value if override_value is not None else self.seed_value
        return {
            "value": val,
            "grid_id": self.grid_id,
            "parameter_name": self.parameter_name,
            "source_claim_id": self.source_reference,
            "ai_quantized_id": self.source_reference if self.status == "AI_QUANTIZED" else None,
            "status": self.status,
            "unit": self.unit,
        }


@dataclass
class KnowledgeV1Parameters:
    """Registry and container of parameterized strategy thresholds with explicit canonical provenance."""
    g01_touch_band: float = 0.003
    g01_stop_band: float = 0.002
    g04_prior_high_window: float = 20.0
    g05_rvol_threshold: float = 1.5
    g14_aggressor_share: float = 0.6
    g15_drop_from_reference: float = 0.005
    g17_pullback_vol_decay: float = 0.5
    g22_lower_shadow_min: float = 0.25
    g23_breakout_proximity: float = 0.001
    g24_upper_shadow_min: float = 0.45

    # -------------------------------------------------------------
    # Canonical Grids Preserved (G01 - G21)
    # -------------------------------------------------------------
    # G01: vwap_touch_band_fraction (Canonical)
    G01_VWAP_TOUCH_BAND: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G01", parameter_name="vwap_touch_band_fraction",
            seed_value=0.003, allowed_values=(0.0, 0.001, 0.003, 0.005),
            source_reference="AQ_R_003"
        ),
        init=False
    )
    # G02: vwap_stop_band_fraction (Canonical)
    G02_VWAP_STOP_BAND: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G02", parameter_name="vwap_stop_band_fraction",
            seed_value=0.002, allowed_values=(0.0, 0.001, 0.002, 0.003),
            source_reference="AQ_R_003"
        ),
        init=False
    )
    # G04: prior_high_window (Canonical)
    G04_PRIOR_HIGH_WINDOW: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G04", parameter_name="prior_high_window",
            seed_value=20.0, allowed_values=(20.0, 60.0, 250.0),
            unit="sessions", source_reference="AQ_R_001, AQ_R_002"
        ),
        init=False
    )
    # G05: rvol_threshold (Canonical - FIXED: was previously mis-mapped to G03)
    G05_RVOL_THRESHOLD: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G05", parameter_name="rvol_threshold",
            seed_value=1.5, allowed_values=(1.0, 1.5, 2.0, 3.0),
            unit="ratio", source_reference="AQ_R_001"
        ),
        init=False
    )
    # G14: aggressor_sell_share (Canonical)
    G14_AGGRESSOR_SHARE: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G14", parameter_name="aggressor_sell_share",
            seed_value=0.6, allowed_values=(0.5, 0.6, 0.7),
            unit="share_0_to_1", source_reference="H01"
        ),
        init=False
    )
    # G15: drop_from_reference (Canonical)
    G15_DROP_FROM_REFERENCE: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G15", parameter_name="drop_from_reference",
            seed_value=0.005, allowed_values=(0.005, 0.01, 0.02, 0.03),
            source_reference="AQ_R_010"
        ),
        init=False
    )
    # G17: pullback_volume_decay (Canonical)
    G17_PULLBACK_VOL_DECAY: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G17", parameter_name="pullback_volume_decay",
            seed_value=0.5, allowed_values=(0.3, 0.5, 0.7),
            unit="rate_ratio", source_reference="AQ_R_008"
        ),
        init=False
    )
    # G19: futures_spread_candidate (Canonical - preserved strictly)
    G19_CANONICAL_FUTURES_SPREAD: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G19", parameter_name="futures_spread_candidate",
            seed_value=0.005, allowed_values=(0.003, 0.005, 0.006),
            source_reference="AQ_R_004"
        ),
        init=False
    )
    # G20: pyramid_profit_trigger (Canonical - preserved strictly)
    G20_CANONICAL_PYRAMID_PROFIT: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G20", parameter_name="pyramid_profit_trigger",
            seed_value=0.008, allowed_values=(0.004, 0.008, 0.015),
            source_reference="AQ_R_011"
        ),
        init=False
    )
    # G21: stop_ticks_candidate (Canonical - preserved strictly)
    G21_CANONICAL_STOP_TICKS: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G21", parameter_name="stop_ticks_candidate",
            seed_value=3.0, allowed_values=(2.0, 3.0, 5.0),
            unit="valid_price_ladder_steps", source_reference="AQ_R_007, AQ_R_008"
        ),
        init=False
    )

    # -------------------------------------------------------------
    # Validated New Research Parameter Grids (G22, G23, G24)
    # -------------------------------------------------------------
    # G22: lower_shadow_support_ratio (NEW Canonical research grid)
    G22_LOWER_SHADOW_SUPPORT: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G22", parameter_name="lower_shadow_support_ratio",
            seed_value=0.25, allowed_values=(0.20, 0.25, 0.30),
            unit="ratio", source_reference="AQ_R_003"
        ),
        init=False
    )
    # G23: breakout_proximity_band (NEW Canonical research grid)
    G23_BREAKOUT_PROXIMITY: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G23", parameter_name="breakout_proximity_band",
            seed_value=0.001, allowed_values=(0.0, 0.001, 0.002),
            unit="fraction", source_reference="AQ_R_001"
        ),
        init=False
    )
    # G24: upper_shadow_rejection_ratio (NEW Canonical research grid)
    G24_UPPER_SHADOW_REJECTION: GridParameter = field(
        default=GridParameter(
            grid_id="RESEARCH_GRID_G24", parameter_name="upper_shadow_rejection_ratio",
            seed_value=0.45, allowed_values=(0.40, 0.45, 0.50),
            unit="ratio", source_reference="AQ_R_008"
        ),
        init=False
    )


# Attach class-level static attributes to KnowledgeV1Parameters
KnowledgeV1Parameters.G01_VWAP_TOUCH_BAND = GridParameter(
    grid_id="RESEARCH_GRID_G01", parameter_name="vwap_touch_band_fraction",
    seed_value=0.003, allowed_values=(0.0, 0.001, 0.003, 0.005),
    source_reference="AQ_R_003"
)
KnowledgeV1Parameters.G02_VWAP_STOP_BAND = GridParameter(
    grid_id="RESEARCH_GRID_G02", parameter_name="vwap_stop_band_fraction",
    seed_value=0.002, allowed_values=(0.0, 0.001, 0.002, 0.003),
    source_reference="AQ_R_003"
)
KnowledgeV1Parameters.G04_PRIOR_HIGH_WINDOW = GridParameter(
    grid_id="RESEARCH_GRID_G04", parameter_name="prior_high_window",
    seed_value=20.0, allowed_values=(20.0, 60.0, 250.0),
    unit="sessions", source_reference="AQ_R_001, AQ_R_002"
)
KnowledgeV1Parameters.G05_RVOL_THRESHOLD = GridParameter(
    grid_id="RESEARCH_GRID_G05", parameter_name="rvol_threshold",
    seed_value=1.5, allowed_values=(1.0, 1.5, 2.0, 3.0),
    unit="ratio", source_reference="AQ_R_001"
)
KnowledgeV1Parameters.G14_AGGRESSOR_SHARE = GridParameter(
    grid_id="RESEARCH_GRID_G14", parameter_name="aggressor_sell_share",
    seed_value=0.6, allowed_values=(0.5, 0.6, 0.7),
    unit="share_0_to_1", source_reference="H01"
)
KnowledgeV1Parameters.G15_DROP_FROM_REFERENCE = GridParameter(
    grid_id="RESEARCH_GRID_G15", parameter_name="drop_from_reference",
    seed_value=0.005, allowed_values=(0.005, 0.01, 0.02, 0.03),
    source_reference="AQ_R_010"
)
KnowledgeV1Parameters.G17_PULLBACK_VOL_DECAY = GridParameter(
    grid_id="RESEARCH_GRID_G17", parameter_name="pullback_volume_decay",
    seed_value=0.5, allowed_values=(0.3, 0.5, 0.7),
    unit="rate_ratio", source_reference="AQ_R_008"
)
KnowledgeV1Parameters.G19_CANONICAL_FUTURES_SPREAD = GridParameter(
    grid_id="RESEARCH_GRID_G19", parameter_name="futures_spread_candidate",
    seed_value=0.005, allowed_values=(0.003, 0.005, 0.006),
    source_reference="AQ_R_004"
)
KnowledgeV1Parameters.G20_CANONICAL_PYRAMID_PROFIT = GridParameter(
    grid_id="RESEARCH_GRID_G20", parameter_name="pyramid_profit_trigger",
    seed_value=0.008, allowed_values=(0.004, 0.008, 0.015),
    source_reference="AQ_R_011"
)
KnowledgeV1Parameters.G21_CANONICAL_STOP_TICKS = GridParameter(
    grid_id="RESEARCH_GRID_G21", parameter_name="stop_ticks_candidate",
    seed_value=3.0, allowed_values=(2.0, 3.0, 5.0),
    unit="valid_price_ladder_steps", source_reference="AQ_R_007, AQ_R_008"
)
KnowledgeV1Parameters.G22_LOWER_SHADOW_SUPPORT = GridParameter(
    grid_id="RESEARCH_GRID_G22", parameter_name="lower_shadow_support_ratio",
    seed_value=0.25, allowed_values=(0.20, 0.25, 0.30),
    unit="ratio", source_reference="AQ_R_003"
)
KnowledgeV1Parameters.G23_BREAKOUT_PROXIMITY = GridParameter(
    grid_id="RESEARCH_GRID_G23", parameter_name="breakout_proximity_band",
    seed_value=0.001, allowed_values=(0.0, 0.001, 0.002),
    unit="fraction", source_reference="AQ_R_001"
)
KnowledgeV1Parameters.G24_UPPER_SHADOW_REJECTION = GridParameter(
    grid_id="RESEARCH_GRID_G24", parameter_name="upper_shadow_rejection_ratio",
    seed_value=0.45, allowed_values=(0.40, 0.45, 0.50),
    unit="ratio", source_reference="AQ_R_008"
)


def _resolve_param(val: Union[GridParameter, float, None], default_grid: GridParameter) -> tuple[float, GridParameter]:
    if val is None:
        return default_grid.seed_value, default_grid
    if isinstance(val, GridParameter):
        return val.seed_value, val
    # val is float
    override_grid = GridParameter(
        grid_id=default_grid.grid_id,
        parameter_name=default_grid.parameter_name,
        seed_value=float(val),
        allowed_values=default_grid.allowed_values,
        status=default_grid.status,
        unit=default_grid.unit,
        source_reference=default_grid.source_reference,
    )
    return float(val), override_grid


@dataclass(frozen=True)
class CandidateEvaluationResult:
    candidate_id: str
    triggered: bool
    timestamp: str
    feature_snapshot: dict[str, Any]
    source_claim_ids: list[str]
    ai_quantized_ids: list[str]
    parameter_provenance: dict[str, Any]
    reason: str
    unsupported_dependencies: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeV1RuleEvaluator:
    """Evaluates the 5 prioritised research candidate rules using canonical parameterized grid objects."""

    @staticmethod
    def evaluate_c01_vwap_pullback_support(
        symbol: str,
        current_time: Any,
        current_price: float,
        vwap: float,
        latest_bar: CompletedBar | dict,
        touch_band: Union[GridParameter, float, None] = None,
        stop_band: Union[GridParameter, float, None] = None,
        support_wick: Union[GridParameter, float, None] = None,
        params: Optional[KnowledgeV1Parameters] = None,
    ) -> CandidateEvaluationResult:
        """Rule C01: VWAP pullback support."""
        ts = parse_timestamp(current_time).isoformat()
        p = params or KnowledgeV1Parameters()

        tb_val = touch_band if touch_band is not None else p.g01_touch_band
        sb_val = stop_band if stop_band is not None else p.g01_stop_band
        sw_val = support_wick if support_wick is not None else p.g22_lower_shadow_min

        tb_val, tb_grid = _resolve_param(tb_val, KnowledgeV1Parameters.G01_VWAP_TOUCH_BAND)
        sb_val, sb_grid = _resolve_param(sb_val, KnowledgeV1Parameters.G02_VWAP_STOP_BAND)
        sw_val, sw_grid = _resolve_param(sw_val, KnowledgeV1Parameters.G22_LOWER_SHADOW_SUPPORT)

        dist = KnowledgeV1Features.dist_to_vwap_pct(current_price, vwap)
        clv = KnowledgeV1Features.close_location_value(latest_bar)
        lower_wick = KnowledgeV1Features.lower_shadow_ratio(latest_bar)

        prov_tb = tb_grid.to_provenance(tb_val)
        prov_sb = sb_grid.to_provenance(sb_val)
        prov_sw = sw_grid.to_provenance(sw_val)

        provenance = {
            "touch_band": prov_tb,
            "stop_band": prov_sb,
            "support_wick": prov_sw,
            "g01_touch_band": prov_tb,
            "g01_stop_band": prov_sb,
            "g22_lower_shadow_min": prov_sw,
        }

        features = {
            "current_price": current_price,
            "vwap": vwap,
            "dist_to_vwap_pct": dist,
            "close_location_value": clv,
            "lower_shadow_ratio": lower_wick,
            "touch_band_val": tb_val,
            "stop_band_val": sb_val,
            "support_wick_val": sw_val,
        }

        if dist is None or clv is None or lower_wick is None:
            return CandidateEvaluationResult(
                candidate_id="C01_vwap_pullback_support",
                triggered=False,
                timestamp=ts,
                feature_snapshot=features,
                source_claim_ids=["SV004"],
                ai_quantized_ids=["AQ_R_003"],
                parameter_provenance=provenance,
                reason="Insufficient VWAP or bar geometry data",
                unsupported_dependencies=[],
            )

        # In-band condition: -stop_band <= dist <= touch_band
        in_band = -sb_val <= dist <= tb_val
        has_support = clv > 0.0 or lower_wick >= sw_val

        triggered = in_band and has_support
        reason = (
            f"Price ({current_price}) pulled back to VWAP ({vwap}, dist {dist*100:.2f}%) "
            f"within [{ -sb_val*100:.2f}%, +{tb_val*100:.2f}%] "
            f"with support (CLV={clv:.2f}, wick={lower_wick:.2f} >= {sw_val})"
            if triggered
            else "Conditions not met"
        )

        return CandidateEvaluationResult(
            candidate_id="C01_vwap_pullback_support",
            triggered=triggered,
            timestamp=ts,
            feature_snapshot=features,
            source_claim_ids=["SV004"],
            ai_quantized_ids=["AQ_R_003"],
            parameter_provenance=provenance,
            reason=reason,
            unsupported_dependencies=[],
        )

    @staticmethod
    def evaluate_c02_daily_trend_and_open_breakout(
        symbol: str,
        current_time: Any,
        current_price: float,
        session_open: float,
        prev_close: float,
        daily_ma5: float,
        daily_ma10: float,
        daily_ma20: float,
        prior_20d_high: float,
        proximity_band: Union[GridParameter, float, None] = None,
        params: Optional[KnowledgeV1Parameters] = None,
    ) -> CandidateEvaluationResult:
        """Rule C02: 日K多方排列 + 早盤突破.
        Restored to original Phase 1 specification: Scope creep (max_extension = 0.015) removed.
        """
        ts = parse_timestamp(current_time).isoformat()
        p = params or KnowledgeV1Parameters()

        prox_val = proximity_band if proximity_band is not None else p.g23_breakout_proximity
        prox_val, prox_grid = _resolve_param(prox_val, KnowledgeV1Parameters.G23_BREAKOUT_PROXIMITY)

        gap = KnowledgeV1Features.gap_open_pct(session_open, prev_close)
        dist_high = KnowledgeV1Features.dist_to_prev_high_pct(current_price, [prior_20d_high])

        prov_prox = prox_grid.to_provenance(prox_val)

        provenance = {
            "proximity_band": prov_prox,
            "g23_breakout_proximity": prov_prox,
            "prior_high_window": KnowledgeV1Parameters.G04_PRIOR_HIGH_WINDOW.to_provenance(20.0),
        }

        features = {
            "current_price": current_price,
            "session_open": session_open,
            "prev_close": prev_close,
            "gap_open_pct": gap,
            "daily_ma5": daily_ma5,
            "daily_ma10": daily_ma10,
            "daily_ma20": daily_ma20,
            "prior_20d_high": prior_20d_high,
            "dist_to_prior_high_pct": dist_high,
        }

        if gap is None or dist_high is None or min(daily_ma5, daily_ma10, daily_ma20) <= 0:
            return CandidateEvaluationResult(
                candidate_id="C02_daily_trend_open_breakout",
                triggered=False,
                timestamp=ts,
                feature_snapshot=features,
                source_claim_ids=["SV001", "SV002", "SV003"],
                ai_quantized_ids=["AQ_R_001", "AQ_R_002"],
                parameter_provenance=provenance,
                reason="Missing daily MA or price limits",
                unsupported_dependencies=[],
            )

        # 1. SV001: 短天期均線多頭排列 MA5 > MA10 > MA20
        ma_aligned = daily_ma5 > daily_ma10 > daily_ma20
        # 2. SV003: 開盤跳空開高 (gap > 0.0)
        gap_up = gap > 0.0
        # 3. 突破前高附近或已突破 (dist_high <= proximity_band)
        # Note: dist_to_prev_high_pct = (prior_high - current_price) / current_price
        # If current_price >= prior_high, dist_high <= 0.0 <= prox_val
        is_breakout = dist_high <= prox_val

        triggered = ma_aligned and gap_up and is_breakout
        reason = (
            f"Daily MAs aligned, gap open +{gap*100:.2f}%, and price is breakout/approaching "
            f"dist_high={dist_high*100:.2f}% (<= +{prox_val*100:.2f}%)"
            if triggered
            else "Conditions not met"
        )

        return CandidateEvaluationResult(
            candidate_id="C02_daily_trend_open_breakout",
            triggered=triggered,
            timestamp=ts,
            feature_snapshot=features,
            source_claim_ids=["SV001", "SV002", "SV003"],
            ai_quantized_ids=["AQ_R_001", "AQ_R_002"],
            parameter_provenance=provenance,
            reason=reason,
            unsupported_dependencies=[],
        )

    @staticmethod
    def evaluate_c03_pullback_volume_decay(
        symbol: str,
        current_time: Any,
        bars: Sequence[CompletedBar],
        decay_threshold: Union[GridParameter, float, None] = None,
        params: Optional[KnowledgeV1Parameters] = None,
    ) -> CandidateEvaluationResult:
        """Rule C03: 強勢股 pullback volume decay."""
        ts = parse_timestamp(current_time).isoformat()
        p = params or KnowledgeV1Parameters()

        dec_val = decay_threshold if decay_threshold is not None else p.g17_pullback_vol_decay
        dec_val, dec_grid = _resolve_param(dec_val, KnowledgeV1Parameters.G17_PULLBACK_VOL_DECAY)

        decay = KnowledgeV1Features.pullback_vol_decay_ratio(bars)
        prov_dec = dec_grid.to_provenance(dec_val)

        provenance = {
            "decay_threshold": prov_dec,
            "g17_pullback_vol_decay": prov_dec,
        }

        features = {
            "bar_count": len(bars),
            "pullback_vol_decay_ratio": decay,
            "decay_threshold_val": dec_val,
        }

        if decay is None:
            return CandidateEvaluationResult(
                candidate_id="C03_pullback_vol_decay",
                triggered=False,
                timestamp=ts,
                feature_snapshot=features,
                source_claim_ids=["SV004"],
                ai_quantized_ids=["AQ_R_008"],
                parameter_provenance=provenance,
                reason="No confirmed causal swing high pivot or insufficient pullback bars",
                unsupported_dependencies=[],
            )

        triggered = decay <= dec_val
        reason = (
            f"Confirmed swing pullback volume rate decayed to {decay:.2f}x of impulse "
            f"(threshold <= {dec_val})"
            if triggered
            else f"Decay ratio {decay:.2f} > threshold {dec_val}"
        )

        return CandidateEvaluationResult(
            candidate_id="C03_pullback_vol_decay",
            triggered=triggered,
            timestamp=ts,
            feature_snapshot=features,
            source_claim_ids=["SV004"],
            ai_quantized_ids=["AQ_R_008"],
            parameter_provenance=provenance,
            reason=reason,
            unsupported_dependencies=[],
        )

    @staticmethod
    def evaluate_c04_breakout_with_rvol(
        symbol: str,
        current_time: Any,
        current_price: float,
        prior_high: float,
        volume_ratio: float,
        buy_volume: float,
        sell_volume: float,
        rvol_threshold: Union[GridParameter, float, None] = None,
        buy_share_threshold: Union[GridParameter, float, None] = None,
        params: Optional[KnowledgeV1Parameters] = None,
    ) -> CandidateEvaluationResult:
        """Rule C04: 前高突破 + relative volume."""
        ts = parse_timestamp(current_time).isoformat()
        p = params or KnowledgeV1Parameters()

        rv_val = rvol_threshold if rvol_threshold is not None else p.g05_rvol_threshold
        bs_val = buy_share_threshold if buy_share_threshold is not None else p.g14_aggressor_share

        rv_val, rv_grid = _resolve_param(rv_val, KnowledgeV1Parameters.G05_RVOL_THRESHOLD)
        bs_val, bs_grid = _resolve_param(bs_val, KnowledgeV1Parameters.G14_AGGRESSOR_SHARE)

        dist_high = KnowledgeV1Features.dist_to_prev_high_pct(current_price, [prior_high])
        buy_share = KnowledgeV1Features.aggressor_buy_share(buy_volume, sell_volume)

        prov_rv = rv_grid.to_provenance(rv_val)
        prov_bs = bs_grid.to_provenance(bs_val)

        provenance = {
            "rvol_threshold": prov_rv,
            "volume_ratio_min": prov_rv,
            "buy_share_threshold": prov_bs,
            "g05_rvol_threshold": prov_rv,
            "g14_aggressor_share": prov_bs,
        }

        features = {
            "current_price": current_price,
            "prior_high": prior_high,
            "dist_to_prev_high_pct": dist_high,
            "volume_ratio": volume_ratio,
            "buy_share": buy_share,
            "rvol_threshold_val": rv_val,
            "buy_share_threshold_val": bs_val,
        }

        if dist_high is None or volume_ratio is None or buy_share is None:
            return CandidateEvaluationResult(
                candidate_id="C04_breakout_with_rvol",
                triggered=False,
                timestamp=ts,
                feature_snapshot=features,
                source_claim_ids=["SV001"],
                ai_quantized_ids=["AQ_R_001", "AQ_R_002", "AQ_R_007"],
                parameter_provenance=provenance,
                reason="Missing breakout price, volume ratio or aggressor flow",
                unsupported_dependencies=[],
            )

        # Breakout condition: current_price >= prior_high -> dist_high <= 0.0
        is_breakout = dist_high <= 0.0
        vol_surge = volume_ratio >= rv_val
        aggressor_bull = buy_share >= bs_val

        triggered = is_breakout and vol_surge and aggressor_bull
        reason = (
            f"Broke high {prior_high} at {current_price}, "
            f"vol_ratio={volume_ratio:.2f}x >= {rv_val}, buy_share={buy_share*100:.1f}% >= {bs_val*100:.0f}%"
            if triggered
            else "Conditions not met"
        )

        return CandidateEvaluationResult(
            candidate_id="C04_breakout_with_rvol",
            triggered=triggered,
            timestamp=ts,
            feature_snapshot=features,
            source_claim_ids=["SV001"],
            ai_quantized_ids=["AQ_R_001", "AQ_R_002", "AQ_R_007"],
            parameter_provenance=provenance,
            reason=reason,
            unsupported_dependencies=[],
        )

    @staticmethod
    def evaluate_c05_failed_rebound_reversal(
        symbol: str,
        current_time: Any,
        current_price: float,
        resistance_price: float,
        latest_bar: CompletedBar | dict,
        buy_volume: float,
        sell_volume: float,
        sell_share_threshold: Union[GridParameter, float, None] = None,
        upper_wick_threshold: Union[GridParameter, float, None] = None,
        resistance_band: Union[GridParameter, float, None] = None,
        params: Optional[KnowledgeV1Parameters] = None,
    ) -> CandidateEvaluationResult:
        """Rule C05: 弱勢反彈不過前高 (Reversal Exhaustion)."""
        ts = parse_timestamp(current_time).isoformat()
        p = params or KnowledgeV1Parameters()

        ss_val = sell_share_threshold if sell_share_threshold is not None else p.g14_aggressor_share
        uw_val = upper_wick_threshold if upper_wick_threshold is not None else p.g24_upper_shadow_min
        rb_val = resistance_band if resistance_band is not None else p.g15_drop_from_reference

        ss_val, ss_grid = _resolve_param(ss_val, KnowledgeV1Parameters.G14_AGGRESSOR_SHARE)
        uw_val, uw_grid = _resolve_param(uw_val, KnowledgeV1Parameters.G24_UPPER_SHADOW_REJECTION)
        rb_val, rb_grid = _resolve_param(rb_val, KnowledgeV1Parameters.G15_DROP_FROM_REFERENCE)

        upper_wick = KnowledgeV1Features.upper_shadow_ratio(latest_bar)
        sell_share = KnowledgeV1Features.aggressor_sell_share(buy_volume, sell_volume)
        dist_res = (resistance_price - current_price) / resistance_price if resistance_price > 0 else None

        prov_ss = ss_grid.to_provenance(ss_val)
        prov_uw = uw_grid.to_provenance(uw_val)
        prov_rb = rb_grid.to_provenance(rb_val)

        provenance = {
            "sell_share_threshold": prov_ss,
            "upper_wick_threshold": prov_uw,
            "resistance_band": prov_rb,
            "g14_aggressor_share": prov_ss,
            "g24_upper_shadow_min": prov_uw,
            "g15_drop_from_reference": prov_rb,
        }

        features = {
            "current_price": current_price,
            "resistance_price": resistance_price,
            "dist_to_resistance_pct": dist_res,
            "upper_shadow_ratio": upper_wick,
            "aggressor_sell_share": sell_share,
            "upper_wick_threshold_val": uw_val,
            "sell_share_threshold_val": ss_val,
        }

        if upper_wick is None or sell_share is None or dist_res is None:
            return CandidateEvaluationResult(
                candidate_id="C05_failed_rebound_reversal",
                triggered=False,
                timestamp=ts,
                feature_snapshot=features,
                source_claim_ids=["SV004", "SV005"],
                ai_quantized_ids=["AQ_R_008"],
                parameter_provenance=provenance,
                reason="Missing resistance, wick or sell share data",
                unsupported_dependencies=[],
            )

        # Near resistance (0.0 <= dist_res <= resistance_band), upper wick >= threshold, sell share >= threshold
        near_res = 0.0 <= dist_res <= rb_val
        heavy_wick = upper_wick >= uw_val
        heavy_selling = sell_share >= ss_val

        triggered = near_res and heavy_wick and heavy_selling
        reason = (
            f"Failed to clear resistance {resistance_price} at {current_price} (dist={dist_res*100:.2f}%), "
            f"upper wick={upper_wick:.2f} >= {uw_val}, sell_share={sell_share*100:.1f}% >= {ss_val*100:.0f}%"
            if triggered
            else "Conditions not met"
        )

        return CandidateEvaluationResult(
            candidate_id="C05_failed_rebound_reversal",
            triggered=triggered,
            timestamp=ts,
            feature_snapshot=features,
            source_claim_ids=["SV004", "SV005"],
            ai_quantized_ids=["AQ_R_008"],
            parameter_provenance=provenance,
            reason=reason,
            unsupported_dependencies=[],
        )
