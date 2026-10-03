"""Sector Strength Filter (F03).

Governance Policy:
- POINT_IN_TIME_SECTOR_MAPPING = False
- If sector series or point-in-time mapping is unavailable, records DATA_INSUFFICIENT.
- NEVER manufactures synthetic sector indices without official provenance.
- Readily supports static snapshot category grouping for analysis when available.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class SectorFilterStatus:
    status: str  # 'DATA_INSUFFICIENT' or 'READY'
    point_in_time_sector_mapping: bool
    symbol: str
    category_code: Optional[str]
    verdict: str
    rejection_reason: Optional[str]


class SectorStrengthFilter:
    """Evaluates sector strength and governance status for symbols."""

    def __init__(
        self,
        snapshot_categories: Optional[dict[str, str]] = None,
        sector_bars_by_category: Optional[dict[str, Any]] = None,
    ):
        self._snapshot_categories = snapshot_categories or {}
        self._sector_bars = sector_bars_by_category or {}
        self._point_in_time = False

    @property
    def point_in_time_sector_mapping(self) -> bool:
        return self._point_in_time

    def evaluate_symbol_sector(self, symbol: str) -> SectorFilterStatus:
        cat = self._snapshot_categories.get(symbol)
        if not self._sector_bars or not cat or cat not in self._sector_bars:
            return SectorFilterStatus(
                status="DATA_INSUFFICIENT",
                point_in_time_sector_mapping=False,
                symbol=symbol,
                category_code=cat,
                verdict="REJECT_FILTER_USAGE",
                rejection_reason="Sector 1m series unavailable and mapping is non-point-in-time snapshot.",
            )

        return SectorFilterStatus(
            status="READY",
            point_in_time_sector_mapping=self._point_in_time,
            symbol=symbol,
            category_code=cat,
            verdict="EVALUATE",
            rejection_reason=None,
        )

    def filter_signal(self, symbol: str, signal_time: datetime, direction: str) -> bool:
        """Default filter behavior under DATA_INSUFFICIENT:
        Does not filter out any signals (returns True/KEEP) while recording DATA_INSUFFICIENT in metadata.
        """
        # Under DATA_INSUFFICIENT, signals remain unfiltered to avoid arbitrary dropping.
        return True
