"""Phase 2A Walk-Forward Framework with Event-Based Purging & Embargo.

MAJOR FIX 4:
- IndexWalkForwardSplitter is marked NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS = True.
- EventWalkForwardSplitter enforces event-time based purging and embargo.
- Purging prevents any training sample label interval [sample_time, label_end_time]
  from overlapping with the test evaluation interval [test_start, test_end].
- Embargo enforces a post-test quarantine buffer to prevent auto-correlation leakage.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Generic, Sequence, TypeVar

from .execution import parse_phase2_timestamp

T = TypeVar("T")


@dataclass(frozen=True)
class WalkForwardFold(Generic[T]):
    fold_index: int
    train_indices: list[int]
    test_indices: list[int]
    train_items: list[T]
    test_items: list[T]
    test_start_time: datetime
    test_end_time: datetime
    purged_count: int
    embargoed_count: int


class IndexWalkForwardSplitter:
    """Legacy index-based walk-forward splitter.
    
    WARNING: Not safe for overlapping forward-looking labels.
    """
    NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS: bool = True

    def __init__(self, n_splits: int = 5, gap: int = 0):
        self.n_splits = n_splits
        self.gap = gap

    def split(self, items: Sequence[Any]) -> list[tuple[list[int], list[int]]]:
        n = len(items)
        if n < self.n_splits + 1:
            raise ValueError(f"Sample count {n} too small for {self.n_splits} splits")
        fold_size = n // (self.n_splits + 1)
        splits = []
        for i in range(1, self.n_splits + 1):
            train_end = i * fold_size
            test_start = train_end + self.gap
            test_end = min(n, test_start + fold_size)
            if test_start < n:
                splits.append((list(range(0, train_end)), list(range(test_start, test_end))))
        return splits


class EventWalkForwardSplitter:
    """Strictly causal event-time walk-forward splitter with label purging and embargo.
    
    Prevents leakage by checking:
    1. Purging: Training sample label_end_time >= test_start_time (for samples before test).
    2. Embargo: Training sample_time <= test_end_time + embargo_duration (for samples after test).
    """
    NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS: bool = False

    def __init__(
        self,
        n_splits: int = 5,
        embargo_duration: timedelta = timedelta(minutes=30),
    ):
        if n_splits < 1:
            raise ValueError("n_splits must be at least 1")
        self.n_splits = n_splits
        self.embargo_duration = embargo_duration

    @staticmethod
    def _extract_times(item: Any) -> tuple[datetime, datetime, datetime]:
        """Extract (sample_time, label_start_time, label_end_time) from object or dict."""
        if hasattr(item, "sample_time") and hasattr(item, "label_end_time"):
            st = parse_phase2_timestamp(item.sample_time)
            ls = parse_phase2_timestamp(getattr(item, "label_start_time", item.sample_time))
            le = parse_phase2_timestamp(item.label_end_time)
            return st, ls, le
        elif isinstance(item, dict):
            st = parse_phase2_timestamp(item.get("sample_time") or item.get("signal_time"))
            ls = parse_phase2_timestamp(item.get("label_start_time") or item.get("execution_time") or st)
            le = parse_phase2_timestamp(item.get("label_end_time") or item.get("exit_time") or ls)
            return st, ls, le
        raise TypeError(f"Item must have sample_time and label_end_time attributes or keys: {type(item)}")

    def split(self, items: Sequence[T]) -> list[WalkForwardFold[T]]:
        """Splits items into walk-forward folds with rigorous purging and embargo."""
        n = len(items)
        if n < self.n_splits + 1:
            raise ValueError(f"Dataset length ({n}) too small for {self.n_splits} splits")

        # Sort items chronologically by sample_time
        indexed_items = list(enumerate(items))
        indexed_items.sort(key=lambda pair: self._extract_times(pair[1])[0])

        step = n // (self.n_splits + 1)
        folds: list[WalkForwardFold[T]] = []

        for fold_idx in range(1, self.n_splits + 1):
            train_raw = indexed_items[:fold_idx * step]
            test_slice = indexed_items[fold_idx * step:(fold_idx + 1) * step]

            if not test_slice or not train_raw:
                continue

            test_times = [self._extract_times(pair[1]) for pair in test_slice]
            test_start = min(t[0] for t in test_times)
            test_end = max(t[2] for t in test_times)

            # Purge & Embargo
            clean_train_indices: list[int] = []
            clean_train_items: list[T] = []
            purged = 0
            embargoed = 0

            for orig_idx, item in train_raw:
                s_time, _, l_end = self._extract_times(item)

                # Prior training items: purge if forward label reaches into test interval
                if s_time < test_start:
                    if l_end >= test_start:
                        purged += 1
                        continue
                # If training items appear after test (e.g. cross validation): embargo check
                elif s_time >= test_end:
                    if s_time <= (test_end + self.embargo_duration):
                        embargoed += 1
                        continue
                else:
                    # Inside test window: purge
                    purged += 1
                    continue

                clean_train_indices.append(orig_idx)
                clean_train_items.append(item)

            test_indices = [pair[0] for pair in test_slice]
            test_items = [pair[1] for pair in test_slice]

            folds.append(
                WalkForwardFold(
                    fold_index=fold_idx,
                    train_indices=clean_train_indices,
                    test_indices=test_indices,
                    train_items=clean_train_items,
                    test_items=test_items,
                    test_start_time=test_start,
                    test_end_time=test_end,
                    purged_count=purged,
                    embargoed_count=embargoed,
                )
            )

        return folds
