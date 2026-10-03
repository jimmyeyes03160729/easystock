"""Batch 2 Result Store for Context Filter Research.

Stores and serializes comparative evaluation between unfiltered signals and filtered subsets,
including Signal Funnel Accounting and Effect Decomposition.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence, Optional
import yaml

from .batch2_filter_runner import FilterComparisonResult, DroppedSignalRecord


class Batch2ResultStore:
    """Manages serialization of Batch 2 filter research results."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("docs/daytrade_phase2")

    def save_results_to_yaml(
        self,
        filepath: Path,
        metadata: dict[str, Any],
        comparisons: Sequence[FilterComparisonResult],
        dropped_signals: Optional[Sequence[DroppedSignalRecord]] = None,
    ) -> None:
        """Writes comparison results, metadata, and dropped signal funnel to target YAML path."""
        data = {
            "metadata": metadata,
            "filter_comparisons": [asdict(r) for r in comparisons],
        }
        if dropped_signals is not None:
            # Group drop reasons
            drop_reasons: dict[str, int] = {}
            for d in dropped_signals:
                drop_reasons[d.drop_reason] = drop_reasons.get(d.drop_reason, 0) + 1

            data["signal_funnel"] = {
                "total_raw_signals": metadata.get("total_raw_signals", 0),
                "total_simulated_signals": metadata.get("total_simulated_signals", 0),
                "total_dropped_signals": len(dropped_signals),
                "drop_reasons_breakdown": drop_reasons,
                "dropped_signals_sample": [asdict(d) for d in dropped_signals[:10]],
            }

        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
