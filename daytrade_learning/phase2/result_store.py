"""Phase 2B Research Result Store & Summary Formatter.

Stores parameter grid evaluation results, baseline comparisons,
and research verdicts.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

from .comparator import BaselineComparator, ComparisonResult, ResearchVerdict


@dataclass
class CandidateParameterResult:
    candidate_id: str
    parameter_set_id: str
    parameters: dict[str, Any]
    slippage_ticks: int
    trade_count: int
    win_rate: float
    expectancy_R: float
    median_R: float
    profit_factor: float
    SQN: float
    MFE_R: float
    MAE_R: float
    verdict: str
    verdict_reason: str
    slippage_bps: Optional[float] = None


class ResearchResultStore:
    """In-memory and file store for Phase 2B candidate evaluations."""

    def __init__(self):
        self.results: list[CandidateParameterResult] = []

    def record_result(
        self,
        candidate_id: str,
        parameter_set_id: str,
        parameters: dict[str, Any],
        slippage_ticks: int = 0,
        slippage_bps: Optional[float] = None,
        metrics: Optional[dict[str, float]] = None,
        comparator: Optional[BaselineComparator] = None,
        baseline_metrics: Optional[dict[str, float]] = None,
    ) -> CandidateParameterResult:
        metrics = metrics or {}
        comp_res: ComparisonResult
        if comparator and baseline_metrics:
            comp_res = comparator.compare(metrics, baseline_metrics)
        else:
            comp_res = ComparisonResult(ResearchVerdict.INCONCLUSIVE, "NO_COMPARATOR")

        res = CandidateParameterResult(
            candidate_id=candidate_id,
            parameter_set_id=parameter_set_id,
            parameters=dict(parameters),
            slippage_ticks=slippage_ticks,
            trade_count=int(metrics.get("trade_count", 0)),
            win_rate=float(metrics.get("win_rate", 0.0)),
            expectancy_R=float(metrics.get("expectancy_R", 0.0)),
            median_R=float(metrics.get("median_R", 0.0)),
            profit_factor=float(metrics.get("profit_factor", 0.0)),
            SQN=float(metrics.get("SQN", 0.0)),
            MFE_R=float(metrics.get("MFE_R", 0.0)),
            MAE_R=float(metrics.get("MAE_R", 0.0)),
            verdict=comp_res.verdict.value,
            verdict_reason=comp_res.reason,
            slippage_bps=slippage_bps,
        )
        self.results.append(res)
        return res

    def to_dict(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in self.results]
