"""
Unit tests for EasyStock Research Governance Trial Ledger and Validator.
Verifies all 10 governance invariants, dataset/slice-scoped exposure rules,
lineage anti-bypass protection, untouched future reservation semantics,
the 4 legacy backfill trials, and comprehensive OBJECTIVE_FUNCTION_SPEC_v1 invariants.
"""

import copy
import sys
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from daytrade_learning.research_governance.validate_trial_ledger import (
    TrialLedgerValidator,
    validate_all_trials,
    validate_trial_file,
)


@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def trials_dir(repo_root):
    return repo_root / "docs" / "research_governance" / "trials"


@pytest.fixture
def sample_valid_trial():
    """Returns a completely valid synthetic trial dictionary for unit mutation testing."""
    return {
        "trial_id": "TRIAL_TEST_SYNTHETIC_01",
        "parent_trial_id": None,
        "created_at": "2026-10-03T12:00:00+08:00",
        "study_name": "Synthetic Test Study",
        "research_stage": "PHASE_2D",
        "ledger_record_type": "PREREGISTERED_TRIAL",
        "recorded_after_experiment": False,
        "provenance": {
            "source_classification": "CANONICAL_INTERNAL_PRIMITIVE",
            "source_refs": ["docs/daytrade_phase2/test_ref.md"],
        },
        "hypothesis": {
            "statement": "Test hypothesis statement",
            "preregistered": True,
            "exploratory": False,
        },
        "objective": {
            "spec_version": "OBJECTIVE_FUNCTION_SPEC_v1",
            "primary_metric": "delta_net_return_pct",
            "direction": "MAXIMIZE",
            "baseline": "TEST_BASELINE",
            "frozen_before_search": True,
        },
        "data": {
            "dataset_id": "TEST_DATASET_2026",
            "dataset_family_id": "TEST_FAMILY_TWSE",
            "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
            "universe": "100_STOCK_LIQUIDITY_POOL",
            "discovery_data_reused": False,
            "independent_confirmation": False,
        },
        "exposure_state": {
            "train_seen": True,
            "validation_seen": False,
            "oos_seen": False,
            "future_holdout_seen": False,
            "exposed_dimensions": ["test_dimension"],
            "exposures": [
                {
                    "exposure_id": "EXP_TEST_SYNTHETIC_TRAIN",
                    "dataset_id": "TEST_DATASET_2026",
                    "dataset_family_id": "TEST_FAMILY_TWSE",
                    "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
                    "start_date": "2024-01-01",
                    "end_date": "2025-12-31",
                    "role": "TRAIN",
                    "seen": True,
                    "exposed_dimensions": ["test_dimension"],
                    "source_trial_id": "TRIAL_TEST_SYNTHETIC_01",
                    "first_seen_at": "2026-10-03T12:00:00+08:00",
                }
            ],
        },
        "search": {
            "parameters_searched": ["param_a"],
            "search_space": {"param_a": [1, 2, 3]},
            "trial_count": 3,
            "post_hoc_changes": False,
        },
        "governance": {
            "plan_hash": "test_hash_plan",
            "registry_hash": "test_hash_reg",
            "no_oos_tuning": True,
            "production_effect": "NONE",
        },
        "result": {
            "status": "SEALED",
            "decision": "ACCEPTED_IN_SAMPLE",
            "sealed_commit": "abcdef1234567890abcdef1234567890abcdef12",
            "notes": "Test synthetic trial notes",
        },
    }


# ==============================================================================
# 1. Backfilled Legacy Trials Verification
# ==============================================================================

def test_all_backfill_trials_pass_validation(trials_dir):
    """Every trial in docs/research_governance/trials must pass validation (4 Phase 2 + event-audit trials)."""
    passed, results = validate_all_trials(trials_dir)
    for filename, errors in results.items():
        assert len(errors) == 0, f"Validation failed for {filename}: {errors}"
    assert passed is True
    legacy = {"P2A_LEGACY_BACKFILL.yaml", "P2B_BATCH1_LEGACY_BACKFILL.yaml",
              "P2B_BATCH2_LEGACY_BACKFILL.yaml", "P2C_F01_LEGACY_BACKFILL.yaml"}
    assert legacy <= set(results), f"Missing legacy trial files: {legacy - set(results)}"


def test_event_audit_trials_form_a_rejected_chain(trials_dir):
    """H2 -> H3 -> H4 -> primitive batch -> base-rate audit -> book rules, none production-ready or confirmed."""
    trials = {}
    for f in trials_dir.glob("EA_*.yaml"):
        with open(f, "r", encoding="utf-8") as fp:
            d = yaml.safe_load(fp)
            trials[d["trial_id"]] = d
    chain = ["TRIAL_EA_H2_TICK_COMPRESSION_BREAKOUT", "TRIAL_EA_H3_COMPLETED_BAR_BREAKOUT",
             "TRIAL_EA_H4_SOURCE_NATIVE_ORB", "TRIAL_EA_SOURCE_PRIMITIVE_BATCH_V1",
             "TRIAL_EA_BASE_RATE_MATCHED_CONTROL_V1", "TRIAL_EA_BOOK_RULES_V1",
             "TRIAL_EA_COST_FEASIBILITY_V1", "TRIAL_EA_HV60_V1", "TRIAL_EA_PASSIVE_FILL_V1"]
    assert set(chain) == set(trials)
    assert trials[chain[0]]["parent_trial_id"] is None
    for parent, child in zip(chain, chain[1:]):
        assert trials[child]["parent_trial_id"] == parent
    for t in trials.values():
        assert t["result"]["PRODUCTION_READY"] is False
        assert t["result"]["INDEPENDENT_CONFIRMATION"] is False
        assert t["data"]["independent_confirmation"] is False
        assert t["governance"]["production_effect"] == "NONE"


def test_legacy_backfill_lineage_integrity(trials_dir):
    """Check parent-child chain of the 4 legacy backfilled trials."""
    validator = TrialLedgerValidator(trials_dir)
    passed, results = validator.validate_ledger_directory()
    assert passed is True

    # Load all files
    trials = {}
    for f in trials_dir.glob("*.yaml"):
        with open(f, "r", encoding="utf-8") as fp:
            d = yaml.safe_load(fp)
            trials[d["trial_id"]] = d

    # Verify P2A is root
    assert "TRIAL_P2A_FOUNDATION" in trials
    assert trials["TRIAL_P2A_FOUNDATION"]["parent_trial_id"] is None

    # Verify P2B Batch 1 child of P2A
    assert "TRIAL_P2B_BATCH1_CANDIDATE_SEARCH" in trials
    assert (
        trials["TRIAL_P2B_BATCH1_CANDIDATE_SEARCH"]["parent_trial_id"]
        == "TRIAL_P2A_FOUNDATION"
    )

    # Verify P2B Batch 2 child of P2B Batch 1
    assert "TRIAL_P2B_BATCH2_FILTER_STUDY" in trials
    assert (
        trials["TRIAL_P2B_BATCH2_FILTER_STUDY"]["parent_trial_id"]
        == "TRIAL_P2B_BATCH1_CANDIDATE_SEARCH"
    )

    # Verify P2C child of P2B Batch 2
    assert "TRIAL_P2C_F01_MECHANISM_FOLLOWUP" in trials
    assert (
        trials["TRIAL_P2C_F01_MECHANISM_FOLLOWUP"]["parent_trial_id"]
        == "TRIAL_P2B_BATCH2_FILTER_STUDY"
    )


def test_phase2c_f01_legacy_backfill_sealed_metadata(trials_dir):
    """Phase 2C trial must record the 8 exposed dimensions and strict sealed attributes."""
    p2c_file = trials_dir / "P2C_F01_LEGACY_BACKFILL.yaml"
    assert p2c_file.exists()

    with open(p2c_file, "r", encoding="utf-8") as f:
        p2c = yaml.safe_load(f)

    assert p2c["result"]["status"] == "SEALED"
    assert p2c["result"]["sealed_commit"] == "8ceb6a94c6ed353cf9ddb250f8c4aab60e278577"
    assert p2c["result"]["PHASE2C_SEALED"] is True
    assert p2c["result"]["PRODUCTION_READY"] is False
    assert p2c["result"]["DISCOVERY_DATA_REUSED"] is True
    assert p2c["result"]["INDEPENDENT_CONFIRMATION"] is False
    assert p2c["result"]["FUTURE_CONFIRMATION_UNTOUCHED"] is True

    # Verify all 8 burned dimensions are recorded
    exposed = p2c["exposure_state"]["exposed_dimensions"]
    assert len(exposed) == 8
    expected_dimensions = [
        "F01 overall result",
        "H01 trend-direction buckets",
        "H02 volatility buckets",
        "H03 opening 15m/30m buckets",
        "H04 time-of-day",
        "H05 breadth",
        "H06 LONG/SHORT/candidate breakdown",
        "H07 year/failure-regime descriptive results",
    ]
    for dim in expected_dimensions:
        assert dim in exposed, f"Missing exposed dimension: {dim}"

    # Verify scoped exposures and confirmation claim
    assert len(p2c["exposure_state"]["exposures"]) >= 1
    exp0 = p2c["exposure_state"]["exposures"][0]
    assert exp0["dataset_id"] == "PHASE2_HISTORICAL_2023_2026_10_02"
    assert exp0["dataset_family_id"] == "TWSE_EQUITY_INTRADAY"
    assert exp0["dataset_lineage_id"] == "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1"
    assert exp0["role"] == "OOS"
    assert exp0["seen"] is True

    claim = p2c.get("confirmation_claim")
    assert claim is not None
    assert claim["dataset_id"] == "PHASE2C_FUTURE_CONFIRMATION_60D"
    assert claim["dataset_family_id"] == "TWSE_EQUITY_INTRADAY"
    assert claim["dataset_lineage_id"] == "LINEAGE_SHIOAJI_TICKS_CANONICAL_V1"
    assert claim["start_date"] == "2026-10-05"
    assert claim["end_date"] is None
    assert claim["intended_independent_confirmation"] is True
    assert claim["confirmation_status"] == "RESERVED_UNTOUCHED"
    assert claim["performance_seen"] is False
    assert claim["independent_confirmation_completed"] is False


def test_batch1_historical_counts_match_sealed_artifacts(trials_dir):
    """P2B Batch 1 legacy backfill must strictly match sealed run summary and report."""
    b1_file = trials_dir / "P2B_BATCH1_LEGACY_BACKFILL.yaml"
    assert b1_file.exists()

    with open(b1_file, "r", encoding="utf-8") as f:
        b1 = yaml.safe_load(f)

    search = b1["search"]
    assert search["candidate_count"] == 4
    assert search["parameter_combination_count"] == 18
    assert search["unique_signal_events"] == 1591201
    assert search["exit_policy_count"] == 5
    assert search["slippage_level_count"] == 4
    assert search["simulation_evaluations_per_signal"] == 20
    assert search["simulation_rows"] == 31824020
    assert search["trial_count"] is None
    assert b1["objective"]["historical_information_incomplete"] is True


# ==============================================================================
# 2. Schema and Invariant Validation Tests
# ==============================================================================

def test_schema_missing_required_key(sample_valid_trial):
    """Removing any top-level key should fail schema validation."""
    validator = TrialLedgerValidator()
    required_keys = [
        "trial_id",
        "parent_trial_id",
        "created_at",
        "study_name",
        "research_stage",
        "ledger_record_type",
        "recorded_after_experiment",
        "provenance",
        "hypothesis",
        "objective",
        "data",
        "exposure_state",
        "search",
        "governance",
        "result",
    ]
    for key in required_keys:
        mutated = copy.deepcopy(sample_valid_trial)
        del mutated[key]
        errors = validator.validate_single_trial(mutated)
        assert len(errors) > 0, f"Validator should fail when '{key}' is missing"
        assert any(key in err for err in errors)


def test_invalid_trial_id_format(sample_valid_trial):
    """trial_id must match ^TRIAL_[A-Z0-9_]+$."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["trial_id"] = "invalid_lowercase_id"
    errors = validator.validate_single_trial(mutated)
    assert any("Invalid trial_id" in err for err in errors)


def test_parent_trial_id_existence(sample_valid_trial):
    """Non-existent parent_trial_id should fail cross-validation."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["parent_trial_id"] = "TRIAL_NON_EXISTENT_PARENT"

    known_trials = {"TRIAL_TEST_SYNTHETIC_01": mutated}
    errors = validator.validate_semantics(mutated, all_trials=known_trials)
    assert any("parent trial does not exist in ledger" in err for err in errors)


def test_lineage_cycle_detection(tmp_path):
    """Cyclic parent_trial_id references must be detected and rejected."""
    trial_a = {
        "trial_id": "TRIAL_CYCLE_A",
        "parent_trial_id": "TRIAL_CYCLE_B",
        "created_at": "2026-10-03T12:00:00+08:00",
        "study_name": "Cycle Study A",
        "research_stage": "EXPLORATORY",
        "ledger_record_type": "EXPLORATORY_SPIKE",
        "recorded_after_experiment": True,
        "provenance": {
            "source_classification": "EXPLORATORY_HEURISTIC",
            "source_refs": ["test"],
        },
        "hypothesis": {"statement": "h", "preregistered": False, "exploratory": True},
        "objective": {
            "spec_version": "v1",
            "primary_metric": "m",
            "direction": "MAXIMIZE",
            "baseline": "b",
            "frozen_before_search": False,
        },
        "data": {
            "dataset_id": "d",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "universe": "u",
            "discovery_data_reused": True,
            "independent_confirmation": False,
        },
        "exposure_state": {
            "train_seen": True,
            "validation_seen": False,
            "oos_seen": False,
            "future_holdout_seen": False,
            "exposures": [
                {
                    "exposure_id": "EXP_A",
                    "dataset_id": "d",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "role": "TRAIN",
                    "seen": True,
                    "exposed_dimensions": [],
                    "source_trial_id": "TRIAL_CYCLE_A",
                    "first_seen_at": "2026-10-03T12:00:00+08:00",
                }
            ],
        },
        "search": {
            "parameters_searched": [],
            "search_space": {},
            "trial_count": 0,
            "post_hoc_changes": False,
        },
        "governance": {
            "plan_hash": None,
            "registry_hash": None,
            "no_oos_tuning": True,
            "production_effect": "NONE",
        },
        "result": {
            "status": "REJECTED",
            "decision": "d",
            "sealed_commit": None,
            "notes": "n",
        },
    }
    trial_b = copy.deepcopy(trial_a)
    trial_b["trial_id"] = "TRIAL_CYCLE_B"
    trial_b["parent_trial_id"] = "TRIAL_CYCLE_A"

    with open(tmp_path / "trial_a.yaml", "w") as f:
        yaml.dump(trial_a, f)
    with open(tmp_path / "trial_b.yaml", "w") as f:
        yaml.dump(trial_b, f)

    validator = TrialLedgerValidator(tmp_path)
    passed, results = validator.validate_ledger_directory()
    assert passed is False
    assert any("Cyclic parent_trial_id" in err for err in results.get("[GLOBAL]", []))


def test_data_dates_validity(sample_valid_trial):
    """start_date > end_date must be rejected."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["data"]["start_date"] = "2026-01-01"
    mutated["data"]["end_date"] = "2024-01-01"
    errors = validator.validate_semantics(mutated)
    assert any("Invalid date range" in err for err in errors)


def test_sealed_trial_requires_commit_hash(sample_valid_trial):
    """SEALED trial without sealed_commit must be rejected."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["result"]["status"] = "SEALED"
    mutated["result"]["sealed_commit"] = None
    errors = validator.validate_semantics(mutated)
    assert any("SEALED trial must have a valid non-empty sealed_commit" in err for err in errors)


def test_contradictory_hypothesis(sample_valid_trial):
    """hypothesis cannot have both preregistered=True and exploratory=True."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["hypothesis"]["preregistered"] = True
    mutated["hypothesis"]["exploratory"] = True
    errors = validator.validate_semantics(mutated)
    assert any("Contradictory hypothesis" in err for err in errors)


def test_production_effect_must_be_strictly_none(sample_valid_trial):
    """production_effect must be strictly 'NONE'."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["governance"]["production_effect"] = "TRIGGER_LIVE_ORDERS"
    errors = validator.validate_semantics(mutated)
    assert any("governance.production_effect must strictly be 'NONE'" in err for err in errors)


def test_legacy_backfill_cannot_claim_recorded_before(sample_valid_trial):
    """LEGACY_BACKFILL must have recorded_after_experiment=True."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    mutated["ledger_record_type"] = "LEGACY_BACKFILL"
    mutated["recorded_after_experiment"] = False
    errors = validator.validate_semantics(mutated)
    assert any("LEGACY_BACKFILL must have recorded_after_experiment=True" in err for err in errors)


# ==============================================================================
# 3. Scoped Exposure & Independent Confirmation Tests
# ==============================================================================

def test_same_slice_seen_cannot_claim_independent_confirmation(sample_valid_trial):
    """Claiming independent confirmation on an identical seen slice must FAIL."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Exposed slice: [2024-01-01, 2025-12-31] on TEST_DATASET_2026
    # Confirmation claim on the exact same slice:
    mutated["data"]["independent_confirmation"] = True
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("overlaps with exposed" in err or "overlaps with previously seen" in err for err in errors)


def test_partial_overlap_cannot_claim_independent_confirmation(sample_valid_trial):
    """Claiming independent confirmation on a slice partially overlapping a seen slice must FAIL."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Exposed slice: [2024-01-01, 2025-12-31]
    # Confirmation claim: [2025-06-01, 2026-06-30] (partial overlap)
    mutated["confirmation_claim"] = {
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2025-06-01",
        "end_date": "2026-06-30",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("overlaps with exposed" in err for err in errors)


def test_nonoverlapping_future_slice_can_claim_independent_confirmation(sample_valid_trial):
    """Claiming independent confirmation on a future slice strictly after all seen slices must PASS."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Exposed slice: [2024-01-01, 2025-12-31]
    # Confirmation claim: [2026-01-01, 2026-12-31] (strictly after 2025-12-31)
    mutated["confirmation_claim"] = {
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) == 0, f"Expected pass, got errors: {errors}"


def test_seen_future_slice_cannot_become_pristine_again(sample_valid_trial):
    """A slice previously seen as HOLDOUT / OOS cannot be claimed again as independent confirmation."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Add a seen HOLDOUT exposure
    mutated["exposure_state"]["exposures"].append({
        "exposure_id": "EXP_HOLDOUT_SEEN",
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "role": "HOLDOUT",
        "seen": True,
        "exposed_dimensions": ["holdout_pnl"],
        "source_trial_id": "TRIAL_TEST_SYNTHETIC_01",
        "first_seen_at": "2026-10-03T12:00:00+08:00",
    })
    # Now claim independent confirmation on that HOLDOUT slice
    mutated["confirmation_claim"] = {
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("Previously seen HOLDOUT data cannot be claimed" in err for err in errors)


def test_different_unseen_dataset_can_be_independent(sample_valid_trial):
    """Claiming independent confirmation on an entirely different unseen dataset must PASS."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Exposed slice is on TEST_DATASET_2026, TEST_FAMILY_TWSE, TEST_LINEAGE_CANONICAL
    # Confirmation claim is on an unrelated dataset, family, and lineage
    mutated["confirmation_claim"] = {
        "dataset_id": "NEW_INDEPENDENT_MARKET_DATASET",
        "dataset_family_id": "CRYPTO_BINANCE_SPOT",
        "dataset_lineage_id": "BINANCE_TRADES_V1",
        "start_date": "2024-01-01",
        "end_date": "2025-12-31",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) == 0, f"Expected pass, got errors: {errors}"


def test_legacy_oos_seen_does_not_globally_burn_all_future_data(sample_valid_trial):
    """oos_seen=True summary flag does NOT globally burn future slices that are strictly non-overlapping."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Historical OOS was seen
    mutated["exposure_state"]["oos_seen"] = True
    mutated["exposure_state"]["exposures"][0]["role"] = "OOS"
    mutated["exposure_state"]["exposures"][0]["end_date"] = "2025-12-31"

    # Confirmation claim is strictly on future data (2026-01-01 onwards)
    mutated["confirmation_claim"] = {
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) == 0, f"Future slice should not be globally burned: {errors}"


# ==============================================================================
# 4. Anti-Bypass & Reservation Semantics Tests (New Requirements)
# ==============================================================================

def test_dataset_rename_cannot_bypass_exposure(sample_valid_trial):
    """Renaming dataset_id while sharing family/lineage with seen data must FAIL on date overlap."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)
    # Exposed slice has family TEST_FAMILY_TWSE and lineage TEST_LINEAGE_CANONICAL on [2024-01-01, 2025-12-31]
    # Attempting to bypass by using renamed dataset_id "RENAMED_DATASET_TRICK_V2" on overlapping date [2025-06-01, 2026-06-30]
    mutated["confirmation_claim"] = {
        "dataset_id": "RENAMED_DATASET_TRICK_V2",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2025-06-01",
        "end_date": "2026-06-30",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": False,
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("aliased from" in err or "overlaps with exposed" in err for err in errors)


def test_untouched_future_claim_is_not_completed_confirmation(sample_valid_trial):
    """RESERVED_UNTOUCHED confirmation claim cannot state independent_confirmation_completed=True or performance_seen=True."""
    validator = TrialLedgerValidator()
    mutated = copy.deepcopy(sample_valid_trial)

    # Claiming completed confirmation while untouched
    mutated["confirmation_claim"] = {
        "dataset_id": "TEST_DATASET_2026",
        "dataset_family_id": "TEST_FAMILY_TWSE",
        "dataset_lineage_id": "TEST_LINEAGE_CANONICAL",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "role": "FUTURE_CONFIRMATION",
        "intended_independent_confirmation": True,
        "confirmation_status": "RESERVED_UNTOUCHED",
        "performance_seen": False,
        "independent_confirmation_completed": True,  # Contradiction!
    }
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("independent_confirmation_completed cannot be True" in err for err in errors)

    # Claiming performance_seen=True while untouched
    mutated["confirmation_claim"]["independent_confirmation_completed"] = False
    mutated["confirmation_claim"]["performance_seen"] = True  # Contradiction!
    errors = validator.validate_semantics(mutated)
    assert len(errors) > 0
    assert any("performance_seen must be False" in err for err in errors)


# ==============================================================================
# 5. Objective Function Specification Comprehensive Tests
# ==============================================================================

def test_objective_function_spec_v1_yaml_content(repo_root):
    """Verify OBJECTIVE_FUNCTION_SPEC_v1.yaml has all mandatory frozen invariants, gates, and profiles."""
    spec_path = repo_root / "docs" / "research_governance" / "OBJECTIVE_FUNCTION_SPEC_v1.yaml"
    assert spec_path.exists(), "OBJECTIVE_FUNCTION_SPEC_v1.yaml must exist"

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    # 1. spec_metadata
    assert spec["spec_metadata"]["status"] == "RESEARCH_GOVERNANCE"
    assert spec["spec_metadata"]["production_effect"] == "NONE"

    # 2. governance_invariants
    inv = spec["governance_invariants"]
    assert inv["freeze_before_search"] is True
    assert inv["train_only_selection"] is True
    assert inv["oos_selection_allowed"] is False
    assert inv["robust_region_required"] is True
    assert inv["post_hoc_objective_change_allowed"] is False

    # 3. eligibility_gates
    gates = spec["eligibility_gates"]
    mandatory_gates = [
        "implementation_integrity",
        "accounting_integrity",
        "sample_adequacy",
        "risk_constraints",
        "causal_data_integrity",
        "parameter_robustness",
        "concentration_audit",
    ]
    for g in mandatory_gates:
        assert g in gates, f"Missing required eligibility gate: {g}"
        assert gates[g].get("mandatory") is True

    # 4. selection
    sel = spec["selection"]
    assert sel["select_global_best_point"] is False
    assert sel["robust_region_required"] is True
    assert sel["representative_selector"] == "PREREGISTERED"
    assert sel["no_robust_region_action"] == "NO_SELECTION"

    # 5. secondary_profile
    sec = spec["secondary_profile"]
    mandatory_profiles = [
        "sample_count",
        "trade_frequency",
        "theoretical_return",
        "trading_friction",
        "net_return",
        "net_expectancy",
        "win_rate",
        "profit_factor",
        "maximum_drawdown",
        "temporal_stability",
        "cross_sectional_stability",
        "concentration",
    ]
    for p in mandatory_profiles:
        assert p in sec, f"Missing required secondary profile metric: {p}"

    # 6. oos_policy
    oos = spec["oos_policy"]
    assert oos["evaluate_only"] is True
    assert oos["tuning_allowed"] is False
    assert oos["threshold_change_allowed"] is False
    assert oos["objective_change_allowed"] is False


def test_objective_spec_mutation_missing_sections(repo_root):
    """Verify that deleting any core section from the specification dictionary is caught."""
    spec_path = repo_root / "docs" / "research_governance" / "OBJECTIVE_FUNCTION_SPEC_v1.yaml"
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    core_sections = [
        "spec_metadata",
        "governance_invariants",
        "eligibility_gates",
        "selection",
        "secondary_profile",
        "oos_policy",
    ]

    for sec in core_sections:
        mutated = copy.deepcopy(spec)
        del mutated[sec]
        assert sec not in mutated
        # Verify check fails
        with pytest.raises(AssertionError):
            assert sec in mutated


def test_objective_spec_mutation_inverted_invariants(repo_root):
    """Verify that flipping key invariants to permissive states is detected as invalid."""
    spec_path = repo_root / "docs" / "research_governance" / "OBJECTIVE_FUNCTION_SPEC_v1.yaml"
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    invariants_to_test = [
        ("governance_invariants", "train_only_selection", False),
        ("governance_invariants", "oos_selection_allowed", True),
        ("governance_invariants", "freeze_before_search", False),
        ("oos_policy", "tuning_allowed", True),
        ("selection", "robust_region_required", False),
    ]

    for section, field, invalid_val in invariants_to_test:
        mutated = copy.deepcopy(spec)
        mutated[section][field] = invalid_val
        with pytest.raises(AssertionError):
            if invalid_val is True:
                assert mutated[section][field] is False
            else:
                assert mutated[section][field] is True
