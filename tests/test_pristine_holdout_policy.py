"""Unit tests for EasyStock Pristine Holdout Policy, Blinded Collection,

and One-Shot Unseal Governance.
"""

from __future__ import annotations

import copy
import datetime
import os
from typing import Any, Dict

import pytest
import yaml

from daytrade_learning.research_governance.validate_oos_consumption import DatasetRegistry
from daytrade_learning.research_governance.validate_pristine_holdout import (
    PristineHoldoutValidator,
    detect_post_unseal_modifications,
    validate_all_holdouts,
    validate_atomic_unseal_transition,
)


REGISTRY_PATH = "docs/research_governance/DATASET_REGISTRY_v1.yaml"
HOLDOUTS_DIR = "docs/research_governance/holdouts"


def make_valid_lifecycle_history(target_state: str) -> list[dict[str, Any]]:
    sequence = [
        "RESERVED_UNTOUCHED",
        "COLLECTING_BLINDED",
        "READY_TO_UNSEAL",
        "UNSEALED_FOR_CONFIRMATION",
        "CONFIRMATION_COMPLETED",
        "CONSUMED",
    ]
    if target_state not in sequence:
        return [{"state": target_state, "timestamp": "2026-10-04T00:00:00+08:00"}]
    idx = sequence.index(target_state)
    return [
        {"state": s, "timestamp": f"2026-10-04T0{i}:00:00+08:00"}
        for i, s in enumerate(sequence[: idx + 1])
    ]



@pytest.fixture
def central_registry() -> DatasetRegistry:
    return DatasetRegistry(REGISTRY_PATH)


@pytest.fixture
def validator(central_registry: DatasetRegistry) -> PristineHoldoutValidator:
    return PristineHoldoutValidator(central_registry)


@pytest.fixture
def valid_holdout_base() -> Dict[str, Any]:
    path = os.path.join(HOLDOUTS_DIR, "PHASE2C_FUTURE_60D_HOLDOUT.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def test_all_on_disk_holdout_files_pass_validation():
    """Verify that all actual on-disk holdout files pass validation."""
    passed, results = validate_all_holdouts(REGISTRY_PATH, HOLDOUTS_DIR)
    for filename, (file_passed, errors) in results.items():
        assert file_passed, f"Validation failed for {filename}: {errors}"
    assert passed is True


def test_future_holdout_starts_after_20261002(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Holdout start date must be strictly after 2026-10-02."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["expected_start_date"] = "2026-10-05"
    errors = validator.validate_single_holdout(h)
    assert len(errors) == 0

    # Violation: start date <= 2026-10-02
    h_bad = copy.deepcopy(valid_holdout_base)
    h_bad["partition_definition"]["expected_start_date"] = "2026-10-02"
    errors_bad = validator.validate_single_holdout(h_bad)
    assert any("must be strictly after 2026-10-02" in e for e in errors_bad)


def test_holdout_uses_first_60_eligible_trading_days(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Holdout selection rule must be FIRST_60_ELIGIBLE_TRADING_DAYS."""
    h = copy.deepcopy(valid_holdout_base)
    assert h["partition_definition"]["selection_rule"] == "FIRST_60_ELIGIBLE_TRADING_DAYS"
    assert h["partition_definition"]["target_eligible_days"] == 60

    # Violation: arbitrary selection rule
    h_bad = copy.deepcopy(valid_holdout_base)
    h_bad["partition_definition"]["selection_rule"] = "CHERRY_PICKED_ACTIVE_DAYS"
    errors = validator.validate_single_holdout(h_bad)
    assert any("Invalid selection_rule" in e for e in errors)


def test_no_fixed_calendar_end_before_collection_complete(
    valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator
):
    """Calendar end date cannot be guessed or set before collection is complete."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 15
    h["partition_definition"]["holdout_end_date"] = "2026-12-31"  # Guessing end date
    errors = validator.validate_single_holdout(h)
    assert any("holdout_end_date must remain null until all 60 eligible days are collected" in e for e in errors)


def test_admin_metadata_allowed_while_blinded(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Inspecting only whitelisted administrative metadata maintains pristine status."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["inspected_metadata"] = [
        "file_existence",
        "ingestion_success",
        "schema_version",
        "checksum",
        "trading_calendar_membership",
    ]
    errors = validator.validate_single_holdout(h)
    assert len(errors) == 0


def test_ohlcv_access_invalidates_pristine_status(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Accessing OHLCV values in pristine holdout is prohibited and burns holdout."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["market_data_inspected"] = ["ohlcv_values"]
    errors = validator.validate_single_holdout(h)
    assert any("Prohibited market data inspected: 'ohlcv_values'" in e for e in errors)


def test_signal_access_invalidates_pristine_status(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Accessing signals or labels in pristine holdout is prohibited."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["market_data_inspected"] = ["signals", "labels"]
    errors = validator.validate_single_holdout(h)
    assert any("Prohibited market data inspected: 'signals'" in e for e in errors)


def test_aggregate_metric_peek_invalidates_holdout(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Inspecting aggregate metrics during blinded collection invalidates pristine status."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["market_data_inspected"] = ["aggregate_metrics"]
    errors = validator.validate_single_holdout(h)
    assert any("Prohibited market data inspected: 'aggregate_metrics'" in e for e in errors)


def test_subgroup_peek_invalidates_holdout(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Inspecting subgroup results (e.g. regime, time-of-day) invalidates pristine status."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["market_data_inspected"] = ["subgroup_metrics"]
    errors = validator.validate_single_holdout(h)
    assert any("Prohibited market data inspected: 'subgroup_metrics'" in e for e in errors)


def test_ai_access_counts_as_exposure(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """AI reading outcome data counts strictly as research exposure without exception."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["ai_outcome_access"] = True
    errors = validator.validate_single_holdout(h)
    assert any("AI outcome access occurred" in e and "counts strictly as exposure" in e for e in errors)


def test_human_access_counts_as_exposure(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Human reading outcome data counts as research exposure."""
    h = copy.deepcopy(valid_holdout_base)
    h["access_governance"]["human_outcome_access"] = True
    errors = validator.validate_single_holdout(h)
    assert any("Human outcome access occurred" in e for e in errors)


def test_interim_20_day_evaluation_forbidden(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Attempting early evaluation or claiming ready_to_unseal at day 20 is strictly forbidden."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 20
    h["unseal_readiness"]["ready_to_unseal"] = True
    errors = validator.validate_single_holdout(h)
    assert any("ready_to_unseal=true requires exactly 60 eligible days" in e for e in errors)


def test_ready_to_unseal_requires_60_days(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """READY_TO_UNSEAL requires exactly 60 collected eligible trading days."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 59
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"
    errors = validator.validate_single_holdout(h)
    assert any("Status READY_TO_UNSEAL requires exactly 60 eligible days; got 59" in e for e in errors)

    # Valid with exactly 60 days
    h_good = copy.deepcopy(valid_holdout_base)
    h_good["partition_definition"]["eligible_days_collected"] = 60
    h_good["lifecycle"]["status"] = "READY_TO_UNSEAL"
    h_good["lifecycle"]["history"] = make_valid_lifecycle_history("READY_TO_UNSEAL")
    h_good["unseal_readiness"]["ready_to_unseal"] = True
    errors_good = validator.validate_single_holdout(h_good)
    assert len(errors_good) == 0


def test_ready_to_unseal_does_not_auto_unseal(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """ready_to_unseal=true does NOT automatically authorize unsealing without explicit authorization record."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"  # Unsealed without authorization
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["unseal_readiness"]["ready_to_unseal"] = True
    h["unseal_readiness"]["unseal_authorized"] = False
    h["unseal_readiness"]["authorization_record"] = None
    errors = validator.validate_single_holdout(h)
    assert any("requires unseal_authorized: true" in e for e in errors)
    assert any("requires complete authorization_record" in e for e in errors)


def test_unseal_requires_all_freeze_hashes(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Unsealing requires complete set of 12 machine-auditable freeze hashes."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["unseal_readiness"]["ready_to_unseal"] = True
    h["unseal_readiness"]["unseal_authorized"] = True
    h["unseal_readiness"]["authorization_record"] = {
        "authorization_id": "AUTH_P2C_001",
        "authorized_at": "2026-10-04T00:00:00+08:00",
        "authorized_by": "CENTRAL_RESEARCH_GOVERNANCE",
        "trial_id": "TRIAL_P2C_F01_FUTURE_CONFIRMATION",
        "objective_spec_hash": "sha256:111111111111",
        "trial_preregistration_hash": "sha256:222222222222",
        "dataset_registry_hash": "sha256:333333333333",
        "pre_unseal_oos_consumption_ledger_hash": "sha256:444444444444",
        "holdout_policy_hash": "sha256:555555555555",
        "code_commit_sha": "89d48f1193d95ee32470d191c3a0e16414392c86",
        "cost_model_hash": "sha256:666666666666",
        # Missing evaluation_plan_hash
    }
    errors = validator.validate_single_holdout(h)
    assert any("Missing or empty required freeze hash field 'evaluation_plan_hash'" in e for e in errors)



def test_post_unseal_parameter_change_invalidates_confirmation():
    """Detecting parameter changes post-unseal invalidates independent confirmation."""
    frozen = {"parameter_grid_hash": "sha256:aaa111", "objective_hash": "sha256:bbb222"}
    altered = {"parameter_grid_hash": "sha256:aaa999_TAMPERED", "objective_hash": "sha256:bbb222"}
    violations = detect_post_unseal_modifications(frozen, altered)
    assert len(violations) == 1
    assert "Post-unseal modification detected for 'parameter_grid_hash'" in violations[0]
    assert "Confirmation invalidated" in violations[0]


def test_post_unseal_objective_change_invalidates_confirmation():
    """Detecting objective function or metric change post-unseal invalidates confirmation."""
    frozen = {"objective_spec_hash": "sha256:obj_v1", "code_commit_sha": "89d48f1"}
    altered = {"objective_spec_hash": "sha256:obj_v2_TAMPERED", "code_commit_sha": "89d48f1"}
    violations = detect_post_unseal_modifications(frozen, altered)
    assert len(violations) == 1
    assert "Post-unseal modification detected for 'objective_spec_hash'" in violations[0]
    assert "Confirmation invalidated" in violations[0]


def test_one_shot_confirmation_consumes_holdout(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Holdout confirmation mode must be ONE_SHOT and cannot be reused."""
    h = copy.deepcopy(valid_holdout_base)
    assert h["confirmation_contract"]["confirmation_mode"] == "ONE_SHOT"

    # Non-one-shot is prohibited
    h_bad = copy.deepcopy(valid_holdout_base)
    h_bad["confirmation_contract"]["confirmation_mode"] = "MULTI_ROUND_TRIAL_AND_ERROR"
    errors = validator.validate_single_holdout(h_bad)
    assert any("Invalid confirmation_mode" in e for e in errors)


def test_consumed_holdout_cannot_be_pristine_again(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """No Re-Pristining: A consumed or unsealed holdout can never transition back to pristine."""
    h = copy.deepcopy(valid_holdout_base)
    h["lifecycle"]["status"] = "RESERVED_UNTOUCHED"
    h["lifecycle"]["history"] = [
        {"state": "RESERVED_UNTOUCHED", "timestamp": "2026-10-01"},
        {"state": "COLLECTING_BLINDED", "timestamp": "2026-10-02"},
        {"state": "READY_TO_UNSEAL", "timestamp": "2026-10-03"},
        {"state": "UNSEALED_FOR_CONFIRMATION", "timestamp": "2026-10-04"},
        {"state": "CONSUMED", "timestamp": "2026-10-05"},
        {"state": "RESERVED_UNTOUCHED", "timestamp": "2026-10-06"},  # Illegal re-pristining!
    ]
    errors = validator.validate_single_holdout(h)
    assert any("Re-pristining violation" in e for e in errors)


def test_confirmation_supported_does_not_mean_production_ready(
    valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator
):
    """Confirmation supported within preregistered scope strictly cannot set production_ready to true."""
    h = copy.deepcopy(valid_holdout_base)
    h["confirmation_contract"]["confirmation_outcome"] = "SUPPORTED_WITHIN_PREREGISTERED_SCOPE"
    h["confirmation_contract"]["production_ready"] = True  # VIOLATION: strictly false
    errors = validator.validate_single_holdout(h)
    assert any("production_ready must be strictly false" in e for e in errors)


def test_holdout_identity_comes_from_dataset_registry(
    valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator
):
    """Holdout dataset_family_id and dataset_lineage_id must strictly match Central Registry."""
    h = copy.deepcopy(valid_holdout_base)
    h["dataset_lineage_id"] = "LINEAGE_INVENTED_ARBITRARY_ID"  # Mismatch
    errors = validator.validate_single_holdout(h)
    assert any("dataset_lineage_id mismatch" in e for e in errors)


def test_unknown_lineage_cannot_be_unsealed(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """LINEAGE_UNKNOWN datasets cannot be unsealed for independent confirmation."""
    h = copy.deepcopy(valid_holdout_base)
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["dataset_lineage_id"] = "LINEAGE_UNKNOWN"
    # Even if authorization record is present
    h["unseal_readiness"]["unseal_authorized"] = True
    h["unseal_readiness"]["authorization_record"] = {f: "hash" for f in [
        "authorization_id", "authorized_at", "authorized_by", "trial_id",
        "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
        "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
        "cost_model_hash", "evaluation_plan_hash",
    ]}
    errors = validator.validate_single_holdout(h)
    assert any("LINEAGE_UNKNOWN cannot be unsealed" in e or "dataset_lineage_id mismatch" in e for e in errors)


def test_outcome_dependent_day_skipping_forbidden(valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator):
    """Holdout eligibility criteria cannot include outcome-dependent filters (volume, return, activity)."""
    h = copy.deepcopy(valid_holdout_base)
    h["eligibility_preregistration"]["criteria"].append("daily_trading_volume > 10000000")  # Volume filter
    errors = validator.validate_single_holdout(h)
    assert any("Outcome-dependent day selection criterion detected" in e for e in errors)


def test_outcome_read_forbidden_before_consumption_event_exists(
    valid_holdout_base: Dict[str, Any], central_registry: DatasetRegistry
):
    """Any outcome-bearing read is strictly forbidden before consumption event registration and unseal."""
    validator = PristineHoldoutValidator(central_registry, authoritative_consumption_events={})
    h = copy.deepcopy(valid_holdout_base)
    # Outcome access attempted while still in RESERVED_UNTOUCHED and without consumption event
    h["access_governance"]["performance_seen"] = True
    errors = validator.validate_single_holdout(h)
    assert any("Outcome access forbidden before consumption event exists" in e for e in errors)

    # Valid: properly authorized, transitioned to UNSEALED, and registered consumption event in authoritative pool
    c_id = "CNS_P2C_FUTURE_60D_UNSEAL_CONFIRMATION"
    auth_id = "AUTH_P2C_001"
    pre_hash = "sha256:444444444444"

    h_unsealed = copy.deepcopy(valid_holdout_base)
    h_unsealed["partition_definition"]["eligible_days_collected"] = 60
    h_unsealed["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h_unsealed["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h_unsealed["unseal_readiness"]["ready_to_unseal"] = True
    h_unsealed["unseal_readiness"]["unseal_authorized"] = True
    h_unsealed["unseal_readiness"]["consumption_event_id"] = c_id
    h_unsealed["unseal_readiness"]["consumption_event_registered"] = True
    h_unsealed["unseal_readiness"]["authorization_record"] = {
        f: "hash" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    h_unsealed["unseal_readiness"]["authorization_record"]["authorization_id"] = auth_id
    h_unsealed["unseal_readiness"]["authorization_record"]["pre_unseal_oos_consumption_ledger_hash"] = pre_hash
    h_unsealed["access_governance"]["performance_seen"] = True

    # Inject matching authoritative event
    authoritative_events = {
        c_id: {
            "consumption_id": c_id,
            "holdout_id": h_unsealed["holdout_id"],
            "triggered_by_authorization_id": auth_id,
            "pre_unseal_ledger_hash": pre_hash,
        }
    }
    validator_with_event = PristineHoldoutValidator(
        central_registry, authoritative_consumption_events=authoritative_events
    )
    errors_unsealed = validator_with_event.validate_single_holdout(h_unsealed)
    assert len(errors_unsealed) == 0


def test_fake_consumption_event_id_is_not_registration(
    valid_holdout_base: Dict[str, Any], central_registry: DatasetRegistry
):
    """Having a non-empty consumption_event_id does not count as registered unless present in authoritative ledger."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["unseal_readiness"]["ready_to_unseal"] = True
    h["unseal_readiness"]["unseal_authorized"] = True
    h["unseal_readiness"]["consumption_event_id"] = "FAKE_INVENTED_EVENT_999"
    h["unseal_readiness"]["authorization_record"] = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    validator = PristineHoldoutValidator(central_registry, authoritative_consumption_events={})
    errors = validator.validate_single_holdout(h)
    assert any("Authoritative consumption event missing" in e for e in errors)
    assert any("An ID or registered boolean alone is insufficient" in e for e in errors)


def test_registered_boolean_without_authoritative_event_fails(
    valid_holdout_base: Dict[str, Any], central_registry: DatasetRegistry
):
    """Setting consumption_event_registered: true without an authoritative event in ledger fails validation."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["unseal_readiness"]["ready_to_unseal"] = True
    h["unseal_readiness"]["unseal_authorized"] = True
    h["unseal_readiness"]["consumption_event_id"] = "NONEXISTENT_EVENT_ID"
    h["unseal_readiness"]["consumption_event_registered"] = True
    h["unseal_readiness"]["authorization_record"] = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    validator = PristineHoldoutValidator(central_registry, authoritative_consumption_events={})
    errors = validator.validate_single_holdout(h)
    assert any("Authoritative consumption event missing" in e for e in errors)


def test_consumption_event_must_match_holdout_id(valid_holdout_base: Dict[str, Any]):
    """Consumption event record must strictly match the holdout_id of the holdout record."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_TEST_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:pre_hash_123"

    event_mismatch = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": "HD_WRONG_HOLDOUT_ID",
        "triggered_by_authorization_id": "AUTH_TEST_001",
        "pre_unseal_ledger_hash": "sha256:pre_hash_123",
    }

    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event_mismatch,
        pre_unseal_ledger_hash="sha256:pre_hash_123",
    )
    assert success is False
    assert any("Holdout ID binding failure" in e for e in errors)


def test_consumption_event_must_reference_authorization_id(valid_holdout_base: Dict[str, Any]):
    """Consumption event record must strictly reference the authorization_id from the authorization record."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_CORRECT_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:pre_hash_123"

    event_mismatch = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": h["holdout_id"],
        "triggered_by_authorization_id": "AUTH_WRONG_999",
        "pre_unseal_ledger_hash": "sha256:pre_hash_123",
    }

    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event_mismatch,
        pre_unseal_ledger_hash="sha256:pre_hash_123",
    )
    assert success is False
    assert any("Authorization ID binding failure" in e for e in errors)


def test_consumption_event_pre_unseal_hash_must_match_authorization(valid_holdout_base: Dict[str, Any]):
    """Consumption event pre_unseal_ledger_hash must match authorization record."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_TEST_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:pre_hash_123"

    event_mismatch = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": h["holdout_id"],
        "triggered_by_authorization_id": "AUTH_TEST_001",
        "pre_unseal_ledger_hash": "sha256:pre_hash_DIFFERENT",
    }

    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event_mismatch,
        pre_unseal_ledger_hash="sha256:pre_hash_123",
    )
    assert success is False
    assert any("Pre-unseal hash binding failure" in e for e in errors)


def test_function_pre_unseal_hash_must_match_authorization(valid_holdout_base: Dict[str, Any]):
    """Function argument pre_unseal_ledger_hash must match authorization record pre_unseal hash."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_TEST_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:auth_hash_123"

    event = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": h["holdout_id"],
        "triggered_by_authorization_id": "AUTH_TEST_001",
        "pre_unseal_ledger_hash": "sha256:auth_hash_123",
    }

    # Pass mismatching caller hash
    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event,
        pre_unseal_ledger_hash="sha256:caller_different_hash",
    )
    assert success is False
    assert any("does not match authorization record pre_unseal_oos_consumption_ledger_hash" in e for e in errors)


def test_valid_atomic_transition_proposal_passes(valid_holdout_base: Dict[str, Any]):
    """Valid atomic transition proposal with all three records correctly bound passes validation."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"
    h["unseal_readiness"]["consumption_event_id"] = "CNS_TEST_001"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_TEST_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:snapshot_hash_123"

    event = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": h["holdout_id"],
        "triggered_by_authorization_id": "AUTH_TEST_001",
        "pre_unseal_ledger_hash": "sha256:snapshot_hash_123",
    }

    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event,
        pre_unseal_ledger_hash="sha256:snapshot_hash_123",
    )
    assert success is True
    assert len(errors) == 0


def test_atomic_validation_does_not_mutate_input_records(valid_holdout_base: Dict[str, Any]):
    """validate_atomic_unseal_transition must be pure and never mutate input dictionaries."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "READY_TO_UNSEAL"
    h["unseal_readiness"]["consumption_event_id"] = "CNS_TEST_001"

    auth = {
        f: "hash_val" for f in [
            "authorization_id", "authorized_at", "authorized_by", "trial_id",
            "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
            "pre_unseal_oos_consumption_ledger_hash", "holdout_policy_hash", "code_commit_sha",
            "cost_model_hash", "evaluation_plan_hash",
        ]
    }
    auth["authorization_id"] = "AUTH_TEST_001"
    auth["pre_unseal_oos_consumption_ledger_hash"] = "sha256:snapshot_hash_123"

    event = {
        "consumption_id": "CNS_TEST_001",
        "holdout_id": h["holdout_id"],
        "triggered_by_authorization_id": "AUTH_TEST_001",
        "pre_unseal_ledger_hash": "sha256:snapshot_hash_123",
    }

    h_before = copy.deepcopy(h)
    auth_before = copy.deepcopy(auth)
    event_before = copy.deepcopy(event)

    success, errors = validate_atomic_unseal_transition(
        holdout_record=h,
        authorization_record=auth,
        consumption_event_record=event,
        pre_unseal_ledger_hash="sha256:snapshot_hash_123",
    )
    assert success is True

    # Assert exact identity/equality before and after
    assert h == h_before
    assert auth == auth_before
    assert event == event_before


def test_lifecycle_status_must_match_last_history_state(
    valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator
):
    """Lifecycle status must strictly equal the state in the last history entry."""
    h = copy.deepcopy(valid_holdout_base)
    # Tamper status without updating history
    h["lifecycle"]["status"] = "COLLECTING_BLINDED"
    # History still ends in RESERVED_UNTOUCHED
    errors = validator.validate_single_holdout(h)
    assert any(
        "Lifecycle status mismatch: status is 'COLLECTING_BLINDED', but last history state is 'RESERVED_UNTOUCHED'" in e
        for e in errors
    )

    # Valid: status and last history entry match
    h["lifecycle"]["history"].append({
        "state": "COLLECTING_BLINDED",
        "timestamp": "2026-10-05T09:00:00+08:00",
        "reason": "First collection batch started.",
    })
    errors_fixed = validator.validate_single_holdout(h)
    assert not any("Lifecycle status mismatch" in e for e in errors_fixed)


def test_authorization_uses_pre_unseal_ledger_hash(
    valid_holdout_base: Dict[str, Any], validator: PristineHoldoutValidator
):
    """Authorization record must use pre_unseal_oos_consumption_ledger_hash instead of ambiguous hash."""
    h = copy.deepcopy(valid_holdout_base)
    h["partition_definition"]["eligible_days_collected"] = 60
    h["lifecycle"]["status"] = "UNSEALED_FOR_CONFIRMATION"
    h["lifecycle"]["history"] = make_valid_lifecycle_history("UNSEALED_FOR_CONFIRMATION")
    h["unseal_readiness"]["ready_to_unseal"] = True
    h["unseal_readiness"]["unseal_authorized"] = True
    # Record has all fields except pre_unseal_oos_consumption_ledger_hash
    h["unseal_readiness"]["authorization_record"] = {f: "hash_val" for f in [
        "authorization_id", "authorized_at", "authorized_by", "trial_id",
        "objective_spec_hash", "trial_preregistration_hash", "dataset_registry_hash",
        "holdout_policy_hash", "code_commit_sha", "cost_model_hash", "evaluation_plan_hash",
    ]}
    errors = validator.validate_single_holdout(h)
    assert any("Missing or empty required freeze hash field 'pre_unseal_oos_consumption_ledger_hash'" in e for e in errors)


def test_post_unseal_ledger_append_does_not_invalidate_pre_unseal_snapshot():
    """Ledger append after unseal changes ledger hash, which must NOT invalidate pre-unseal snapshot."""
    pre_unseal_frozen = {
        "pre_unseal_oos_consumption_ledger_hash": "sha256:snapshot_before_append",
        "objective_spec_hash": "sha256:obj_frozen",
        "code_commit_sha": "89d48f1193d95ee32470d191c3a0e16414392c86",
    }
    # After unseal, the ledger on disk has a new event appended -> its current hash changed to something else
    post_unseal_current = {
        "pre_unseal_oos_consumption_ledger_hash": "sha256:ledger_changed_by_append",
        "objective_spec_hash": "sha256:obj_frozen",
        "code_commit_sha": "89d48f1193d95ee32470d191c3a0e16414392c86",
    }
    violations = detect_post_unseal_modifications(pre_unseal_frozen, post_unseal_current)
    # The change in ledger hash is expected lifecycle progression and must NOT trigger violation
    assert len(violations) == 0


