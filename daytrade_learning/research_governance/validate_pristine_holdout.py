"""Validator for EasyStock Pristine Holdout Policy, Blinded Collection,

and One-Shot Unseal Governance.

Authority: CENTRAL_RESEARCH_GOVERNANCE
Source Classification: MODERN_GOVERNANCE_EXTENSION
Pardo Principles: Out-of-sample testing, walk-forward integrity, overfitting controls
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from daytrade_learning.research_governance.validate_oos_consumption import (
    DatasetRegistry,
    parse_date,
)

ADMIN_METADATA_WHITELIST = {
    "file_existence",
    "ingestion_success",
    "schema_version",
    "checksum",
    "trading_calendar_membership",
}

PROHIBITED_MARKET_DATA_CHECKS = {
    "ohlcv_values",
    "row_count_activity_statistics",
    "feature_values",
    "feature_distributions",
    "labels",
    "signals",
    "candidate_outputs",
    "pnl",
    "returns",
    "aggregate_metrics",
    "subgroup_metrics",
}

PROHIBITED_DAY_SELECTION_CRITERIA = {
    "trading_volume",
    "volume",
    "stock_pool_symbol_count",
    "symbol_count",
    "f01_calculability",
    "signal_count",
    "market_activity_level",
    "activity_level",
    "market_return",
    "return",
    "market_volatility",
    "volatility",
    "candidate_performance",
    "performance",
}

VALID_LIFECYCLE_STATES = {
    "RESERVED_UNTOUCHED",
    "COLLECTING_BLINDED",
    "READY_TO_UNSEAL",
    "UNSEALED_FOR_CONFIRMATION",
    "CONFIRMATION_COMPLETED",
    "CONSUMED",
    "INVALIDATED",
}

PRISTINE_STATES = {
    "RESERVED_UNTOUCHED",
    "COLLECTING_BLINDED",
    "READY_TO_UNSEAL",
}

VALID_STATE_TRANSITIONS = {
    "RESERVED_UNTOUCHED": {"COLLECTING_BLINDED", "INVALIDATED"},
    "COLLECTING_BLINDED": {"READY_TO_UNSEAL", "INVALIDATED", "CONSUMED"},
    "READY_TO_UNSEAL": {"UNSEALED_FOR_CONFIRMATION", "INVALIDATED"},
    "UNSEALED_FOR_CONFIRMATION": {"CONFIRMATION_COMPLETED", "INVALIDATED"},
    "CONFIRMATION_COMPLETED": {"CONSUMED", "INVALIDATED"},
    "CONSUMED": set(),
    "INVALIDATED": set(),
}

REQUIRED_FREEZE_HASH_FIELDS = [
    "authorization_id",
    "authorized_at",
    "authorized_by",
    "trial_id",
    "objective_spec_hash",
    "trial_preregistration_hash",
    "dataset_registry_hash",
    "pre_unseal_oos_consumption_ledger_hash",
    "holdout_policy_hash",
    "code_commit_sha",
    "cost_model_hash",
    "evaluation_plan_hash",
]

CONFIRMATION_VOCABULARY = {
    "SUPPORTED_WITHIN_PREREGISTERED_SCOPE",
    "NOT_SUPPORTED",
    "INCONCLUSIVE",
    "INVALIDATED",
}


class PristineHoldoutValidator:
    """Validates holdout records against Pristine Holdout Policy specifications."""

    def __init__(
        self,
        registry: DatasetRegistry,
        authoritative_consumption_events: Optional[List[Dict[str, Any]]] = None,
        ledgers_dir: Optional[str] = "docs/research_governance/oos_consumption",
    ):
        self.registry = registry
        self.authoritative_consumption_events: Dict[str, Dict[str, Any]] = {}

        if authoritative_consumption_events is not None:
            if isinstance(authoritative_consumption_events, dict):
                for k, ev in authoritative_consumption_events.items():
                    c_id = ev.get("consumption_id") or k
                    self.authoritative_consumption_events[c_id] = ev
            elif isinstance(authoritative_consumption_events, list):
                for ev in authoritative_consumption_events:
                    c_id = ev.get("consumption_id")
                    if c_id:
                        self.authoritative_consumption_events[c_id] = ev
        elif ledgers_dir and os.path.exists(ledgers_dir):
            for fname in os.listdir(ledgers_dir):
                if fname.endswith(".yaml") or fname.endswith(".yml"):
                    p = os.path.join(ledgers_dir, fname)
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            d = yaml.safe_load(f) or {}
                        for ev in d.get("consumption_events", []):
                            c_id = ev.get("consumption_id")
                            if c_id:
                                self.authoritative_consumption_events[c_id] = ev
                    except Exception:
                        pass

    def validate_single_holdout(
        self,
        record: Dict[str, Any],
        seen_holdout_ids: Optional[Set[str]] = None,
        authoritative_events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Validate a single holdout configuration record."""
        errors: List[str] = []
        h_id = record.get("holdout_id")
        if not h_id:
            errors.append("Missing required field: holdout_id")
            return errors

        # 1. holdout_id format and uniqueness
        if not re.match(r"^[A-Z0-9_]+$", str(h_id)):
            errors.append(f"Invalid holdout_id format: '{h_id}'. Must match ^[A-Z0-9_]+$")
        if seen_holdout_ids is not None:
            if h_id in seen_holdout_ids:
                errors.append(f"Duplicate holdout_id detected: '{h_id}'")
            seen_holdout_ids.add(h_id)

        # 2. Schema version
        schema_ver = record.get("schema_version")
        if schema_ver != "PRISTINE_HOLDOUT_POLICY_v1":
            errors.append(f"[{h_id}] Invalid schema_version: '{schema_ver}'. Expected 'PRISTINE_HOLDOUT_POLICY_v1'")

        # 3. Dataset Identity & Lineage Integrity via Central Registry
        ds_id = record.get("dataset_id")
        if not ds_id or not self.registry.contains(ds_id):
            errors.append(f"[{h_id}] dataset_id '{ds_id}' not found in Central Dataset Registry")
            return errors

        reg_info = self.registry.get(ds_id)
        assert reg_info is not None
        reg_family = reg_info.get("dataset_family_id")
        reg_lineage = reg_info.get("dataset_lineage_id")

        rec_family = record.get("dataset_family_id")
        rec_lineage = record.get("dataset_lineage_id")

        if rec_family != reg_family:
            errors.append(
                f"[{h_id}] dataset_family_id mismatch for '{ds_id}': record specifies '{rec_family}' "
                f"but registry authoritative value is '{reg_family}'"
            )
        if rec_lineage != reg_lineage:
            errors.append(
                f"[{h_id}] dataset_lineage_id mismatch for '{ds_id}': record specifies '{rec_lineage}' "
                f"but registry authoritative value is '{reg_lineage}'"
            )

        # 4. Lifecycle state and valid transitions
        lifecycle = record.get("lifecycle", {}) or {}
        curr_status = lifecycle.get("status") or record.get("status")
        if not curr_status or curr_status not in VALID_LIFECYCLE_STATES:
            errors.append(f"[{h_id}] Invalid lifecycle status: '{curr_status}'")
            return errors

        history = lifecycle.get("history", []) or []
        if history:
            # Lifecycle history consistency: lifecycle.status must equal lifecycle.history[-1].state
            last_state = history[-1].get("state")
            if curr_status != last_state:
                errors.append(
                    f"[{h_id}] Lifecycle status mismatch: "
                    f"status is '{curr_status}', but last history state is '{last_state}'"
                )

            # Check sequential state transition validity
            for i in range(len(history) - 1):
                s_from = history[i].get("state")
                s_to = history[i + 1].get("state")
                if s_from in VALID_STATE_TRANSITIONS:
                    if s_to not in VALID_STATE_TRANSITIONS[s_from]:
                        errors.append(
                            f"[{h_id}] Invalid state transition: from '{s_from}' to '{s_to}' in lifecycle history"
                        )

            # Check No Re-Pristining: if any prior state was unsealed or non-pristine,
            # it cannot transition back to a pristine state.
            seen_unsealed = False
            for step in history:
                st = step.get("state")
                if st in ("UNSEALED_FOR_CONFIRMATION", "CONFIRMATION_COMPLETED", "CONSUMED"):
                    seen_unsealed = True
                if seen_unsealed and st in PRISTINE_STATES:
                    errors.append(
                        f"[{h_id}] Re-pristining violation: holdout previously in unsealed state '{st}' "
                        "cannot transition back to pristine status"
                    )

        if curr_status in PRISTINE_STATES:
            for step in history:
                if step.get("state") in ("UNSEALED_FOR_CONFIRMATION", "CONFIRMATION_COMPLETED", "CONSUMED"):
                    errors.append(
                        f"[{h_id}] Re-pristining violation: current status is '{curr_status}' "
                        "but history reveals it was previously unsealed"
                    )

        # 5. Partition Definition & Eligibility Rules
        part = record.get("partition_definition", {}) or {}
        start_rule = part.get("start_rule")
        exp_start = part.get("expected_start_date")
        sel_rule = part.get("selection_rule")
        end_date = part.get("holdout_end_date")
        target_days = part.get("target_eligible_days", 60)
        days_collected = part.get("eligible_days_collected", 0)

        # Start date must be strictly after 2026-10-02
        if exp_start:
            exp_d = parse_date(exp_start)
            if exp_d and exp_d <= datetime.date(2026, 10, 2):
                errors.append(
                    f"[{h_id}] expected_start_date '{exp_start}' must be strictly after 2026-10-02"
                )

        if sel_rule != "FIRST_60_ELIGIBLE_TRADING_DAYS":
            errors.append(
                f"[{h_id}] Invalid selection_rule: '{sel_rule}'. Expected 'FIRST_60_ELIGIBLE_TRADING_DAYS'"
            )

        # Incomplete collection cannot fix calendar end date
        if days_collected < target_days and end_date is not None:
            errors.append(
                f"[{h_id}] holdout_end_date must remain null until all {target_days} eligible days are collected; got '{end_date}'"
            )

        # Eligibility preregistration checks (no outcome-dependent skipping)
        elig = record.get("eligibility_preregistration", {}) or {}
        criteria = elig.get("criteria", []) or []
        prohibited_criteria = elig.get("prohibited_selection_criteria", []) or []

        # Check for outcome-dependent terms in criteria
        for c in criteria:
            c_low = c.lower()
            for forbidden in PROHIBITED_DAY_SELECTION_CRITERIA:
                if forbidden in c_low and "calendar" not in c_low and "checksum" not in c_low:
                    errors.append(
                        f"[{h_id}] Outcome-dependent day selection criterion detected: '{c}'. "
                        "Holdout days cannot be skipped or selected based on performance, volume, or market activity."
                    )

        if elig.get("outcome_dependent_skipping_prohibited") is not True:
            errors.append(
                f"[{h_id}] eligibility_preregistration must declare outcome_dependent_skipping_prohibited: true"
            )

        # 6. Blinded Access Governance & Metadata Whitelist
        access = record.get("access_governance", {}) or {}
        human_access = access.get("human_outcome_access", False)
        ai_access = access.get("ai_outcome_access", False)
        auto_access = access.get("automated_research_outcome_access", False)
        perf_seen = access.get("performance_seen", False)
        meta_inspected = access.get("inspected_metadata", []) or []
        market_data_inspected = access.get("market_data_inspected", []) or []

        if curr_status in PRISTINE_STATES:
            if human_access:
                errors.append(f"[{h_id}] Human outcome access occurred while in pristine status '{curr_status}'")
            if ai_access:
                errors.append(
                    f"[{h_id}] AI outcome access occurred while in pristine status '{curr_status}'. "
                    "AI access counts strictly as exposure."
                )
            if auto_access:
                errors.append(f"[{h_id}] Automated research outcome access occurred while in pristine status '{curr_status}'")
            if perf_seen:
                errors.append(f"[{h_id}] Performance/outcome exposure detected while in pristine status '{curr_status}'")

            # Check inspected metadata whitelist
            for m in meta_inspected:
                if m not in ADMIN_METADATA_WHITELIST:
                    errors.append(
                        f"[{h_id}] Non-whitelisted metadata inspected: '{m}'. Allowed: {sorted(list(ADMIN_METADATA_WHITELIST))}"
                    )

            # Check prohibited market data
            for m in market_data_inspected:
                errors.append(
                    f"[{h_id}] Prohibited market data inspected: '{m}'. Market data inspection burns holdout."
                )

        # 7. Unseal Readiness, 60-Day Counter Rule, and Authoritative Consumption Verification
        readiness = record.get("unseal_readiness", {}) or {}
        ready_to_unseal = readiness.get("ready_to_unseal", False)
        unseal_auth = readiness.get("unseal_authorized", False)
        auth_record = readiness.get("authorization_record")
        c_event_id = readiness.get("consumption_event_id") or record.get("consumption_event_id")

        # Resolve authoritative consumption event:
        # A non-empty consumption_event_id or consumption_event_registered=true can NEVER be treated as proof
        # that the event exists. OOS Consumption Ledger is authoritative.
        events_pool: Dict[str, Dict[str, Any]] = {}
        if authoritative_events is not None:
            for ev in authoritative_events:
                eid = ev.get("consumption_id")
                if eid:
                    events_pool[eid] = ev
        else:
            events_pool = self.authoritative_consumption_events

        resolved_event = events_pool.get(c_event_id) if c_event_id else None
        has_authoritative_event = resolved_event is not None

        # Outcome Access Rule: Any outcome-bearing read strictly forbidden before consumption registration
        has_outcome_access = any([human_access, ai_access, auto_access, perf_seen]) or bool(market_data_inspected)
        if has_outcome_access:
            if curr_status in PRISTINE_STATES or not unseal_auth or not has_authoritative_event:
                errors.append(
                    f"[{h_id}] Outcome access forbidden before consumption event exists: "
                    f"holdout must have unseal authorization PASS, verified authoritative consumption event in OOS ledger, "
                    f"and atomic transition to UNSEALED_FOR_CONFIRMATION before outcome read can occur."
                )

        if ready_to_unseal:
            if days_collected < target_days:
                errors.append(
                    f"[{h_id}] ready_to_unseal=true requires exactly {target_days} eligible days collected; got {days_collected}"
                )

        if curr_status == "READY_TO_UNSEAL":
            if days_collected != target_days:
                errors.append(
                    f"[{h_id}] Status READY_TO_UNSEAL requires exactly {target_days} eligible days; got {days_collected}"
                )

        # Unseal Authorization & Freeze Hashes
        if curr_status == "UNSEALED_FOR_CONFIRMATION":
            if not unseal_auth:
                errors.append(f"[{h_id}] Status UNSEALED_FOR_CONFIRMATION requires unseal_authorized: true")
            if not auth_record or not isinstance(auth_record, dict):
                errors.append(f"[{h_id}] Status UNSEALED_FOR_CONFIRMATION requires complete authorization_record")
            else:
                for f_field in REQUIRED_FREEZE_HASH_FIELDS:
                    val = auth_record.get(f_field)
                    if not val:
                        errors.append(
                            f"[{h_id}] Missing or empty required freeze hash field '{f_field}' in authorization_record"
                        )
            # LINEAGE_UNKNOWN cannot be unsealed
            if rec_lineage == "LINEAGE_UNKNOWN":
                errors.append(f"[{h_id}] LINEAGE_UNKNOWN cannot be unsealed for independent confirmation")

            # UNSEALED state validation: requires an authoritative verified consumption event
            if not c_event_id:
                errors.append(
                    f"[{h_id}] Status UNSEALED_FOR_CONFIRMATION requires an authoritative consumption event; "
                    "consumption_event_id is missing/empty"
                )
            elif not has_authoritative_event:
                errors.append(
                    f"[{h_id}] Authoritative consumption event missing: holdout claims status UNSEALED_FOR_CONFIRMATION "
                    f"with consumption_event_id '{c_event_id}', but no corresponding event exists in the "
                    "authoritative OOS Consumption Ledger. An ID or registered boolean alone is insufficient."
                )
            else:
                # 3-way binding check between holdout, authorization, and authoritative consumption event
                ev_holdout_id = resolved_event.get("holdout_id")
                ev_auth_id = resolved_event.get("triggered_by_authorization_id")
                ev_pre_hash = resolved_event.get("pre_unseal_ledger_hash")

                auth_id = auth_record.get("authorization_id") if isinstance(auth_record, dict) else None
                auth_pre_hash = auth_record.get("pre_unseal_oos_consumption_ledger_hash") if isinstance(auth_record, dict) else None

                if ev_holdout_id != h_id:
                    errors.append(
                        f"[{h_id}] Consumption event holdout binding mismatch: event specifies holdout_id='{ev_holdout_id}', expected '{h_id}'"
                    )
                if ev_auth_id != auth_id:
                    errors.append(
                        f"[{h_id}] Consumption event authorization binding mismatch: event specifies triggered_by_authorization_id='{ev_auth_id}', expected '{auth_id}'"
                    )
                if ev_pre_hash != auth_pre_hash:
                    errors.append(
                        f"[{h_id}] Consumption event pre-unseal hash binding mismatch: event specifies pre_unseal_ledger_hash='{ev_pre_hash}', expected '{auth_pre_hash}'"
                    )

        # 8. Confirmation Contract, Result Vocabulary, and Production Isolation
        contract = record.get("confirmation_contract", {}) or {}
        conf_mode = contract.get("confirmation_mode")
        conf_completed = contract.get("independent_confirmation_completed", False)
        conf_outcome = contract.get("confirmation_outcome")
        prod_ready = contract.get("production_ready", False)

        if conf_mode != "ONE_SHOT":
            errors.append(f"[{h_id}] Invalid confirmation_mode: '{conf_mode}'. Expected 'ONE_SHOT'")

        if curr_status in PRISTINE_STATES:
            if conf_completed:
                errors.append(
                    f"[{h_id}] independent_confirmation_completed cannot be true while holdout is '{curr_status}'"
                )
            if conf_outcome is not None:
                errors.append(
                    f"[{h_id}] confirmation_outcome cannot be recorded while holdout is '{curr_status}'"
                )

        if conf_outcome is not None and conf_outcome not in CONFIRMATION_VOCABULARY:
            errors.append(
                f"[{h_id}] Invalid confirmation_outcome: '{conf_outcome}'. "
                f"Allowed vocabulary: {sorted(list(CONFIRMATION_VOCABULARY))}"
            )

        # Production Ready Invariant: strictly false
        if prod_ready is not False:
            errors.append(
                f"[{h_id}] production_ready must be strictly false. "
                "Confirmation support cannot alter production readiness."
            )

        return errors

    def validate_holdout_file(
        self,
        file_path: str,
        seen_holdout_ids: Optional[Set[str]] = None,
    ) -> Tuple[bool, List[str]]:
        """Validate a holdout YAML file on disk."""
        if not os.path.exists(file_path):
            return False, [f"File not found: {file_path}"]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            return False, [f"YAML parsing error in {file_path}: {e}"]

        errors = self.validate_single_holdout(data, seen_holdout_ids)
        return len(errors) == 0, errors


def detect_post_unseal_modifications(
    frozen_hashes: Dict[str, str],
    current_hashes: Dict[str, str],
) -> List[str]:
    """Detect if any frozen artifact (parameters, objective, code, cost model) was modified post-unseal.

    Note: pre_unseal_oos_consumption_ledger_hash represents the ledger snapshot
    BEFORE the unseal consumption event is appended. Post-unseal appends to the
    ledger are expected and do not invalidate the pre-unseal snapshot hash.
    """
    violations: List[str] = []
    for key, expected_hash in frozen_hashes.items():
        if key in ("pre_unseal_oos_consumption_ledger_hash", "oos_consumption_ledger_hash"):
            continue
        curr_val = current_hashes.get(key)
        if not curr_val:
            violations.append(f"Missing current hash for frozen asset '{key}'")
        elif curr_val != expected_hash:
            violations.append(
                f"Post-unseal modification detected for '{key}': "
                f"frozen='{expected_hash}', current='{curr_val}'. Confirmation invalidated."
            )
    return violations


def validate_atomic_unseal_transition(
    holdout_record: Dict[str, Any],
    authorization_record: Dict[str, Any],
    consumption_event_record: Dict[str, Any],
    pre_unseal_ledger_hash: str,
) -> Tuple[bool, List[str]]:
    """Pure validation of an atomic unseal transition proposal.

    Does NOT write files, append ledger files, mutate YAML, or mutate input dictionaries.
    Validates whether a future coordinator WOULD be allowed to perform the transition.
    """
    errors: List[str] = []

    # 1. Verify holdout status and readiness
    curr_status = holdout_record.get("lifecycle", {}).get("status") or holdout_record.get("status")
    if curr_status != "READY_TO_UNSEAL":
        errors.append(f"Atomic unseal proposal requires holdout status READY_TO_UNSEAL; got '{curr_status}'")

    part = holdout_record.get("partition_definition", {}) or {}
    days_collected = part.get("eligible_days_collected", 0)
    target_days = part.get("target_eligible_days", 60)
    if days_collected != target_days:
        errors.append(f"Atomic unseal proposal requires exactly {target_days} eligible days; got {days_collected}")

    readiness = holdout_record.get("unseal_readiness", {}) or {}
    holdout_c_id = readiness.get("consumption_event_id")

    # 2. Verify authorization record completeness
    if not authorization_record or not isinstance(authorization_record, dict):
        errors.append("Atomic unseal proposal requires valid authorization_record")
        return False, errors

    auth_id = authorization_record.get("authorization_id")
    auth_pre_unseal_hash = authorization_record.get("pre_unseal_oos_consumption_ledger_hash")

    for field in REQUIRED_FREEZE_HASH_FIELDS:
        if not authorization_record.get(field):
            errors.append(f"Missing required freeze hash field '{field}' in authorization_record")

    # 3. Verify function argument pre_unseal_ledger_hash matches authorization
    if pre_unseal_ledger_hash != auth_pre_unseal_hash:
        errors.append(
            f"Argument pre_unseal_ledger_hash ('{pre_unseal_ledger_hash}') does not match "
            f"authorization record pre_unseal_oos_consumption_ledger_hash ('{auth_pre_unseal_hash}')"
        )

    # 4. Verify consumption_event_record completeness & 3-way binding
    if not consumption_event_record or not isinstance(consumption_event_record, dict):
        errors.append("Atomic unseal proposal requires valid consumption_event_record")
        return False, errors

    event_c_id = consumption_event_record.get("consumption_id")
    event_holdout_id = consumption_event_record.get("holdout_id")
    event_auth_id = consumption_event_record.get("triggered_by_authorization_id")
    event_pre_hash = consumption_event_record.get("pre_unseal_ledger_hash")
    holdout_id = holdout_record.get("holdout_id")

    # Bind 1: consumption_id == holdout readiness consumption_event_id (if holdout declares one)
    if holdout_c_id and event_c_id != holdout_c_id:
        errors.append(
            f"Consumption event ID mismatch: consumption_event_record has '{event_c_id}', "
            f"but holdout readiness specifies '{holdout_c_id}'"
        )
    if not event_c_id:
        errors.append("consumption_event_record missing required consumption_id")

    # Bind 2: holdout_id == holdout_record.holdout_id
    if event_holdout_id != holdout_id:
        errors.append(
            f"Holdout ID binding failure: consumption_event_record references holdout_id '{event_holdout_id}', "
            f"expected '{holdout_id}'"
        )

    # Bind 3: triggered_by_authorization_id == authorization_record.authorization_id
    if event_auth_id != auth_id:
        errors.append(
            f"Authorization ID binding failure: consumption_event_record references "
            f"triggered_by_authorization_id '{event_auth_id}', expected '{auth_id}'"
        )

    # Bind 4: pre_unseal_ledger_hash == authorization_record.pre_unseal_oos_consumption_ledger_hash
    if event_pre_hash != auth_pre_unseal_hash:
        errors.append(
            f"Pre-unseal hash binding failure: consumption_event_record has pre_unseal_ledger_hash "
            f"'{event_pre_hash}', expected '{auth_pre_unseal_hash}'"
        )

    return len(errors) == 0, errors


def validate_all_holdouts(
    registry_path: str,
    holdouts_dir: str,
) -> Tuple[bool, Dict[str, Tuple[bool, List[str]]]]:
    """Validate all holdout files in the holdouts directory."""
    registry = DatasetRegistry(registry_path)
    validator = PristineHoldoutValidator(registry)

    results: Dict[str, Tuple[bool, List[str]]] = {}
    seen_ids: Set[str] = set()

    if not os.path.exists(holdouts_dir):
        return False, {"directory": (False, [f"Holdouts directory not found: {holdouts_dir}"])}

    files = sorted([f for f in os.listdir(holdouts_dir) if f.endswith(".yaml") or f.endswith(".yml")])
    all_passed = True

    for filename in files:
        full_path = os.path.join(holdouts_dir, filename)
        passed, errors = validator.validate_holdout_file(full_path, seen_ids)
        results[filename] = (passed, errors)
        if not passed:
            all_passed = False

    return all_passed, results


def main() -> int:
    """CLI Entry point for Pristine Holdout Policy validator."""
    parser = argparse.ArgumentParser(description="EasyStock Pristine Holdout Policy Validator v1")
    parser.add_argument(
        "--registry",
        default="docs/research_governance/DATASET_REGISTRY_v1.yaml",
        help="Path to DATASET_REGISTRY_v1.yaml",
    )
    parser.add_argument(
        "--holdouts-dir",
        default="docs/research_governance/holdouts",
        help="Directory containing holdout configuration files",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("EasyStock Research Governance — Pristine Holdout Policy Validator v1")
    print("=" * 70)
    print(f"Registry:     {args.registry}")
    print(f"Holdouts Dir: {args.holdouts_dir}")
    print("-" * 70)

    try:
        registry = DatasetRegistry(args.registry)
        print(f"Loaded Central Dataset Registry with {len(registry.datasets)} datasets.")
    except Exception as e:
        print(f"ERROR loading registry: {e}")
        return 1

    print("-" * 70)
    print(f"{'FILE / ARTIFACT':<40} {'STATUS':<12} {'DETAILS'}")
    print("-" * 70)

    all_passed, results = validate_all_holdouts(args.registry, args.holdouts_dir)

    for filename, (passed, errors) in results.items():
        status_str = "PASS" if passed else "FAIL"
        details_str = "All rules satisfied" if passed else "; ".join(errors)
        print(f"{filename:<40} {status_str:<12} {details_str}")

    print("-" * 70)
    # Detailed Holdout Inventory Summary
    for filename in sorted(os.listdir(args.holdouts_dir)):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            p = os.path.join(args.holdouts_dir, filename)
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            h_id = d.get("holdout_id")
            st = d.get("lifecycle", {}).get("status") or d.get("status")
            part = d.get("partition_definition", {}) or {}
            acc = d.get("access_governance", {}) or {}
            readiness = d.get("unseal_readiness", {}) or {}
            contract = d.get("confirmation_contract", {}) or {}

            print(f"HOLDOUT_ID:                          {h_id}")
            print(f"HOLDOUT_STATUS:                      {st}")
            print(f"SELECTION_RULE:                      {part.get('selection_rule')}")
            print(f"EXPECTED_START_DATE:                 {part.get('expected_start_date')}")
            print(f"ELIGIBLE_DAYS_COLLECTED:             {part.get('eligible_days_collected')}")
            print(f"OUTCOME_ACCESS_OCCURRED:             {acc.get('performance_seen')}")
            print(f"HUMAN_OUTCOME_ACCESS:                {acc.get('human_outcome_access')}")
            print(f"AI_OUTCOME_ACCESS:                   {acc.get('ai_outcome_access')}")
            print(f"READY_TO_UNSEAL:                     {readiness.get('ready_to_unseal')}")
            print(f"UNSEAL_AUTHORIZED:                   {readiness.get('unseal_authorized')}")
            print(f"INDEPENDENT_CONFIRMATION_COMPLETED:  {contract.get('independent_confirmation_completed')}")
            print(f"PRODUCTION_READY:                    {contract.get('production_ready')}")

    print("-" * 70)
    if all_passed:
        print("RESULT: ALL PRISTINE HOLDOUT CONFIGURATIONS PASSED VALIDATION.")
        print("Blinded isolation, unseal contracts, and freeze hash rules intact.")
        return 0
    else:
        print("RESULT: VALIDATION FAILED WITH GOVERNANCE INTEGRITY BREACHES.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
