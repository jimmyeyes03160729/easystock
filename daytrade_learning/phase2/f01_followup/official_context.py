"""Phase 2C F01 Follow-up: Official Benchmark Context Contract.

Provides an architectural interface for future replication against official index series
(TAIEX IX0001, TPEX OTC, Sector Indices).

Currently in IMPLEMENTATION_CONTRACT_ONLY status because official 1m series are DATA_UNAVAILABLE.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class OfficialContextSnapshot:
    signal_event_id: str
    series_name: str
    status: str  # "DATA_UNAVAILABLE", "DATA_READY"
    index_cum_return: Optional[float]
    agreement_with_f01_proxy: Optional[bool]
    notes: str


class OfficialMarketContextProvider(ABC):
    """Abstract interface for future benchmark replication."""

    @abstractmethod
    def get_market_context(self, signal_event_id: str, signal_time: datetime) -> OfficialContextSnapshot:
        """Retrieves official market context at signal timestamp."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> str:
        """Returns provider availability status."""
        raise NotImplementedError


class StandbyOfficialContextProvider(OfficialMarketContextProvider):
    """Default implementation for Phase 2C-A returning DATA_UNAVAILABLE without mocking."""

    def __init__(self, benchmark_name: str = "TWSE_TAIEX_IX0001"):
        self.benchmark_name = benchmark_name

    def get_market_context(self, signal_event_id: str, signal_time: datetime) -> OfficialContextSnapshot:
        return OfficialContextSnapshot(
            signal_event_id=signal_event_id,
            series_name=self.benchmark_name,
            status="DATA_UNAVAILABLE",
            index_cum_return=None,
            agreement_with_f01_proxy=None,
            notes="Official index series unavailable in historical store. Contract standby only.",
        )

    def get_status(self) -> str:
        return "DATA_UNAVAILABLE"
