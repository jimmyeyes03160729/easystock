"""Phase 2C F01 Follow-up: Proxy Breadth Context (H05).

Tracks true causal leave-one-out peer constituent counts at timestamp t:
1. proxy_constituent_count_at_t: Peer symbols available at bar t (excluding target symbol)
2. Invariant guard:
   - MAX_PEER_COUNT <= 99 (active universe <= 100).
   - If peer_count > 99 or peer_count < 0: raises CausalityOrMetadataFailure (CAUSALITY_OR_METADATA_FAILURE).
3. Pre-registered buckets:
   - BREADTH_34_54: Legacy ~55-symbol archive regime
   - BREADTH_55_79: Intermediate/transition archive regime
   - BREADTH_80_99: Expanded 100-symbol archive regime
   - INSUFFICIENT_BREADTH: peer_count < 34 (explicit status, strictly NO silent drop)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


class CausalityOrMetadataFailure(ValueError):
    """Raised when active peer count violates physical universe constraints (>99 or <0)."""
    pass


@dataclass(frozen=True)
class BreadthContextSnapshot:
    peer_constituent_count: int
    breadth_bucket: str  # "BREADTH_34_54", "BREADTH_55_79", "BREADTH_80_99", "INSUFFICIENT_BREADTH"
    invariant_passed: bool


class BreadthContextAnalyzer:
    """Classifies proxy breadth according to pre-registered historical boundaries."""

    MAX_UNIVERSE = 100
    MAX_PEER_COUNT = 99
    MIN_ANALYZABLE_PEERS = 34

    @classmethod
    def compute(cls, active_peers_count: int) -> BreadthContextSnapshot:
        """Computes breadth snapshot.
        
        Guards:
            - active_peers_count cannot exceed MAX_PEER_COUNT (99).
            - active_peers_count cannot be negative.
            - If active_peers_count < 34, labeled INSUFFICIENT_BREADTH (never silently dropped).
        """
        if active_peers_count > cls.MAX_PEER_COUNT:
            raise CausalityOrMetadataFailure(
                f"CAUSALITY_OR_METADATA_FAILURE: active_peers_count {active_peers_count} exceeds MAX_PEER_COUNT {cls.MAX_PEER_COUNT}"
            )
        if active_peers_count < 0:
            raise CausalityOrMetadataFailure(
                f"CAUSALITY_OR_METADATA_FAILURE: active_peers_count {active_peers_count} is negative"
            )

        if cls.MIN_ANALYZABLE_PEERS <= active_peers_count <= 54:
            bucket = "BREADTH_34_54"
        elif 55 <= active_peers_count <= 79:
            bucket = "BREADTH_55_79"
        elif 80 <= active_peers_count <= cls.MAX_PEER_COUNT:
            bucket = "BREADTH_80_99"
        else:
            bucket = "INSUFFICIENT_BREADTH"

        return BreadthContextSnapshot(
            peer_constituent_count=active_peers_count,
            breadth_bucket=bucket,
            invariant_passed=True,
        )
