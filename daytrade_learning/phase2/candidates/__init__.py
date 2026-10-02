"""Batch 1 Research Candidate Detectors for Phase 2B.

All candidates are strictly research-only and inert by default.
1. P2B_01_PULLBACK_VOLUME_DECAY
2. P2B_02_RANGE_EXPANSION
3. P2B_03_2B_REVERSAL
4. P2B_04_1_2_3_REVERSAL
"""
from __future__ import annotations

from .pullback_volume_decay import PullbackVolumeDecayDetector, PullbackSignal
from .range_expansion import RangeExpansionDetector, RangeExpansionSignal
from .two_b_reversal import TwoBReversalDetector, TwoBSignal
from .one_two_three import OneTwoThreeDetector, OneTwoThreeSignal

__all__ = [
    "PullbackVolumeDecayDetector",
    "PullbackSignal",
    "RangeExpansionDetector",
    "RangeExpansionSignal",
    "TwoBReversalDetector",
    "TwoBSignal",
    "OneTwoThreeDetector",
    "OneTwoThreeSignal",
]
