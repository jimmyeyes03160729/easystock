"""EasyStock Daytrade Knowledge V1 - Phase 1 Research Module.

Research-only module. Strict read-only causality; no live/paper orders.
"""

from .registry import FeatureRegistry, RegistryStatus
from .causal_tools import CausalBarSeries, CausalSwingSegmenter
from .features import KnowledgeV1Features
from .rules import KnowledgeV1RuleEvaluator
from .backtest_dataset import ResearchDatasetBuilder

__all__ = [
    "FeatureRegistry",
    "RegistryStatus",
    "CausalBarSeries",
    "CausalSwingSegmenter",
    "KnowledgeV1Features",
    "KnowledgeV1RuleEvaluator",
    "ResearchDatasetBuilder",
]
