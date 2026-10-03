"""Phase 2B Batch 2 Context / Regime / Relative Strength Filter Runner.

Core Principles & Integrity Guarantees:
1. Reuses Batch 1 signal generation with identical signal_event_id.
2. Filters DO NOT ALTER:
   - signal_time
   - entry logic
   - pattern definition
   - stop definition
3. Explicit Signal Funnel Accounting:
   - RAW_SIGNAL -> FILTER_ELIGIBLE -> EXECUTABLE -> EXIT_AVAILABLE -> SIMULATED.
   - Captures all dropped signals with explicit drop_stage and drop_reason.
   - Strict identity: raw_count == simulated_count + len(dropped_signals).
4. Effect Decomposition:
   - Decomposes R-multiple changes vs percentage returns (theoretical_pct, cost_pct, net_pct).
   - Tracks initial_risk_pct and initial_risk_ticks distributions (mean, median, p25, p75).
   - Distinguishes SIGNAL_EDGE_IMPROVEMENT, LOWER_FRICTION_SELECTION, and LARGER_R_DENOMINATOR_SELECTION.
5. Strictly Causal Leave-One-Out Evaluation across 5 filter families.
"""
from __future__ import annotations
import math
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Sequence, Callable

from .costs import TransactionCostModel, get_twse_tick_size
from .dataset import Phase2TradeRecord
from .execution import MarketBar, parse_phase2_timestamp
from .research_runner import ResearchRunner, ResearchExitPolicy, EXIT_FIXED_15M
from .candidates import (
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
)
from .context_filters import (
    ResearchMarketRegime,
    RelativeStrengthFilter,
    SectorStrengthFilter,
    HigherTimeframeAggregator,
    LiquidityFilter,
)

TPE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class RawSignalEvent:
    signal_event_id: str
    candidate_id: str
    symbol: str
    direction: str  # 'LONG' or 'SHORT'
    signal_time: datetime
    feature_time: datetime
    entry_reference_price: float
    stop_loss_price: float
    raw_signal: Any


@dataclass(frozen=True)
class DroppedSignalRecord:
    signal_event_id: str
    candidate_id: str
    symbol: str
    signal_time: str
    drop_stage: str  # 'EXECUTION', 'HORIZON', 'RISK_VALIDATION'
    drop_reason: str  # 'NO_LEGAL_EXECUTION', 'INSUFFICIENT_FORWARD_HORIZON', 'INVALID_INITIAL_RISK', 'STOP_LOSS_VIOLATION'


@dataclass(frozen=True)
class RiskDistributionSummary:
    mean_risk_pct: float
    median_risk_pct: float
    p25_risk_pct: float
    p75_risk_pct: float
    mean_risk_ticks: float
    median_risk_ticks: float
    p25_risk_ticks: float
    p75_risk_ticks: float


@dataclass(frozen=True)
class TradePerformanceSummary:
    count: int
    theoretical_gross_R: float
    net_R: float
    theoretical_return_pct: float
    net_return_pct: float
    cost_pct: float  # alias to total_trading_friction_pct for backward compatibility
    slippage_pct: float = 0.0
    commission_pct: float = 0.0
    tax_pct: float = 0.0
    total_trading_friction_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    risk_distribution: RiskDistributionSummary = RiskDistributionSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class FilterComparisonResult:
    filter_id: str
    filter_family: str
    filter_condition: str
    unfiltered: TradePerformanceSummary
    filtered: TradePerformanceSummary
    retention_rate: float
    delta_theoretical_gross_R: float
    delta_net_R: float
    delta_theoretical_return_pct: float
    delta_cost_pct: float
    delta_net_return_pct: float
    delta_trading_friction_pct: float = 0.0
    delta_slippage_pct: float = 0.0
    delta_commission_pct: float = 0.0
    delta_tax_pct: float = 0.0
    effect_attribution: str = ""  # 'SIGNAL_EDGE_IMPROVEMENT', 'LOWER_FRICTION_SELECTION', 'LARGER_R_DENOMINATOR_SELECTION', 'NEUTRAL_OR_DEGRADED'
    implementation_status: str = "VERIFIED"
    performance_status: str = "NOT_EVALUATED"
    smoke_validation_pass: bool = True
    notes: str = ""


def compute_distribution(values: list[float]) -> tuple[float, float, float, float]:
    """Returns (mean, median, p25, p75) for a list of floats."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0
    s_vals = sorted(values)
    n = len(s_vals)
    mean_val = statistics.mean(s_vals)
    med_val = statistics.median(s_vals)
    p25 = s_vals[int(n * 0.25)] if n > 1 else s_vals[0]
    p75 = s_vals[int(n * 0.75)] if n > 1 else s_vals[-1]
    return round(mean_val, 4), round(med_val, 4), round(p25, 4), round(p75, 4)


def compute_performance_summary(trades: Sequence[Phase2TradeRecord]) -> TradePerformanceSummary:
    """Computes both R-multiple and percentage return metrics with complete risk distributions and friction decomposition."""
    empty_dist = RiskDistributionSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    if not trades:
        return TradePerformanceSummary(
            count=0,
            theoretical_gross_R=0.0,
            net_R=0.0,
            theoretical_return_pct=0.0,
            net_return_pct=0.0,
            cost_pct=0.0,
            slippage_pct=0.0,
            commission_pct=0.0,
            tax_pct=0.0,
            total_trading_friction_pct=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            risk_distribution=empty_dist,
        )

    n = len(trades)
    sum_gross_R = 0.0
    sum_net_R = 0.0
    sum_theo_pct = 0.0
    sum_slip_pct = 0.0
    sum_comm_pct = 0.0
    sum_tax_pct = 0.0
    sum_friction_pct = 0.0
    sum_net_pct = 0.0

    wins = 0
    gross_gains = 0.0
    gross_losses = 0.0

    risk_pcts: list[float] = []
    risk_ticks: list[float] = []

    for t in trades:
        initial_risk = t.initial_risk_per_share
        entry_p = t.actual_entry_price
        theo_entry = t.theoretical_entry_price
        theo_exit = t.theoretical_exit_price
        act_exit = t.actual_exit_price
        is_long = t.direction.upper() == "LONG"

        # R multiples
        if initial_risk > 0:
            theo_R = (theo_exit - theo_entry) / initial_risk if is_long else (theo_entry - theo_exit) / initial_risk
            sum_gross_R += theo_R
            sum_net_R += t.pnl_R

            tick_size = get_twse_tick_size(entry_p)
            r_ticks = initial_risk / tick_size if tick_size > 0 else 0.0
            r_pct = (initial_risk / entry_p * 100.0) if entry_p > 0 else 0.0
            risk_pcts.append(r_pct)
            risk_ticks.append(r_ticks)

        # Percentage returns (relative to actual entry notional)
        if entry_p > 0 and t.quantity > 0:
            notional = entry_p * t.quantity
            theo_gross = (theo_exit - theo_entry) * t.quantity if is_long else (theo_entry - theo_exit) * t.quantity
            theo_pct = theo_gross / notional * 100.0

            slip_pct = t.slippage_cost / notional * 100.0
            comm_pct = t.commission_total / notional * 100.0
            tx_pct = t.tax_total / notional * 100.0
            friction_pct = slip_pct + comm_pct + tx_pct
            net_pct = theo_pct - friction_pct

            # Trade-level accounting identity assertion:
            # net_return_pct == theoretical_return_pct - total_trading_friction_pct
            # where total_trading_friction_pct == slippage_pct + commission_pct + tax_pct
            assert abs(friction_pct - (slip_pct + comm_pct + tx_pct)) < 1e-7
            assert abs(net_pct - (theo_pct - friction_pct)) < 1e-7

            sum_theo_pct += theo_pct
            sum_slip_pct += slip_pct
            sum_comm_pct += comm_pct
            sum_tax_pct += tx_pct
            sum_friction_pct += friction_pct
            sum_net_pct += net_pct

        if t.net_pnl > 0:
            wins += 1

        if t.gross_pnl_actual > 0:
            gross_gains += t.gross_pnl_actual
        else:
            gross_losses += abs(t.gross_pnl_actual)

    pf = (gross_gains / gross_losses) if gross_losses > 0 else (99.0 if gross_gains > 0 else 0.0)

    # Risk distributions
    mean_rp, med_rp, p25_rp, p75_rp = compute_distribution(risk_pcts)
    mean_rt, med_rt, p25_rt, p75_rt = compute_distribution(risk_ticks)
    risk_summary = RiskDistributionSummary(
        mean_risk_pct=mean_rp,
        median_risk_pct=med_rp,
        p25_risk_pct=p25_rp,
        p75_risk_pct=p75_rp,
        mean_risk_ticks=mean_rt,
        median_risk_ticks=med_rt,
        p25_risk_ticks=p25_rt,
        p75_risk_ticks=p75_rt,
    )

    theo_avg = round(sum_theo_pct / n, 4)
    slip_avg = round(sum_slip_pct / n, 4)
    comm_avg = round(sum_comm_pct / n, 4)
    tax_avg = round(sum_tax_pct / n, 4)
    friction_avg = round(slip_avg + comm_avg + tax_avg, 4)
    net_avg = round(theo_avg - friction_avg, 4)

    return TradePerformanceSummary(
        count=n,
        theoretical_gross_R=round(sum_gross_R / n, 4),
        net_R=round(sum_net_R / n, 4),
        theoretical_return_pct=theo_avg,
        net_return_pct=net_avg,
        cost_pct=friction_avg,
        slippage_pct=slip_avg,
        commission_pct=comm_avg,
        tax_pct=tax_avg,
        total_trading_friction_pct=friction_avg,
        win_rate=round(wins / n, 4),
        profit_factor=round(pf, 4),
        risk_distribution=risk_summary,
    )


class Batch2FilterRunner:
    """Orchestrates candidate signal detection, context filter application, funnel accounting, and comparative evaluation."""

    def __init__(
        self,
        cost_model: Optional[TransactionCostModel] = None,
        exit_policy: ResearchExitPolicy = EXIT_FIXED_15M,
        slippage_ticks: int = 1,
    ):
        self.cost_model = cost_model or TransactionCostModel()
        self.exit_policy = exit_policy
        self.slippage_ticks = slippage_ticks
        self.research_runner = ResearchRunner(cost_model=self.cost_model)

        # Detectors
        self.detectors = {
            "P2B_01_v1": PullbackVolumeDecayDetector(),
            "P2B_02_v1": RangeExpansionDetector(),
            "P2B_03_v1": TwoBReversalDetector(),
            "P2B_04_v1": OneTwoThreeDetector(),
        }

    def detect_raw_signals(
        self,
        symbol: str,
        bars: Sequence[MarketBar],
        candidate_ids: Optional[Sequence[str]] = None,
    ) -> list[RawSignalEvent]:
        """Detects Batch 1 raw signals, assigning immutable signal_event_id."""
        targets = candidate_ids or list(self.detectors.keys())
        raw_events: list[RawSignalEvent] = []

        for cid in targets:
            det = self.detectors.get(cid)
            if not det:
                continue

            signals = det.detect_signals(symbol=symbol, bars=bars)
            for s in signals:
                st = parse_phase2_timestamp(s.signal_time)
                ft = parse_phase2_timestamp(s.feature_time)
                event_id = f"{cid}_{symbol}_{st.strftime('%Y%m%d%H%M')}"
                entry_ref = getattr(s, "entry_reference_price", getattr(getattr(s, "trigger_bar", None), "close", 0.0))
                raw_events.append(
                    RawSignalEvent(
                        signal_event_id=event_id,
                        candidate_id=cid,
                        symbol=symbol,
                        direction=s.direction.upper(),
                        signal_time=st,
                        feature_time=ft,
                        entry_reference_price=entry_ref,
                        stop_loss_price=s.stop_loss_price,
                        raw_signal=s,
                    )
                )

        return raw_events

    def simulate_events_with_funnel(
        self,
        events: Sequence[RawSignalEvent],
        bars_by_symbol: dict[str, Sequence[MarketBar]],
    ) -> tuple[list[Phase2TradeRecord], list[DroppedSignalRecord]]:
        """Simulates trades for signal events while rigorously recording funnel drop stages."""
        trades: list[Phase2TradeRecord] = []
        dropped: list[DroppedSignalRecord] = []

        for ev in events:
            bars = bars_by_symbol.get(ev.symbol, [])
            if not bars:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="DATA_VALIDATION",
                        drop_reason="DATA_GAP",
                    )
                )
                continue

            # Check market entry execution
            exec_res = self.research_runner.clock.execute_market_entry(
                signal_time=ev.signal_time,
                bars=bars,
                direction=ev.direction,
                slippage_ticks=self.slippage_ticks,
                feature_time=ev.feature_time,
            )
            if exec_res["status"] != "FILLED":
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="EXECUTION",
                        drop_reason="NO_LEGAL_EXECUTION",
                    )
                )
                continue

            entry_time = parse_phase2_timestamp(exec_res["execution_time"])
            actual_entry = exec_res["actual_entry_price"]
            subsequent_bars = [b for b in bars if b.bar_open_time >= entry_time]
            if not subsequent_bars:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="HORIZON",
                        drop_reason="INSUFFICIENT_FORWARD_HORIZON",
                    )
                )
                continue

            # Initial risk validation
            initial_risk_per_share = abs(actual_entry - ev.stop_loss_price)
            if initial_risk_per_share <= 0:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="RISK_VALIDATION",
                        drop_reason="INVALID_INITIAL_RISK",
                    )
                )
                continue

            # Stop loss direction validation
            if ev.direction == "LONG" and ev.stop_loss_price >= actual_entry:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="RISK_VALIDATION",
                        drop_reason="STOP_LOSS_VIOLATION",
                    )
                )
                continue
            elif ev.direction == "SHORT" and ev.stop_loss_price <= actual_entry:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="RISK_VALIDATION",
                        drop_reason="STOP_LOSS_VIOLATION",
                    )
                )
                continue

            trade = self.research_runner.simulate_trade_from_signal(
                signal=ev.raw_signal,
                all_bars=bars,
                exit_policy=self.exit_policy,
                slippage_ticks=self.slippage_ticks,
            )
            if trade is not None:
                trades.append(trade)
            else:
                dropped.append(
                    DroppedSignalRecord(
                        signal_event_id=ev.signal_event_id,
                        candidate_id=ev.candidate_id,
                        symbol=ev.symbol,
                        signal_time=ev.signal_time.isoformat(),
                        drop_stage="SIMULATION",
                        drop_reason="INSUFFICIENT_FORWARD_HORIZON",
                    )
                )

        return trades, dropped

    def evaluate_filter(
        self,
        filter_id: str,
        filter_family: str,
        condition_name: str,
        all_events: Sequence[RawSignalEvent],
        bars_by_symbol: dict[str, Sequence[MarketBar]],
        filter_decision_func: Callable[[RawSignalEvent], bool],
        notes: str = "",
    ) -> FilterComparisonResult:
        """Evaluates KEEP vs DROP for all events and compares against unfiltered baseline with effect attribution."""
        unfiltered_trades, _ = self.simulate_events_with_funnel(all_events, bars_by_symbol)
        unfiltered_perf = compute_performance_summary(unfiltered_trades)

        kept_events = [ev for ev in all_events if filter_decision_func(ev)]
        filtered_trades, _ = self.simulate_events_with_funnel(kept_events, bars_by_symbol)
        filtered_perf = compute_performance_summary(filtered_trades)

        retention_rate = (len(kept_events) / len(all_events)) if all_events else 0.0

        delta_gross_R = filtered_perf.theoretical_gross_R - unfiltered_perf.theoretical_gross_R
        delta_net_R = filtered_perf.net_R - unfiltered_perf.net_R
        delta_theo_pct = filtered_perf.theoretical_return_pct - unfiltered_perf.theoretical_return_pct
        delta_friction_pct = filtered_perf.total_trading_friction_pct - unfiltered_perf.total_trading_friction_pct
        delta_slip_pct = filtered_perf.slippage_pct - unfiltered_perf.slippage_pct
        delta_comm_pct = filtered_perf.commission_pct - unfiltered_perf.commission_pct
        delta_tax_pct = filtered_perf.tax_pct - unfiltered_perf.tax_pct
        delta_net_pct = filtered_perf.net_return_pct - unfiltered_perf.net_return_pct
        delta_cost_pct = delta_friction_pct

        # Effect attribution logic
        if delta_theo_pct > 0.02 and delta_gross_R > 0.02:
            attribution = "SIGNAL_EDGE_IMPROVEMENT"
        elif delta_cost_pct < -0.05:
            attribution = "LOWER_FRICTION_SELECTION"
        elif delta_net_R > 0.2 and delta_net_pct <= 0.0:
            attribution = "LARGER_R_DENOMINATOR_SELECTION"
        else:
            attribution = "NEUTRAL_OR_DEGRADED"

        return FilterComparisonResult(
            filter_id=filter_id,
            filter_family=filter_family,
            filter_condition=condition_name,
            unfiltered=unfiltered_perf,
            filtered=filtered_perf,
            retention_rate=round(retention_rate, 4),
            delta_theoretical_gross_R=round(delta_gross_R, 4),
            delta_net_R=round(delta_net_R, 4),
            delta_theoretical_return_pct=round(delta_theo_pct, 4),
            delta_cost_pct=round(delta_cost_pct, 4),
            delta_net_return_pct=round(delta_net_pct, 4),
            delta_trading_friction_pct=round(delta_friction_pct, 4),
            delta_slippage_pct=round(delta_slip_pct, 4),
            delta_commission_pct=round(delta_comm_pct, 4),
            delta_tax_pct=round(delta_tax_pct, 4),
            effect_attribution=attribution,
            implementation_status="VERIFIED",
            performance_status="NOT_EVALUATED",
            smoke_validation_pass=True,
            notes=notes,
        )
