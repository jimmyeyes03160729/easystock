"""Phase 2A Baseline Comparator & Research-Only Verdicts.

CRITICAL GOVERNANCE REQUIREMENTS:
- Permitted research verdicts:
  1. KEEP_FOR_MORE_RESEARCH
  2. REJECT_RESEARCH_CANDIDATE
  3. DATA_INSUFFICIENT
  4. CAUSALITY_FAILURE
  5. EXECUTION_INVALID

- STRICTLY FORBIDDEN:
  - PROMOTE_TO_PRODUCTION is not defined and strictly prohibited.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResearchVerdict(str, Enum):
    KEEP_FOR_MORE_RESEARCH = "KEEP_FOR_MORE_RESEARCH"
    REJECT_RESEARCH_CANDIDATE = "REJECT_RESEARCH_CANDIDATE"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    CAUSALITY_FAILURE = "CAUSALITY_FAILURE"
    EXECUTION_INVALID = "EXECUTION_INVALID"


FORBIDDEN_VERDICTS = {"PROMOTE_TO_PRODUCTION", "PASS_TO_PRODUCTION", "DEPLOY"}


@dataclass(frozen=True)
class ComparisonResult:
    verdict: ResearchVerdict
    candidate_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    deltas: dict[str, float]
    reason: str

    def __post_init__(self):
        if str(self.verdict) in FORBIDDEN_VERDICTS:
            raise ValueError(f"Forbidden verdict: {self.verdict} is never permitted in Phase 2A research.")


class BaselineComparator:
    """Compares candidate strategy metrics against a reference baseline."""

    def __init__(self, min_trades_required: int = 30):
        self.min_trades_required = min_trades_required

    def compare(
        self,
        candidate_metrics: dict[str, float],
        baseline_metrics: dict[str, float],
    ) -> ComparisonResult:
        """Evaluates candidate relative to baseline.
        
        Outputs research verdicts only: KEEP_FOR_MORE_RESEARCH, REJECT_RESEARCH_CANDIDATE, or DATA_INSUFFICIENT.
        """
        n = candidate_metrics.get("trade_count", 0)
        if n < self.min_trades_required:
            return ComparisonResult(
                verdict=ResearchVerdict.DATA_INSUFFICIENT,
                candidate_metrics=candidate_metrics,
                baseline_metrics=baseline_metrics,
                deltas={},
                reason=f"Insufficient sample size: {n} trades < {self.min_trades_required} required",
            )

        cand_exp = candidate_metrics.get("expectancy_R", 0.0)
        base_exp = baseline_metrics.get("expectancy_R", 0.0)
        cand_pf = candidate_metrics.get("profit_factor", 0.0)
        base_pf = baseline_metrics.get("profit_factor", 0.0)

        deltas = {
            "expectancy_R_delta": round(cand_exp - base_exp, 4),
            "profit_factor_delta": round(cand_pf - base_pf, 4),
            "win_rate_delta": round(
                candidate_metrics.get("win_rate", 0.0) - baseline_metrics.get("win_rate", 0.0), 4
            ),
        }

        # Pure research evaluation: does candidate show excess expectancy over baseline?
        if cand_exp > base_exp and cand_pf > 1.0:
            verdict = ResearchVerdict.KEEP_FOR_MORE_RESEARCH
            reason = f"Candidate expectancy (+{deltas['expectancy_R_delta']} R) and PF ({cand_pf:.2f}) exceed baseline"
        else:
            verdict = ResearchVerdict.REJECT_RESEARCH_CANDIDATE
            reason = f"Candidate fails to outperform baseline (expectancy delta: {deltas['expectancy_R_delta']} R)"

        return ComparisonResult(
            verdict=verdict,
            candidate_metrics=candidate_metrics,
            baseline_metrics=baseline_metrics,
            deltas=deltas,
            reason=reason,
        )
