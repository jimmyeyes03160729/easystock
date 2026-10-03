"""Unit tests for EasyStock OOS Consumption Ledger, Central Dataset Registry,

and exposure accounting invariants.
"""

from __future__ import annotations

import copy
import datetime
import os
from typing import Any, Dict

import pytest
import yaml

from daytrade_learning.research_governance.validate_oos_consumption import (
    DatasetRegistry,
    OOSConsumptionValidator,
    compute_slice_consumption_stats,
    validate_all,
)

REGISTRY_PATH = "docs/research_governance/DATASET_REGISTRY_v1.yaml"
LEDGERS_DIR = "docs/research_governance/oos_consumption"


@pytest.fixture
def central_registry() -> DatasetRegistry:
    return DatasetRegistry(REGISTRY_PATH)


@pytest.fixture
def validator(central_registry: DatasetRegistry) -> OOSConsumptionValidator:
    return OOSConsumptionValidator(central_registry)


def test_all_consumption_ledger_files_pass_validation():
    """Verify that all actual on-disk ledger files in oos_consumption pass validation."""
    passed, results = validate_all(REGISTRY_PATH, LEDGERS_DIR)
    for filename, (file_passed, errors) in results.items():
        assert file_passed, f"Validation failed for {filename}: {errors}"
    assert passed is True


def test_same_dataset_overlap_is_consumed(validator: OOSConsumptionValidator, central_registry: DatasetRegistry):
    """An event on the same dataset overlapping an exposed slice cannot claim pristine_before=true."""
    prior = [
        {
            "consumption_id": "CNS_PRIOR_01",
            "trial_id": "TRIAL_A",
            "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
            "dataset_family_id": "TWSE_EQUITY_INTRADAY",
            "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
            "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "role": "OOS",
            "exposure": {
                "performance_seen": True,
                "labels_seen": False,
                "aggregate_metrics_seen": True,
                "subgroup_results_seen": False,
                "parameter_selection_influenced": False,
                "human_seen": True,
                "ai_seen": True,
            },
            "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
            "dimensions_seen": ["net_return"],
            "consumed_at": "2026-01-01T00:00:00+08:00",
            "record_type": "PREREGISTERED_CONSUMPTION",
            "source_artifact": "report.md",
            "source_commit": "abc1234",
            "governance": {
                "pristine_before": True,
                "pristine_after": False,
                "independent_confirmation_eligible_after": False,
            },
        }
    ]

    new_event = {
        "consumption_id": "CNS_NEW_02",
        "trial_id": "TRIAL_B",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-03-01", "end_date": "2024-09-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
        "dimensions_seen": ["win_rate"],
        "consumed_at": "2026-02-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "report2.md",
        "source_commit": "def5678",
        "governance": {
            "pristine_before": True,  # INVALID: overlaps with 2024-01-01 ~ 2024-06-30
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }

    seen_ids = {"CNS_PRIOR_01"}
    errors = validator.validate_single_event(new_event, seen_ids, prior)
    assert any("Overlap violation" in e and "pristine_before=true" in e for e in errors)


def test_same_lineage_renamed_dataset_is_consumed(validator: OOSConsumptionValidator):
    """Renaming dataset_id (alias representation) with same lineage still inherits prior exposure."""
    prior = [
        {
            "consumption_id": "CNS_PRIOR_01",
            "trial_id": "TRIAL_A",
            "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
            "dataset_family_id": "TWSE_EQUITY_INTRADAY",
            "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
            "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
            "role": "OOS",
            "exposure": {
                "performance_seen": True,
                "labels_seen": False,
                "aggregate_metrics_seen": True,
                "subgroup_results_seen": False,
                "parameter_selection_influenced": False,
                "human_seen": True,
                "ai_seen": True,
            },
            "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
            "dimensions_seen": ["net_return"],
            "consumed_at": "2026-01-01T00:00:00+08:00",
            "record_type": "PREREGISTERED_CONSUMPTION",
            "source_artifact": "report.md",
            "source_commit": "abc1234",
            "governance": {
                "pristine_before": True,
                "pristine_after": False,
                "independent_confirmation_eligible_after": False,
            },
        }
    ]

    # Event uses alias dataset: 2026-09-10_FROZEN_100_STOCK_POOL
    new_event = {
        "consumption_id": "CNS_NEW_ALIAS",
        "trial_id": "TRIAL_B",
        "dataset_id": "2026-09-10_FROZEN_100_STOCK_POOL",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-04-01", "end_date": "2024-08-01"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
        "dimensions_seen": ["profit_factor"],
        "consumed_at": "2026-02-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "report_alias.md",
        "source_commit": "def5678",
        "governance": {
            "pristine_before": True,  # INVALID: shares LINEAGE_SHIOAJI_TICKS_CANONICAL_V1 and overlaps
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }

    seen_ids = {"CNS_PRIOR_01"}
    errors = validator.validate_single_event(new_event, seen_ids, prior)
    assert any("Overlap violation" in e for e in errors)


def test_derived_dataset_inherits_parent_exposure(validator: OOSConsumptionValidator):
    """Derived dataset (TWSE_MARKET_CONTEXT_F01) inherits exposure from parent (PHASE2_HISTORICAL_2023_2026_10_02)."""
    prior = [
        {
            "consumption_id": "CNS_PARENT_EXPOSURE",
            "trial_id": "TRIAL_PARENT",
            "dataset_id": "PHASE2_HISTORICAL_2023_2026_10_02",
            "dataset_family_id": "TWSE_EQUITY_INTRADAY",
            "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
            "slice": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
            "role": "TRAIN",
            "exposure": {
                "performance_seen": True,
                "labels_seen": True,
                "aggregate_metrics_seen": True,
                "subgroup_results_seen": True,
                "parameter_selection_influenced": True,
                "human_seen": True,
                "ai_seen": True,
            },
            "exposure_level": "LEVEL_4_PARAMETER_SELECTION_USED",
            "dimensions_seen": ["trend_filter_search"],
            "consumed_at": "2026-01-01T00:00:00+08:00",
            "record_type": "PREREGISTERED_CONSUMPTION",
            "source_artifact": "parent_study.md",
            "source_commit": "parent1",
            "governance": {
                "pristine_before": False,
                "pristine_after": False,
                "independent_confirmation_eligible_after": False,
            },
        }
    ]

    # Derived feature set trying to claim pristine_before on overlapping range
    derived_event = {
        "consumption_id": "CNS_DERIVED_EVENT",
        "trial_id": "TRIAL_DERIVED",
        "dataset_id": "TWSE_MARKET_CONTEXT_F01",
        "dataset_family_id": "TWSE_MARKET_CONTEXT",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-06-01", "end_date": "2024-10-31"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
        "dimensions_seen": ["tx_trend_delta"],
        "consumed_at": "2026-02-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "derived_study.md",
        "source_commit": "derived1",
        "governance": {
            "pristine_before": True,  # INVALID: parent dataset was exposed on this slice
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }

    seen_ids = {"CNS_PARENT_EXPOSURE"}
    errors = validator.validate_single_event(derived_event, seen_ids, prior)
    assert any("Overlap violation" in e for e in errors)


def test_unrelated_trial_still_burns_same_slice(validator: OOSConsumptionValidator):
    """Trial B has no parent relationship with Trial A, but cannot claim pristine for slice burned by Trial A."""
    prior = [
        {
            "consumption_id": "CNS_TRIAL_A",
            "trial_id": "TRIAL_A_UNRELATED",
            "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
            "dataset_family_id": "TWSE_EQUITY_INTRADAY",
            "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
            "slice": {"start_date": "2024-01-01", "end_date": "2024-12-31"},
            "role": "OOS",
            "exposure": {
                "performance_seen": True,
                "labels_seen": False,
                "aggregate_metrics_seen": True,
                "subgroup_results_seen": False,
                "parameter_selection_influenced": False,
                "human_seen": True,
                "ai_seen": True,
            },
            "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
            "dimensions_seen": ["metric_a"],
            "consumed_at": "2026-01-01T00:00:00+08:00",
            "record_type": "PREREGISTERED_CONSUMPTION",
            "source_artifact": "a.md",
            "source_commit": "aaa",
            "governance": {
                "pristine_before": True,
                "pristine_after": False,
                "independent_confirmation_eligible_after": False,
            },
        }
    ]

    event_b = {
        "consumption_id": "CNS_TRIAL_B",
        "trial_id": "TRIAL_B_UNRELATED",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-05-01", "end_date": "2024-09-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
        "dimensions_seen": ["metric_b"],
        "consumed_at": "2026-02-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "b.md",
        "source_commit": "bbb",
        "governance": {
            "pristine_before": True,  # INVALID: global research program level exposure applies
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }

    seen_ids = {"CNS_TRIAL_A"}
    errors = validator.validate_single_event(event_b, seen_ids, prior)
    assert any("Overlap violation" in e for e in errors)


def test_nonoverlapping_future_slice_remains_pristine(validator: OOSConsumptionValidator):
    """A slice strictly after all previous exposures can be pristine_before=true."""
    prior = [
        {
            "consumption_id": "CNS_PRIOR_HISTORICAL",
            "trial_id": "TRIAL_P2C",
            "dataset_id": "PHASE2_HISTORICAL_2023_2026_10_02",
            "dataset_family_id": "TWSE_EQUITY_INTRADAY",
            "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
            "slice": {"start_date": "2023-09-27", "end_date": "2026-10-02"},
            "role": "DESCRIPTIVE",
            "exposure": {
                "performance_seen": True,
                "labels_seen": False,
                "aggregate_metrics_seen": True,
                "subgroup_results_seen": True,
                "parameter_selection_influenced": False,
                "human_seen": True,
                "ai_seen": True,
            },
            "exposure_level": "LEVEL_3_SUBGROUP_RESULTS_SEEN",
            "dimensions_seen": ["H01"],
            "consumed_at": "2026-10-03T11:00:00+08:00",
            "record_type": "LEGACY_BACKFILL",
            "recorded_after_exposure": True,
            "source_artifact": "report.md",
            "source_commit": "ccc",
            "governance": {
                "pristine_before": False,
                "pristine_after": False,
                "independent_confirmation_eligible_after": False,
            },
        }
    ]

    # Future slice strictly starting 2026-10-05
    future_event = {
        "consumption_id": "CNS_FUTURE_TEST",
        "trial_id": "TRIAL_FUTURE",
        "dataset_id": "PHASE2C_FUTURE_CONFIRMATION_60D",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2026-10-05", "end_date": None, "slice_definition": "first_60_days"},
        "role": "CONFIRMATION",
        "exposure": {
            "performance_seen": False,
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": False,
            "ai_seen": False,
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": None,
        "record_type": "CONFIRMATION_RESERVATION",
        "recorded_after_exposure": False,
        "source_artifact": "contract.yaml",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,
            "independent_confirmation_completed": False,
        },
    }

    seen_ids = {"CNS_PRIOR_HISTORICAL"}
    errors = validator.validate_single_event(future_event, seen_ids, prior)
    assert len(errors) == 0


def test_aggregate_metrics_burn_level2(validator: OOSConsumptionValidator):
    """aggregate_metrics_seen=true cannot declare exposure_level < LEVEL_2."""
    event = {
        "consumption_id": "CNS_AGG_LEVEL_TEST",
        "trial_id": "TRIAL_TEST",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,  # Aggregate seen!
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_1_FEATURE_STRUCTURE_SEEN",  # VIOLATION: must be at least LEVEL_2
        "dimensions_seen": ["aggregate_net_return"],
        "consumed_at": "2026-01-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "rep.md",
        "source_commit": "c1",
        "governance": {
            "pristine_before": True,
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("aggregate_metrics_seen=true requires at least LEVEL_2_AGGREGATE_METRICS_SEEN" in e for e in errors)


def test_subgroup_results_burn_level3(validator: OOSConsumptionValidator):
    """subgroup_results_seen=true or subgroup dimensions cannot declare exposure_level < LEVEL_3."""
    event = {
        "consumption_id": "CNS_SUBGROUP_TEST",
        "trial_id": "TRIAL_TEST",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": True,  # Subgroup seen!
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",  # VIOLATION: must be at least LEVEL_3
        "dimensions_seen": ["volatility_strata"],
        "consumed_at": "2026-01-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "rep.md",
        "source_commit": "c1",
        "governance": {
            "pristine_before": True,
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("subgroup_results_seen=true or subgroup dimensions seen requires at least LEVEL_3" in e for e in errors)


def test_parameter_selection_burn_level4(validator: OOSConsumptionValidator):
    """parameter_selection_influenced=true cannot declare exposure_level < LEVEL_4."""
    event = {
        "consumption_id": "CNS_PARAM_TEST",
        "trial_id": "TRIAL_TEST",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
        "role": "TRAIN",
        "exposure": {
            "performance_seen": True,
            "labels_seen": True,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": True,
            "parameter_selection_influenced": True,  # Param selection influenced!
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_3_SUBGROUP_RESULTS_SEEN",  # VIOLATION: must be at least LEVEL_4
        "dimensions_seen": ["threshold_search"],
        "consumed_at": "2026-01-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "rep.md",
        "source_commit": "c1",
        "governance": {
            "pristine_before": True,
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("parameter_selection_influenced=true requires at least LEVEL_4" in e for e in errors)


def test_repeated_research_burn_level5(validator: OOSConsumptionValidator):
    """LEVEL_5 is assigned when the same slice is repeatedly exposed across multiple research stages."""
    event = {
        "consumption_id": "CNS_LEVEL5_TEST",
        "trial_id": "TRIAL_P2C_F01",
        "dataset_id": "PHASE2_HISTORICAL_2023_2026_10_02",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2023-09-27", "end_date": "2026-10-02"},
        "role": "DESCRIPTIVE",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": True,
            "parameter_selection_influenced": False,
            "research_direction_influenced": True,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_5_REPEATED_RESEARCH_EXPOSED",
        "dimensions_seen": ["F01 overall result", "H01 trend-direction buckets"],
        "consumed_at": "2026-10-03T11:00:00+08:00",
        "record_type": "LEGACY_BACKFILL",
        "recorded_after_exposure": True,
        "source_artifact": "p2c_report.md",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": False,
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert len(errors) == 0


def test_reserved_future_has_zero_outcome_exposure(validator: OOSConsumptionValidator):
    """RESERVED_UNTOUCHED reservation cannot contain any performance/outcome exposure."""
    event = {
        "consumption_id": "CNS_BAD_RESERVATION",
        "trial_id": "TRIAL_P2C_F01",
        "dataset_id": "PHASE2C_FUTURE_CONFIRMATION_60D",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2026-10-05", "end_date": None},
        "role": "CONFIRMATION",
        "exposure": {
            "performance_seen": True,  # VIOLATION!
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": False,
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": "2026-10-03T23:00:00+08:00",
        "record_type": "CONFIRMATION_RESERVATION",
        "recorded_after_exposure": False,
        "source_artifact": "contract.yaml",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("RESERVED_UNTOUCHED confirmation reservation cannot contain performance/outcome exposure" in e for e in errors)


def test_reserved_future_cannot_be_completed(validator: OOSConsumptionValidator):
    """RESERVED_UNTOUCHED reservation cannot declare independent_confirmation_completed: true."""
    event = {
        "consumption_id": "CNS_PREMATURE_COMPLETE",
        "trial_id": "TRIAL_P2C_F01",
        "dataset_id": "PHASE2C_FUTURE_CONFIRMATION_60D",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2026-10-05", "end_date": None},
        "role": "CONFIRMATION",
        "exposure": {
            "performance_seen": False,
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": False,
            "ai_seen": False,
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": "2026-10-03T23:00:00+08:00",
        "record_type": "CONFIRMATION_RESERVATION",
        "recorded_after_exposure": False,
        "source_artifact": "contract.yaml",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,
            "independent_confirmation_completed": True,  # VIOLATION: cannot be completed while unreleased
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("cannot be marked completed" in e for e in errors)


def test_unknown_lineage_not_auto_pristine(validator: OOSConsumptionValidator, central_registry: DatasetRegistry):
    """LINEAGE_UNKNOWN cannot automatically claim pristine independent confirmation."""
    # Temporarily register a dummy dataset with LINEAGE_UNKNOWN
    central_registry.datasets["UNKNOWN_DS"] = {
        "dataset_id": "UNKNOWN_DS",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_UNKNOWN",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
    }

    event = {
        "consumption_id": "CNS_UNKNOWN_LINEAGE",
        "trial_id": "TRIAL_TEST",
        "dataset_id": "UNKNOWN_DS",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_UNKNOWN",
        "slice": {"start_date": "2026-01-01", "end_date": "2026-06-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": False,
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": False,
            "ai_seen": False,
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": "2026-01-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "rep.md",
        "source_commit": "c1",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,  # VIOLATION: unknown lineage cannot auto-claim
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("Unknown lineage (LINEAGE_UNKNOWN) cannot automatically claim pristine" in e for e in errors)


def test_registry_is_authoritative_over_trial_claim(validator: OOSConsumptionValidator):
    """A consumption event cannot invent a fake dataset_lineage_id or family_id different from the registry."""
    event = {
        "consumption_id": "CNS_FAKER_EVENT",
        "trial_id": "TRIAL_TEST",
        "dataset_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
        "dataset_family_id": "FAKE_FAMILY",  # VIOLATION: registry has TWSE_EQUITY_INTRADAY
        "dataset_lineage_id": "FAKE_LINEAGE",  # VIOLATION: registry has LINEAGE_SHIOAJI_TICKS_CANONICAL_V1
        "slice": {"start_date": "2024-01-01", "end_date": "2024-06-30"},
        "role": "OOS",
        "exposure": {
            "performance_seen": True,
            "labels_seen": False,
            "aggregate_metrics_seen": True,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": True,
            "ai_seen": True,
        },
        "exposure_level": "LEVEL_2_AGGREGATE_METRICS_SEEN",
        "dimensions_seen": ["net_return"],
        "consumed_at": "2026-01-01T00:00:00+08:00",
        "record_type": "PREREGISTERED_CONSUMPTION",
        "source_artifact": "rep.md",
        "source_commit": "c1",
        "governance": {
            "pristine_before": True,
            "pristine_after": False,
            "independent_confirmation_eligible_after": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("dataset_family_id mismatch" in e for e in errors)
    assert any("dataset_lineage_id mismatch" in e for e in errors)


def test_phase2c_eight_dimensions_are_consumed(central_registry: DatasetRegistry):
    """Verify Phase 2C backfill in PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml explicitly records all 8 dimensions."""
    backfill_file = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(backfill_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    p2c_events = [
        ev for ev in data.get("consumption_events", [])
        if ev.get("trial_id") == "TRIAL_P2C_F01_MECHANISM_FOLLOWUP"
    ]
    assert len(p2c_events) >= 1
    p2c_ev = p2c_events[0]

    dims = p2c_ev.get("dimensions_seen", [])
    expected_8 = [
        "F01 overall result",
        "H01 trend-direction buckets",
        "H02 volatility buckets",
        "H03 opening 15m/30m buckets",
        "H04 time-of-day",
        "H05 breadth",
        "H06 LONG/SHORT/candidate breakdown",
        "H07 year/failure-regime descriptive results",
    ]
    for exp_dim in expected_8:
        assert exp_dim in dims, f"Missing expected dimension in Phase 2C backfill: {exp_dim}"

    # Also compute slice stats
    stats = compute_slice_consumption_stats(
        central_registry,
        data.get("consumption_events", []),
        "PHASE2_HISTORICAL_2023_2026_10_02",
        datetime.date(2023, 9, 27),
        datetime.date(2026, 10, 2),
    )
    assert stats["is_pristine"] is False
    assert stats["distinct_dimension_count"] >= 8
    assert "F01 overall result" in stats["distinct_dimensions"]


def test_future_60d_reservation_is_level0():
    """Verify PHASE2C_FUTURE_CONFIRMATION_RESERVATION.yaml is strictly LEVEL_0_UNTOUCHED."""
    res_file = os.path.join(LEDGERS_DIR, "PHASE2C_FUTURE_CONFIRMATION_RESERVATION.yaml")
    with open(res_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    events = data.get("consumption_events", [])
    assert len(events) == 1
    ev = events[0]
    assert ev.get("role") == "CONFIRMATION"
    assert ev.get("exposure_level") == "LEVEL_0_UNTOUCHED"

    exp = ev.get("exposure", {})
    assert exp.get("performance_seen") is False
    assert exp.get("labels_seen") is False
    assert exp.get("aggregate_metrics_seen") is False
    assert exp.get("subgroup_results_seen") is False
    assert exp.get("human_seen") is False
    assert exp.get("ai_seen") is False

    gov = ev.get("governance", {})
    assert gov.get("pristine_before") is True
    assert gov.get("pristine_after") is True
    assert gov.get("independent_confirmation_eligible_after") is True
    assert gov.get("independent_confirmation_intended") is True
    assert gov.get("independent_confirmation_completed") is False


def test_batch1_full_history_is_consumed_through_20261002():
    """Verify Phase 2B Batch 1 full historical event covers 2023-09-04 to 2026-10-02 at LEVEL_3."""
    backfill_file = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(backfill_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    b1_full = [
        ev for ev in data.get("consumption_events", [])
        if ev.get("consumption_id") == "CNS_P2B_BATCH1_FULL_HISTORICAL_EVALUATION"
    ]
    assert len(b1_full) == 1
    ev = b1_full[0]
    assert ev.get("trial_id") == "TRIAL_P2B_BATCH1_CANDIDATE_SEARCH"
    assert ev.get("slice", {}).get("start_date") == "2023-09-04"
    assert ev.get("slice", {}).get("end_date") == "2026-10-02"
    assert ev.get("exposure_level") == "LEVEL_3_SUBGROUP_RESULTS_SEEN"
    dims = ev.get("dimensions_seen", [])
    for d in ["aggregate", "candidate", "year", "time-of-day", "completeness", "exit-policy", "slippage", "performance metrics"]:
        assert d in dims


def test_batch1_wfa_windows_match_sealed_report():
    """Verify Phase 2B Batch 1 WFA folds exactly match the 5 Train and 5 OOS windows from sealed report."""
    backfill_file = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(backfill_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    events_by_id = {ev.get("consumption_id"): ev for ev in data.get("consumption_events", [])}

    expected_folds = [
        ("CNS_P2B_BATCH1_WFA_FOLD1_TRAIN", "2023-09-27", "2025-01-03", "TRAIN", "LEVEL_4_PARAMETER_SELECTION_USED"),
        ("CNS_P2B_BATCH1_WFA_FOLD1_OOS",   "2025-01-08", "2025-06-24", "OOS",   "LEVEL_3_SUBGROUP_RESULTS_SEEN"),
        ("CNS_P2B_BATCH1_WFA_FOLD2_TRAIN", "2024-03-06", "2025-06-20", "TRAIN", "LEVEL_4_PARAMETER_SELECTION_USED"),
        ("CNS_P2B_BATCH1_WFA_FOLD2_OOS",   "2025-06-25", "2025-11-20", "OOS",   "LEVEL_3_SUBGROUP_RESULTS_SEEN"),
        ("CNS_P2B_BATCH1_WFA_FOLD3_TRAIN", "2024-08-06", "2025-11-18", "TRAIN", "LEVEL_4_PARAMETER_SELECTION_USED"),
        ("CNS_P2B_BATCH1_WFA_FOLD3_OOS",   "2025-11-21", "2026-04-30", "OOS",   "LEVEL_3_SUBGROUP_RESULTS_SEEN"),
        ("CNS_P2B_BATCH1_WFA_FOLD4_TRAIN", "2025-01-06", "2026-04-28", "TRAIN", "LEVEL_4_PARAMETER_SELECTION_USED"),
        ("CNS_P2B_BATCH1_WFA_FOLD4_OOS",   "2026-05-04", "2026-09-29", "OOS",   "LEVEL_3_SUBGROUP_RESULTS_SEEN"),
        ("CNS_P2B_BATCH1_WFA_FOLD5_TRAIN", "2025-06-23", "2026-09-23", "TRAIN", "LEVEL_4_PARAMETER_SELECTION_USED"),
        ("CNS_P2B_BATCH1_WFA_FOLD5_OOS",   "2026-09-30", "2026-10-02", "OOS",   "LEVEL_3_SUBGROUP_RESULTS_SEEN"),
    ]

    for cid, exp_start, exp_end, exp_role, exp_lvl in expected_folds:
        assert cid in events_by_id, f"Missing WFA event: {cid}"
        ev = events_by_id[cid]
        assert ev.get("slice", {}).get("start_date") == exp_start
        assert ev.get("slice", {}).get("end_date") == exp_end
        assert ev.get("role") == exp_role
        assert ev.get("exposure_level") == exp_lvl


def test_batch2_full_history_is_consumed_through_20261002():
    """Verify Phase 2B Batch 2 full historical event covers 2023-09-04 to 2026-10-02 at LEVEL_4."""
    backfill_file = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(backfill_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    b2_events = [
        ev for ev in data.get("consumption_events", [])
        if ev.get("consumption_id") == "CNS_P2B_BATCH2_FILTER_EVALUATION"
    ]
    assert len(b2_events) == 1
    ev = b2_events[0]
    assert ev.get("slice", {}).get("start_date") == "2023-09-04"
    assert ev.get("slice", {}).get("end_date") == "2026-10-02"
    assert ev.get("exposure_level") == "LEVEL_4_PARAMETER_SELECTION_USED"
    assert ev.get("exposure", {}).get("research_direction_influenced") is True


def test_phase2a_unknown_dates_are_not_invented():
    """Verify Phase 2A does not fabricate dates; declares historical_exposure_range UNKNOWN and start_date null."""
    backfill_file = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(backfill_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    p2a_events = [
        ev for ev in data.get("consumption_events", [])
        if ev.get("consumption_id") == "CNS_P2A_FOUNDATION_EXPLORATION"
    ]
    assert len(p2a_events) == 1
    ev = p2a_events[0]
    sl = ev.get("slice", {})
    assert sl.get("start_date") is None
    assert sl.get("end_date") is None
    assert sl.get("historical_exposure_range") == "UNKNOWN"
    assert sl.get("historical_information_incomplete") is True


def test_level0_admin_metadata_does_not_burn_holdout(validator: OOSConsumptionValidator):
    """Inspecting only whitelisted administrative metadata maintains LEVEL_0_UNTOUCHED and pristine status."""
    event = {
        "consumption_id": "CNS_ADMIN_META_CHECK",
        "trial_id": "TRIAL_P2C_F01",
        "dataset_id": "PHASE2C_FUTURE_CONFIRMATION_60D",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2026-10-05", "end_date": None},
        "role": "CONFIRMATION",
        "exposure": {
            "performance_seen": False,
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": False,
            "ai_seen": False,
            "admin_metadata_inspected": [
                "file_existence",
                "ingestion_success",
                "schema_version",
                "checksum",
                "trading_calendar_membership",
            ],
            "market_data_inspected": [],
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": None,
        "record_type": "CONFIRMATION_RESERVATION",
        "recorded_after_exposure": False,
        "source_artifact": "contract.yaml",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,
            "independent_confirmation_completed": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert len(errors) == 0


def test_level0_market_value_inspection_burns_holdout(validator: OOSConsumptionValidator):
    """Inspecting prohibited market data values or statistics burns holdout and fails LEVEL_0 validation."""
    event = {
        "consumption_id": "CNS_PROHIBITED_MARKET_CHECK",
        "trial_id": "TRIAL_P2C_F01",
        "dataset_id": "PHASE2C_FUTURE_CONFIRMATION_60D",
        "dataset_family_id": "TWSE_EQUITY_INTRADAY",
        "dataset_lineage_id": "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1",
        "slice": {"start_date": "2026-10-05", "end_date": None},
        "role": "CONFIRMATION",
        "exposure": {
            "performance_seen": False,
            "labels_seen": False,
            "aggregate_metrics_seen": False,
            "subgroup_results_seen": False,
            "parameter_selection_influenced": False,
            "human_seen": False,
            "ai_seen": False,
            "admin_metadata_inspected": ["file_existence"],
            "market_data_inspected": ["ohlcv_values", "tick_count"],
        },
        "exposure_level": "LEVEL_0_UNTOUCHED",
        "dimensions_seen": [],
        "consumed_at": None,
        "record_type": "CONFIRMATION_RESERVATION",
        "recorded_after_exposure": False,
        "source_artifact": "contract.yaml",
        "source_commit": "8ceb6a94",
        "governance": {
            "pristine_before": True,
            "pristine_after": True,
            "independent_confirmation_eligible_after": True,
            "independent_confirmation_completed": False,
        },
    }
    errors = validator.validate_single_event(event, set(), [])
    assert any("market data inspection" in e and "burns holdout" in e for e in errors)


def test_future_reservation_not_counted_as_consumption(central_registry: DatasetRegistry):
    """Future reservation is NOT a consumption event.

    It contributes zero to total_consumption_events, confirmation_consumption_count,
    human_exposure_count, and ai_exposure_count.
    """
    res_path = os.path.join(LEDGERS_DIR, "PHASE2C_FUTURE_CONFIRMATION_RESERVATION.yaml")
    with open(res_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    events = data.get("consumption_events", [])
    assert len(events) == 1
    ev = events[0]
    assert ev.get("record_type") == "RESERVATION"
    assert ev.get("consumed_at") is None
    assert ev.get("exposure_level") == "LEVEL_0_UNTOUCHED"

    stats = compute_slice_consumption_stats(
        registry=central_registry,
        consumption_events=events,
        dataset_id="PHASE2C_FUTURE_CONFIRMATION_60D",
        start_date=datetime.date(2026, 10, 5),
        end_date=None,
    )
    assert stats["total_consumption_events"] == 0
    assert stats["confirmation_consumption_count"] == 0
    assert stats["human_exposure_count"] == 0
    assert stats["ai_exposure_count"] == 0
    assert stats["is_pristine"] is True
    assert stats["max_exposure_level"] == "LEVEL_0_UNTOUCHED"


def test_batch2_f01_followup_is_candidate_selection_not_parameter_tuning():
    """Verify that Phase 2B Batch 2 F01 selection reflects candidate selection rather than parameter tuning."""
    bf_path = os.path.join(LEDGERS_DIR, "PHASE2_HISTORICAL_LEGACY_BACKFILL.yaml")
    with open(bf_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    events = data.get("consumption_events", [])
    b2_events = [e for e in events if e.get("consumption_id") == "CNS_P2B_BATCH2_FILTER_EVALUATION"]
    assert len(b2_events) == 1
    b2 = b2_events[0]

    exposure = b2.get("exposure", {})
    assert exposure.get("parameter_selection_influenced") is False
    assert exposure.get("candidate_selection_influenced") is True
    assert exposure.get("research_direction_influenced") is True
    assert b2.get("exposure_level") == "LEVEL_4_PARAMETER_SELECTION_USED"


