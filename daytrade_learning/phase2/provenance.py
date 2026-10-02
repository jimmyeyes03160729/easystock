"""Phase 2A Parameter Provenance & Canonical Audit Registry.

Canonical Knowledge V2 is strictly sealed (commit 37c72e1).
Permitted Sources:
- Knowledge V1 canonical
- Knowledge V2 canonical
- EasyStock existing repo facts
- Official Taiwan market rules
- Research governance candidates

Audit Checks Enforced:
1. PARAM_PB_VOL_DECAY:
   - Author: Anna Coulling (A Complete Guide To Volume Price Analysis)
   - Source chapter: Chapter 7 (Low Volume Test / Support and Resistance).
   - Chapter 5 is strictly rejected.
2. AI-Quantized Research Parameter Grids:
   - [0.35, 0.45, 0.50] and [1.2, 1.5, 1.8] are flagged as AI_QUANTIZED.
   - Origin: "Knowledge V2 Research Parameter Candidate".
   - Never attributed to original authors.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProvenanceStatus(str, Enum):
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    AI_QUANTIZED = "AI_QUANTIZED"
    EASYSTOCK_FACT = "EASYSTOCK_FACT"
    TAIWAN_OFFICIAL_RULE = "TAIWAN_OFFICIAL_RULE"


@dataclass(frozen=True)
class ProvenanceRecord:
    parameter_id: str
    name: str
    value_or_grid: Any
    status: ProvenanceStatus
    author: str
    source_book_or_doc: str
    chapter_or_section: str
    notes: str


PARAM_PB_VOL_DECAY = ProvenanceRecord(
    parameter_id="PARAM_PB_VOL_DECAY",
    name="Pullback Low Volume Test Threshold",
    value_or_grid=0.50,
    status=ProvenanceStatus.SOURCE_VERIFIED,
    author="Anna Coulling",
    source_book_or_doc="A Complete Guide To Volume Price Analysis",
    chapter_or_section="Chapter 7",
    notes="Low volume test confirming lack of selling pressure; Chapter 7 verified.",
)

GRID_VOL_DECAY = ProvenanceRecord(
    parameter_id="GRID_PB_VOL_DECAY",
    name="Pullback Volume Decay Parameter Grid",
    value_or_grid=[0.35, 0.45, 0.50],
    status=ProvenanceStatus.AI_QUANTIZED,
    author="None (AI Quantized)",
    source_book_or_doc="Knowledge V2 Research Parameter Candidate",
    chapter_or_section="Parameter Grids Specification",
    notes="Discretized grid for sensitivity analysis; not explicitly stated in book text.",
)

GRID_EXTENSION = ProvenanceRecord(
    parameter_id="GRID_EXTENSION_RATIO",
    name="Price Extension Threshold Grid",
    value_or_grid=[1.2, 1.5, 1.8],
    status=ProvenanceStatus.AI_QUANTIZED,
    author="None (AI Quantized)",
    source_book_or_doc="Knowledge V2 Research Parameter Candidate",
    chapter_or_section="Parameter Grids Specification",
    notes="Discretized research grid for momentum extension stress testing.",
)

PHASE2_PROVENANCE_REGISTRY: dict[str, ProvenanceRecord] = {
    PARAM_PB_VOL_DECAY.parameter_id: PARAM_PB_VOL_DECAY,
    GRID_VOL_DECAY.parameter_id: GRID_VOL_DECAY,
    GRID_EXTENSION.parameter_id: GRID_EXTENSION,
}


def audit_parameter_provenance(record: ProvenanceRecord) -> None:
    """Validates parameter integrity and prevents false provenance claims."""
    if record.parameter_id == "PARAM_PB_VOL_DECAY":
        if "Chapter 5" in record.chapter_or_section:
            raise ValueError("Provenance audit failed: PARAM_PB_VOL_DECAY must point to Chapter 7, not Chapter 5.")
        if "Chapter 7" not in record.chapter_or_section:
            raise ValueError("Provenance audit failed: PARAM_PB_VOL_DECAY must point to Chapter 7.")

    if record.value_or_grid in ([0.35, 0.45, 0.50], [1.2, 1.5, 1.8]):
        if record.status != ProvenanceStatus.AI_QUANTIZED:
            raise ValueError(
                f"Provenance audit failed: Parameter grid {record.value_or_grid} must be flagged AI_QUANTIZED"
            )
        if "Knowledge V2 Research Parameter Candidate" not in record.source_book_or_doc:
            raise ValueError(
                f"Provenance audit failed: Origin must be Knowledge V2 Research Parameter Candidate"
            )
