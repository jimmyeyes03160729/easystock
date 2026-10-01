"""Research Backtest Dataset Builder for Knowledge V1 Phase 1.

Strict Causality & Execution Clock Contract (aligned with daytrade_learning/research.py):
1. signal_time: The timestamp when candidate conditions are evaluated.
2. decision_available_time: signal_time + 2 seconds safety buffer.
3. execution_time: The start of the next full minute bar after decision_available_time:
   (signal_time + 2s).replace(second=0, microsecond=0) + timedelta(minutes=1)
4. execution_price: Open price of the execution bar * (1 + slippage_bps/10000).
5. If no valid completed bar exists at execution_time:
   execution_status = 'NO_CAUSAL_EXECUTION', prices/returns set to None. No fabricated fills.
6. Forward returns and MFE/MAE are strictly computed from execution_time and execution_price.
7. Features and evaluation labels are strictly separated to prevent target leakage.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from .causal_tools import CompletedBar, parse_timestamp
from .rules import CandidateEvaluationResult

# Cost model identical to paper_ledger.py
BUY_RATE = 0.001425 * 0.28   # 28折手續費
SELL_RATE = 0.001425 * 0.28  # 28折手續費
DAY_TAX_RATE = 0.0015        # 現股當沖證交稅 0.15%
MIN_FEE = 20.0               # 最低手續費 20 元
EXECUTION_BUFFER_SECONDS = 2 # Minimum 2-second decision/routing buffer


@dataclass(frozen=True)
class ResearchEventRecord:
    symbol: str
    signal_time: str
    decision_available_time: str
    execution_time: Optional[str]
    execution_status: str  # 'FILLED' or 'NO_CAUSAL_EXECUTION'
    candidate_id: str
    feature_snapshot: dict[str, Any]
    execution_price: Optional[float]
    forward_return_1m: Optional[float]
    forward_return_3m: Optional[float]
    forward_return_5m: Optional[float]
    forward_return_10m: Optional[float]
    forward_return_30m: Optional[float]
    mfe: Optional[float]
    mae: Optional[float]
    market_gate_state: str
    market_regime_if_available: Optional[str]
    transaction_cost_estimate: Optional[float]
    slippage_assumption_bps: float
    simulated_notional: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def features_vector(self) -> dict[str, Any]:
        """Strictly returns features known at signal_time; excludes all forward labels."""
        return dict(self.feature_snapshot)


def compute_causal_execution_time(
    signal_time: datetime,
    safety_buffer_seconds: int = EXECUTION_BUFFER_SECONDS,
) -> tuple[datetime, datetime]:
    """Computes decision_available_time (+2s) and execution_time (next full minute start).
    Contract identical to daytrade_learning/research.py:282.
    """
    available_time = signal_time + timedelta(seconds=safety_buffer_seconds)
    execution_time = available_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return available_time, execution_time


class ResearchDatasetBuilder:
    """Builds offline research episode records adhering to the delayed execution clock."""

    @staticmethod
    def calculate_transaction_cost(notional: float) -> float:
        """Transaction cost based on paper_ledger.py rules."""
        if notional <= 0:
            return 0.0
        buy_fee = max(MIN_FEE, notional * BUY_RATE)
        sell_fee = max(MIN_FEE, notional * SELL_RATE)
        tax = notional * DAY_TAX_RATE
        return round(buy_fee + sell_fee + tax, 2)

    @classmethod
    def compute_causal_execution_time(cls, signal_time: datetime) -> tuple[datetime, datetime]:
        """Computes decision_available_time (+2s) and execution_time (next full minute start).
        Contract identical to daytrade_learning/research.py:282.
        """
        return compute_causal_execution_time(signal_time)

    @classmethod
    def build_record(
        cls,
        symbol: str,
        trigger_result: CandidateEvaluationResult,
        bars_pool: Optional[Sequence[CompletedBar | dict]] = None,
        candidate_bars: Optional[Sequence[CompletedBar | dict]] = None,
        market_gate_state: str = "GREEN",
        market_regime: Optional[str] = None,
        slippage_bps: float = 5.0,
        simulated_shares: int = 1000,
    ) -> Optional[ResearchEventRecord]:
        """Given a candidate trigger and subsequent completed bars, compute causal fills and returns."""
        if not trigger_result.triggered:
            return None

        raw_pool = candidate_bars if candidate_bars is not None else bars_pool
        if raw_pool is None:
            raw_pool = []

        sig_time = parse_timestamp(trigger_result.timestamp)
        decision_time, exec_time = cls.compute_causal_execution_time(sig_time)

        # Standardize bars pool as CompletedBar objects
        standardized_bars: list[CompletedBar] = []
        for b in raw_pool:
            if isinstance(b, CompletedBar):
                standardized_bars.append(b)
            elif isinstance(b, dict):
                end = parse_timestamp(b.get("at") or b.get("end_time") or b.get("ts"))
                start = parse_timestamp(b.get("start_time") or (end - timedelta(minutes=1)))
                standardized_bars.append(CompletedBar(
                    start_time=start,
                    end_time=end,
                    open=float(b.get("open") or b.get("Open")),
                    high=float(b.get("high") or b.get("High")),
                    low=float(b.get("low") or b.get("Low")),
                    close=float(b.get("close") or b.get("Close")),
                    volume=float(b.get("volume") or b.get("Volume") or 0.0),
                ))
        standardized_bars.sort(key=lambda x: x.end_time)

        # Locate the execution bar: the bar whose start_time matches exec_time
        # or whose time window covers exec_time
        exec_bar = None
        for b in standardized_bars:
            if b.start_time <= exec_time < b.end_time or b.start_time == exec_time:
                exec_bar = b
                break

        # If no bar exists at execution_time or zero volume, record NO_CAUSAL_EXECUTION
        if exec_bar is None or exec_bar.volume <= 0 or exec_bar.open <= 0:
            return ResearchEventRecord(
                symbol=str(symbol),
                signal_time=sig_time.isoformat(),
                decision_available_time=decision_time.isoformat(),
                execution_time=exec_time.isoformat(),
                execution_status="NO_CAUSAL_EXECUTION",
                candidate_id=trigger_result.candidate_id,
                feature_snapshot=dict(trigger_result.feature_snapshot),
                execution_price=None,
                forward_return_1m=None,
                forward_return_3m=None,
                forward_return_5m=None,
                forward_return_10m=None,
                forward_return_30m=None,
                mfe=None,
                mae=None,
                market_gate_state=str(market_gate_state),
                market_regime_if_available=market_regime,
                transaction_cost_estimate=None,
                slippage_assumption_bps=slippage_bps,
                simulated_notional=None,
            )

        # Execution succeeded
        slippage_factor = 1.0 + (slippage_bps / 10000.0)
        execution_price = round(exec_bar.open * slippage_factor, 4)
        notional = round(execution_price * simulated_shares, 2)
        cost = cls.calculate_transaction_cost(notional)

        # Bars strictly subsequent to or starting from execution
        # Future horizons are relative to exec_time
        def get_forward_return(horizon_minutes: int) -> Optional[float]:
            target_time = exec_time + timedelta(minutes=horizon_minutes)
            # Find the bar whose end_time covers target_time
            matching = [b for b in standardized_bars if b.end_time >= target_time and b.start_time >= exec_time]
            if matching:
                p_exit = matching[0].close
                return round((p_exit - execution_price) / execution_price, 6)
            return None

        ret_1m = get_forward_return(1)
        ret_3m = get_forward_return(3)
        ret_5m = get_forward_return(5)
        ret_10m = get_forward_return(10)
        ret_30m = get_forward_return(30)

        # MFE / MAE over 30 minutes following execution
        max_horizon_time = exec_time + timedelta(minutes=30)
        path_bars = [b for b in standardized_bars if b.start_time >= exec_time and b.end_time <= max_horizon_time]

        mfe = None
        mae = None
        if path_bars:
            highest_path = max(b.high for b in path_bars)
            lowest_path = min(b.low for b in path_bars)
            mfe = round(max(0.0, (highest_path - execution_price) / execution_price), 6)
            mae = round(max(0.0, (execution_price - lowest_path) / execution_price), 6)

        return ResearchEventRecord(
            symbol=str(symbol),
            signal_time=sig_time.isoformat(),
            decision_available_time=decision_time.isoformat(),
            execution_time=exec_time.isoformat(),
            execution_status="FILLED",
            candidate_id=trigger_result.candidate_id,
            feature_snapshot=dict(trigger_result.feature_snapshot),
            execution_price=execution_price,
            forward_return_1m=ret_1m,
            forward_return_3m=ret_3m,
            forward_return_5m=ret_5m,
            forward_return_10m=ret_10m,
            forward_return_30m=ret_30m,
            mfe=mfe,
            mae=mae,
            market_gate_state=str(market_gate_state),
            market_regime_if_available=market_regime,
            transaction_cost_estimate=cost,
            slippage_assumption_bps=slippage_bps,
            simulated_notional=notional,
        )
