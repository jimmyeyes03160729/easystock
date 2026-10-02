"""Phase 2B Research Runner.

Coordinates:
- Candidate signal detection
- CausalExecutionClock order execution
- Research-only exit policies (Fixed horizon 5m/15m/30m/60m, StopTargetExit)
- Phase 2A Single Source of Truth accounting
- EventWalkForwardSplitter evaluation
- Baseline comparison & research-only verdicts
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from .costs import TransactionCostModel, get_twse_tick_size
from .dataset import Phase2TradeRecord, create_phase2_trade
from .execution import CausalExecutionClock, MarketBar, parse_phase2_timestamp
from .metrics import calculate_trade_metrics
from .comparator import BaselineComparator, ComparisonResult, ResearchVerdict
from .walkforward import EventWalkForwardSplitter, WalkForwardFold


@dataclass(frozen=True)
class ResearchExitPolicy:
    name: str
    horizon_minutes: int
    target_R: Optional[float] = None
    use_trailing_stop: bool = False


# Standard Research Exit Baselines
EXIT_FIXED_5M = ResearchExitPolicy(name="FIXED_HORIZON_5M", horizon_minutes=5)
EXIT_FIXED_15M = ResearchExitPolicy(name="FIXED_HORIZON_15M", horizon_minutes=15)
EXIT_FIXED_30M = ResearchExitPolicy(name="FIXED_HORIZON_30M", horizon_minutes=30)
EXIT_FIXED_60M = ResearchExitPolicy(name="FIXED_HORIZON_60M", horizon_minutes=60)
EXIT_STOP_TARGET_1_5R = ResearchExitPolicy(
    name="STOP_TARGET_1_5R_MAX30M", horizon_minutes=30, target_R=1.5
)


class ResearchRunner:
    """Executes offline historical signal research adhering to Phase 2A contracts."""

    def __init__(
        self,
        cost_model: Optional[TransactionCostModel] = None,
        clock: Optional[CausalExecutionClock] = None,
        default_quantity: int = 1000,
    ):
        self.cost_model = cost_model or TransactionCostModel()
        self.clock = clock or CausalExecutionClock(safety_buffer_seconds=2)
        self.default_quantity = default_quantity

    def simulate_trade_from_signal(
        self,
        signal: Any,  # PullbackSignal, RangeExpansionSignal, TwoBSignal, OneTwoThreeSignal
        all_bars: Sequence[MarketBar],
        exit_policy: ResearchExitPolicy = EXIT_FIXED_15M,
        slippage_ticks: int = 0,
        slippage_bps: Optional[float] = None,
    ) -> Optional[Phase2TradeRecord]:
        """Simulates trade entry and exit for a detected candidate signal.
        
        Slippage Semantics:
        - Canonical: slippage_ticks in [0, 1, 2, 3] ticks, mapped via TWSE official tick size.
        - Secondary sensitivity: slippage_bps.
        """
        exec_res = self.clock.execute_market_entry(
            signal_time=signal.signal_time,
            bars=all_bars,
            direction=signal.direction,
            slippage_ticks=slippage_ticks,
            slippage_bps=slippage_bps,
            feature_time=signal.feature_time,
        )
        if exec_res["status"] != "FILLED":
            return None

        entry_bar: MarketBar = exec_res["bar"]
        entry_time = parse_phase2_timestamp(exec_res["execution_time"])
        actual_entry = exec_res["actual_entry_price"]
        theo_entry = exec_res["theoretical_entry_price"]

        def _apply_exit_slippage(theo_p: float, is_long: bool) -> float:
            if slippage_bps is not None:
                amt = theo_p * (slippage_bps / 10000.0)
            else:
                amt = slippage_ticks * get_twse_tick_size(theo_p)
            return theo_p - amt if is_long else theo_p + amt

        # Filter subsequent bars strictly after entry_time
        subsequent_bars = [b for b in all_bars if b.bar_open_time >= entry_time]
        if not subsequent_bars:
            return None

        dir_upper = signal.direction.upper()
        stop_loss = signal.stop_loss_price
        initial_risk_per_share = abs(actual_entry - stop_loss)
        if initial_risk_per_share <= 0:
            return None

        target_price = None
        if exit_policy.target_R is not None:
            if dir_upper == "LONG":
                target_price = actual_entry + (initial_risk_per_share * exit_policy.target_R)
            else:
                target_price = actual_entry - (initial_risk_per_share * exit_policy.target_R)

        # Causal forward walk to simulate exit
        exit_bar: Optional[MarketBar] = None
        exit_type = "HORIZON"
        theo_exit = None
        actual_exit = None

        trade_bars: list[MarketBar] = []
        max_duration = timedelta(minutes=exit_policy.horizon_minutes)

        for b in subsequent_bars:
            trade_bars.append(b)
            # 1. Stop loss check
            if dir_upper == "LONG" and b.low <= stop_loss:
                exit_bar = b
                exit_type = "STOP_LOSS"
                theo_exit = stop_loss
                actual_exit = _apply_exit_slippage(theo_exit, is_long=True)
                break
            elif dir_upper == "SHORT" and b.high >= stop_loss:
                exit_bar = b
                exit_type = "STOP_LOSS"
                theo_exit = stop_loss
                actual_exit = _apply_exit_slippage(theo_exit, is_long=False)
                break

            # 2. Profit target check
            if target_price is not None:
                if dir_upper == "LONG" and b.high >= target_price:
                    exit_bar = b
                    exit_type = "TARGET"
                    theo_exit = target_price
                    actual_exit = _apply_exit_slippage(theo_exit, is_long=True)
                    break
                elif dir_upper == "SHORT" and b.low <= target_price:
                    exit_bar = b
                    exit_type = "TARGET"
                    theo_exit = target_price
                    actual_exit = _apply_exit_slippage(theo_exit, is_long=False)
                    break

            # 3. Horizon time exit
            elapsed = b.bar_close_time - entry_time
            if elapsed >= max_duration:
                exit_bar = b
                exit_type = "HORIZON_EXPIRY"
                theo_exit = b.close
                actual_exit = _apply_exit_slippage(theo_exit, is_long=(dir_upper == "LONG"))
                break

        if exit_bar is None:
            # Reached end of session without stop or target
            exit_bar = subsequent_bars[-1]
            theo_exit = exit_bar.close
            actual_exit = _apply_exit_slippage(theo_exit, is_long=(dir_upper == "LONG"))

        # Enforce valid stop loss constraints
        if dir_upper == "LONG" and stop_loss >= actual_entry:
            return None
        if dir_upper == "SHORT" and stop_loss <= actual_entry:
            return None

        # Build trade record
        features_extended = dict(signal.features)
        features_extended["exit_type"] = exit_type
        features_extended["exit_policy"] = exit_policy.name
        features_extended["slippage_ticks"] = slippage_ticks
        if slippage_bps is not None:
            features_extended["slippage_bps"] = slippage_bps

        trade = create_phase2_trade(
            symbol=signal.symbol,
            direction=dir_upper,
            quantity=self.default_quantity,
            feature_time=signal.feature_time,
            signal_time=signal.signal_time,
            decision_available_time=exec_res["decision_available_time"],
            execution_time=entry_time,
            exit_time=exit_bar.bar_close_time,
            theoretical_entry_price=round(theo_entry, 4),
            actual_entry_price=round(actual_entry, 4),
            theoretical_exit_price=round(theo_exit, 4),
            actual_exit_price=round(actual_exit, 4),
            stop_loss_price=round(stop_loss, 4),
            intraday_bars_during_trade=trade_bars,
            features_snapshot=features_extended,
            cost_model=self.cost_model,
            is_daytrade=True,
            sample_time=signal.signal_time,
            label_start_time=entry_time,
            label_end_time=exit_bar.bar_close_time,
        )
        return trade

    def evaluate_candidate(
        self,
        trades: Sequence[Phase2TradeRecord],
        n_splits: int = 3,
        embargo_duration: timedelta = timedelta(minutes=15),
    ) -> dict[str, Any]:
        """Runs walk-forward evaluation and metrics for a list of trades."""
        if not trades:
            return {
                "trade_count": 0,
                "overall_metrics": calculate_trade_metrics([]),
                "walk_forward_folds": [],
            }

        overall_metrics = calculate_trade_metrics(trades)

        folds_summary = []
        if len(trades) >= n_splits + 2:
            splitter = EventWalkForwardSplitter(
                n_splits=n_splits,
                embargo_duration=embargo_duration,
            )
            folds = splitter.split(trades)
            for fold in folds:
                train_m = calculate_trade_metrics(fold.train_items)
                test_m = calculate_trade_metrics(fold.test_items)
                folds_summary.append({
                    "fold": fold.fold_index,
                    "train_trades": len(fold.train_items),
                    "test_trades": len(fold.test_items),
                    "purged_count": fold.purged_count,
                    "embargoed_count": fold.embargoed_count,
                    "train_expectancy_R": train_m.get("expectancy_R", 0.0),
                    "test_expectancy_R": test_m.get("expectancy_R", 0.0),
                    "train_win_rate": train_m.get("win_rate", 0.0),
                    "test_win_rate": test_m.get("win_rate", 0.0),
                })

        return {
            "trade_count": len(trades),
            "overall_metrics": overall_metrics,
            "walk_forward_folds": folds_summary,
        }
