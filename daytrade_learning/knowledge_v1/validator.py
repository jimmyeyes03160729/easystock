"""Canonical Parameter Grid Validator for Knowledge V1 Research.

Enforces strict provenance synchronization against:
docs/daytrade_knowledge_v1/research_parameter_grids.yaml

Rules:
1. Every GridParameter used in candidate evaluators MUST exist in the canonical YAML.
2. parameter_name must match the canonical specification exactly.
3. seed_value and test values must be present in the canonical allowable values list.
4. status (e.g. AI_QUANTIZED) must match canonical specification.
5. Inconsistencies FAIL CLOSED (raise ValueError). No silent fallback, no synthetic IDs.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
import yaml

# Path to canonical research parameter grids
CANONICAL_GRIDS_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "daytrade_knowledge_v1" / "research_parameter_grids.yaml"


class CanonicalGridValidator:
    """Validates runtime GridParameter definitions against canonical YAML specifications."""

    _cached_grids: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def load_canonical_grids(cls, yaml_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
        """Loads canonical grids from YAML, caching in-memory."""
        if cls._cached_grids is not None and yaml_path is None:
            return cls._cached_grids

        target_path = yaml_path or CANONICAL_GRIDS_PATH
        if not target_path.exists():
            raise FileNotFoundError(f"Canonical parameter grid file not found at: {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        grids = {}
        for entry in data.get("grids", []):
            gid = entry.get("grid_id")
            if gid:
                grids[gid] = entry

        if yaml_path is None:
            cls._cached_grids = grids
        return grids

    @classmethod
    def normalize_grid_id(cls, raw_grid_id: str) -> str:
        """Normalizes 'RESEARCH_GRID_G01' or 'G01' to canonical 'G01' format."""
        if raw_grid_id.startswith("RESEARCH_GRID_"):
            return raw_grid_id.replace("RESEARCH_GRID_", "")
        return raw_grid_id

    @classmethod
    def validate_parameter(
        cls,
        grid_id: str,
        parameter_name: str,
        value: float,
        status: Optional[str] = None,
        yaml_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Validates a strategy threshold against canonical specification.
        Raises ValueError if invalid (Fail-Closed).
        """
        canonical_grids = cls.load_canonical_grids(yaml_path=yaml_path)
        norm_gid = cls.normalize_grid_id(grid_id)

        # 1. Check existence
        if norm_gid not in canonical_grids:
            raise ValueError(
                f"[CANONICAL_GRID_VALIDATION_FAILED] Grid ID '{grid_id}' (normalized: '{norm_gid}') "
                f"does NOT exist in canonical research_parameter_grids.yaml. Available IDs: {sorted(canonical_grids.keys())}"
            )

        canonical_entry = canonical_grids[norm_gid]

        # 2. Check parameter_name
        canonical_pname = canonical_entry.get("parameter")
        if canonical_pname != parameter_name:
            raise ValueError(
                f"[CANONICAL_GRID_VALIDATION_FAILED] Grid ID '{grid_id}' parameter name mismatch! "
                f"Expected canonical '{canonical_pname}', but received '{parameter_name}'."
            )

        # 3. Check allowed values
        canonical_values = canonical_entry.get("values", [])
        # Floating point comparison with tolerance
        is_allowed = any(math.isclose(float(v), float(value), abs_tol=1e-6) for v in canonical_values)
        if not is_allowed:
            raise ValueError(
                f"[CANONICAL_GRID_VALIDATION_FAILED] Value {value} is NOT in canonical allowed values "
                f"for Grid '{grid_id}' ({parameter_name}). Allowed: {canonical_values}"
            )

        # 4. Check status if provided
        if status is not None:
            canonical_status = canonical_entry.get("status")
            if canonical_status and canonical_status != status:
                raise ValueError(
                    f"[CANONICAL_GRID_VALIDATION_FAILED] Status mismatch for Grid '{grid_id}'! "
                    f"Canonical is '{canonical_status}', but received '{status}'."
                )

        return canonical_entry
