"""
EasyStock Research Governance — Trial Ledger Validator v1
Validates research trial ledger records against the schema and governance rules.
Supports dataset- and slice-scoped exposure tracking and Pardo degrees-of-freedom invariants.
Includes dataset lineage anti-bypass protection and future confirmation reservation semantics.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

# Permitted enumeration values
ALLOWED_RESEARCH_STAGES = {
    "PHASE_2A",
    "PHASE_2B_BATCH_1",
    "PHASE_2B_BATCH_2",
    "PHASE_2C",
    "PHASE_2D",
    "PHASE_3",
    "EXPLORATORY",
}

ALLOWED_RECORD_TYPES = {
    "PREREGISTERED_TRIAL",
    "LEGACY_BACKFILL",
    "EXPLORATORY_SPIKE",
}

ALLOWED_SOURCE_CLASSIFICATIONS = {
    "SOURCE_VERIFIED_LITERATURE",
    "CANONICAL_INTERNAL_PRIMITIVE",
    "EXPLORATORY_HEURISTIC",
    "HISTORICAL_REUSE",
}

ALLOWED_DIRECTIONS = {
    "MAXIMIZE",
    "MINIMIZE",
    "PASS_FAIL",
    "MECHANISM_EXPLANATION",
    "DESCRIPTIVE",
}

ALLOWED_STATUSES = {
    "SEALED",
    "REJECTED",
    "SUPERSEDED",
    "IN_PROGRESS",
    "DATA_INSUFFICIENT",
}

ALLOWED_EXPOSURE_ROLES = {
    "TRAIN",
    "VALIDATION",
    "OOS",
    "HOLDOUT",
    "DESCRIPTIVE",
}

ALLOWED_CONFIRMATION_STATUSES = {
    "RESERVED_UNTOUCHED",
    "IN_PROGRESS",
    "COMPLETED",
    "ABANDONED",
}

TRIAL_ID_PATTERN = re.compile(r"^TRIAL_[A-Z0-9_]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TrialLedgerValidationError(Exception):
    """Raised when a trial ledger fails validation."""
    pass


class TrialLedgerValidator:
    """Validator for EasyStock Research Trial Ledger files and directory collections."""

    def __init__(self, trials_dir: Optional[Path] = None):
        if trials_dir is None:
            # Default to docs/research_governance/trials relative to repo root
            repo_root = Path(__file__).resolve().parents[2]
            trials_dir = repo_root / "docs" / "research_governance" / "trials"
        self.trials_dir = Path(trials_dir)

    @staticmethod
    def _is_valid_date(val: Any) -> bool:
        if isinstance(val, (datetime.date, datetime.datetime)):
            return True
        if isinstance(val, str) and DATE_PATTERN.match(val):
            try:
                datetime.date.fromisoformat(val)
                return True
            except ValueError:
                return False
        return False

    @staticmethod
    def _to_date_str(val: Any) -> Optional[str]:
        if val is None:
            return None
        if isinstance(val, (datetime.date, datetime.datetime)):
            return val.strftime("%Y-%m-%d")
        return str(val).strip()

    def validate_schema(self, trial: Dict[str, Any], trial_ref: str = "") -> List[str]:
        """Check required fields, types, and schema patterns."""
        errors: List[str] = []
        prefix = f"[{trial_ref}] " if trial_ref else ""

        required_root_keys = [
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

        for k in required_root_keys:
            if k not in trial:
                errors.append(f"{prefix}Missing required top-level field: '{k}'")

        if errors:
            return errors

        # trial_id
        tid = trial.get("trial_id")
        if not isinstance(tid, str) or not TRIAL_ID_PATTERN.match(tid):
            errors.append(
                f"{prefix}Invalid trial_id '{tid}': must match pattern ^TRIAL_[A-Z0-9_]+$"
            )

        # parent_trial_id
        pid = trial.get("parent_trial_id")
        if pid is not None and not isinstance(pid, str):
            errors.append(f"{prefix}parent_trial_id must be a string or null (None)")

        # research_stage
        stage = trial.get("research_stage")
        if stage not in ALLOWED_RESEARCH_STAGES:
            errors.append(
                f"{prefix}Invalid research_stage '{stage}': must be one of {sorted(ALLOWED_RESEARCH_STAGES)}"
            )

        # ledger_record_type
        rtype = trial.get("ledger_record_type")
        if rtype not in ALLOWED_RECORD_TYPES:
            errors.append(
                f"{prefix}Invalid ledger_record_type '{rtype}': must be one of {sorted(ALLOWED_RECORD_TYPES)}"
            )

        # recorded_after_experiment
        if not isinstance(trial.get("recorded_after_experiment"), bool):
            errors.append(f"{prefix}recorded_after_experiment must be a boolean")

        # provenance
        prov = trial.get("provenance")
        if not isinstance(prov, dict):
            errors.append(f"{prefix}provenance must be a dictionary")
        else:
            sclass = prov.get("source_classification")
            if sclass not in ALLOWED_SOURCE_CLASSIFICATIONS:
                errors.append(
                    f"{prefix}Invalid provenance.source_classification '{sclass}': "
                    f"must be one of {sorted(ALLOWED_SOURCE_CLASSIFICATIONS)}"
                )
            srefs = prov.get("source_refs")
            if not isinstance(srefs, list) or len(srefs) == 0:
                errors.append(f"{prefix}provenance.source_refs must be a non-empty list of strings")

        # hypothesis
        hypo = trial.get("hypothesis")
        if not isinstance(hypo, dict):
            errors.append(f"{prefix}hypothesis must be a dictionary")
        else:
            for hk in ["statement", "preregistered", "exploratory"]:
                if hk not in hypo:
                    errors.append(f"{prefix}hypothesis missing required field '{hk}'")
            if "statement" in hypo and not isinstance(hypo["statement"], str):
                errors.append(f"{prefix}hypothesis.statement must be a string")
            if "preregistered" in hypo and not isinstance(hypo["preregistered"], bool):
                errors.append(f"{prefix}hypothesis.preregistered must be a boolean")
            if "exploratory" in hypo and not isinstance(hypo["exploratory"], bool):
                errors.append(f"{prefix}hypothesis.exploratory must be a boolean")

        # objective
        obj = trial.get("objective")
        if not isinstance(obj, dict):
            errors.append(f"{prefix}objective must be a dictionary")
        else:
            for ok in ["spec_version", "primary_metric", "direction", "baseline", "frozen_before_search"]:
                if ok not in obj:
                    errors.append(f"{prefix}objective missing required field '{ok}'")
            odir = obj.get("direction")
            if odir not in ALLOWED_DIRECTIONS:
                errors.append(
                    f"{prefix}Invalid objective.direction '{odir}': must be one of {sorted(ALLOWED_DIRECTIONS)}"
                )
            if not isinstance(obj.get("frozen_before_search"), bool):
                errors.append(f"{prefix}objective.frozen_before_search must be a boolean")

        # data
        data = trial.get("data")
        if not isinstance(data, dict):
            errors.append(f"{prefix}data must be a dictionary")
        else:
            for dk in ["dataset_id", "start_date", "end_date", "universe", "discovery_data_reused", "independent_confirmation"]:
                if dk not in data:
                    errors.append(f"{prefix}data missing required field '{dk}'")
            if not self._is_valid_date(data.get("start_date")):
                errors.append(f"{prefix}data.start_date is not a valid ISO date (YYYY-MM-DD)")
            if not self._is_valid_date(data.get("end_date")):
                errors.append(f"{prefix}data.end_date is not a valid ISO date (YYYY-MM-DD)")
            if not isinstance(data.get("discovery_data_reused"), bool):
                errors.append(f"{prefix}data.discovery_data_reused must be a boolean")
            if not isinstance(data.get("independent_confirmation"), bool):
                errors.append(f"{prefix}data.independent_confirmation must be a boolean")

        # exposure_state
        expo = trial.get("exposure_state")
        if not isinstance(expo, dict):
            errors.append(f"{prefix}exposure_state must be a dictionary")
        else:
            for ek in ["train_seen", "validation_seen", "oos_seen", "future_holdout_seen", "exposures"]:
                if ek not in expo:
                    errors.append(f"{prefix}exposure_state missing required field '{ek}'")
            for ek in ["train_seen", "validation_seen", "oos_seen", "future_holdout_seen"]:
                if ek in expo and not isinstance(expo.get(ek), bool):
                    errors.append(f"{prefix}exposure_state.{ek} must be a boolean")

            exposures = expo.get("exposures")
            if not isinstance(exposures, list):
                errors.append(f"{prefix}exposure_state.exposures must be a list of exposure records")
            else:
                for idx, exp_item in enumerate(exposures):
                    if not isinstance(exp_item, dict):
                        errors.append(f"{prefix}exposure_state.exposures[{idx}] must be a dictionary")
                        continue
                    for req_exp_k in ["exposure_id", "dataset_id", "start_date", "role", "seen", "exposed_dimensions", "source_trial_id", "first_seen_at"]:
                        if req_exp_k not in exp_item:
                            errors.append(f"{prefix}exposure_state.exposures[{idx}] missing '{req_exp_k}'")
                    if "role" in exp_item and exp_item["role"] not in ALLOWED_EXPOSURE_ROLES:
                        errors.append(
                            f"{prefix}exposure_state.exposures[{idx}].role '{exp_item['role']}' "
                            f"must be one of {sorted(ALLOWED_EXPOSURE_ROLES)}"
                        )
                    if "seen" in exp_item and not isinstance(exp_item["seen"], bool):
                        errors.append(f"{prefix}exposure_state.exposures[{idx}].seen must be a boolean")
                    if not self._is_valid_date(exp_item.get("start_date")):
                        errors.append(f"{prefix}exposure_state.exposures[{idx}].start_date must be valid date")
                    if exp_item.get("end_date") is not None and not self._is_valid_date(exp_item.get("end_date")):
                        errors.append(f"{prefix}exposure_state.exposures[{idx}].end_date must be valid date or null")

        # confirmation_claim (optional)
        claim = trial.get("confirmation_claim")
        if claim is not None:
            if not isinstance(claim, dict):
                errors.append(f"{prefix}confirmation_claim must be a dictionary if specified")
            else:
                for ck in ["dataset_id", "start_date", "role"]:
                    if ck not in claim:
                        errors.append(f"{prefix}confirmation_claim missing required field '{ck}'")
                if not self._is_valid_date(claim.get("start_date")):
                    errors.append(f"{prefix}confirmation_claim.start_date must be valid date")
                if claim.get("end_date") is not None and not self._is_valid_date(claim.get("end_date")):
                    errors.append(f"{prefix}confirmation_claim.end_date must be valid date or null")
                if "confirmation_status" in claim:
                    cstatus = claim.get("confirmation_status")
                    if cstatus not in ALLOWED_CONFIRMATION_STATUSES:
                        errors.append(
                            f"{prefix}Invalid confirmation_claim.confirmation_status '{cstatus}': "
                            f"must be one of {sorted(ALLOWED_CONFIRMATION_STATUSES)}"
                        )
                if "performance_seen" in claim and not isinstance(claim.get("performance_seen"), bool):
                    errors.append(f"{prefix}confirmation_claim.performance_seen must be a boolean")
                if "independent_confirmation_completed" in claim and not isinstance(claim.get("independent_confirmation_completed"), bool):
                    errors.append(f"{prefix}confirmation_claim.independent_confirmation_completed must be a boolean")
                if "intended_independent_confirmation" in claim and not isinstance(claim.get("intended_independent_confirmation"), bool):
                    errors.append(f"{prefix}confirmation_claim.intended_independent_confirmation must be a boolean")
                if "independent_confirmation" in claim and not isinstance(claim.get("independent_confirmation"), bool):
                    errors.append(f"{prefix}confirmation_claim.independent_confirmation must be a boolean")

        # search
        search = trial.get("search")
        if not isinstance(search, dict):
            errors.append(f"{prefix}search must be a dictionary")
        else:
            for sk in ["parameters_searched", "search_space", "trial_count", "post_hoc_changes"]:
                if sk not in search:
                    errors.append(f"{prefix}search missing required field '{sk}'")
            if not isinstance(search.get("parameters_searched"), list):
                errors.append(f"{prefix}search.parameters_searched must be a list")
            t_count = search.get("trial_count")
            if t_count is not None and (not isinstance(t_count, int) or t_count < 0):
                errors.append(f"{prefix}search.trial_count must be a non-negative integer or null")
            if not isinstance(search.get("post_hoc_changes"), bool):
                errors.append(f"{prefix}search.post_hoc_changes must be a boolean")

        # governance
        gov = trial.get("governance")
        if not isinstance(gov, dict):
            errors.append(f"{prefix}governance must be a dictionary")
        else:
            for gk in ["plan_hash", "registry_hash", "no_oos_tuning", "production_effect"]:
                if gk not in gov:
                    errors.append(f"{prefix}governance missing required field '{gk}'")
            if not isinstance(gov.get("no_oos_tuning"), bool):
                errors.append(f"{prefix}governance.no_oos_tuning must be a boolean")

        # result
        res = trial.get("result")
        if not isinstance(res, dict):
            errors.append(f"{prefix}result must be a dictionary")
        else:
            for rk in ["status", "decision", "sealed_commit", "notes"]:
                if rk not in res:
                    errors.append(f"{prefix}result missing required field '{rk}'")
            rstatus = res.get("status")
            if rstatus not in ALLOWED_STATUSES:
                errors.append(
                    f"{prefix}Invalid result.status '{rstatus}': must be one of {sorted(ALLOWED_STATUSES)}"
                )

        return errors

    def _collect_ancestor_exposures(
        self, trial: Dict[str, Any], all_trials: Optional[Dict[str, Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Collect all exposures from current trial and its ancestor lineage."""
        exposures: List[Dict[str, Any]] = []
        # Current trial exposures
        cur_exposures = trial.get("exposure_state", {}).get("exposures", [])
        if isinstance(cur_exposures, list):
            exposures.extend(cur_exposures)

        if all_trials:
            parent_id = trial.get("parent_trial_id")
            visited = {trial.get("trial_id")}
            while parent_id and parent_id in all_trials and parent_id not in visited:
                visited.add(parent_id)
                parent_trial = all_trials[parent_id]
                p_exps = parent_trial.get("exposure_state", {}).get("exposures", [])
                if isinstance(p_exps, list):
                    exposures.extend(p_exps)
                parent_id = parent_trial.get("parent_trial_id")

        return exposures

    def validate_semantics(
        self,
        trial: Dict[str, Any],
        all_trials: Optional[Dict[str, Dict[str, Any]]] = None,
        trial_ref: str = "",
    ) -> List[str]:
        """Validate research governance business logic and semantic invariants."""
        errors: List[str] = []
        prefix = f"[{trial_ref}] " if trial_ref else ""

        # Rule 5: Data dates valid (start_date <= end_date)
        data = trial.get("data", {})
        s_date_val = data.get("start_date")
        e_date_val = data.get("end_date")
        if self._is_valid_date(s_date_val) and self._is_valid_date(e_date_val):
            s_date = self._to_date_str(s_date_val)
            e_date = self._to_date_str(e_date_val)
            if s_date > e_date:
                errors.append(
                    f"{prefix}Invalid date range: start_date ({s_date}) > end_date ({e_date})"
                )

        # Rule 6: Objective non-empty
        obj = trial.get("objective", {})
        p_metric = obj.get("primary_metric")
        if not isinstance(p_metric, str) or not p_metric.strip():
            errors.append(f"{prefix}objective.primary_metric cannot be empty")
        s_ver = obj.get("spec_version")
        if not isinstance(s_ver, str) or not s_ver.strip():
            errors.append(f"{prefix}objective.spec_version cannot be empty")

        # Rule 7: Preregistered vs Exploratory consistency
        hypo = trial.get("hypothesis", {})
        is_prereg = hypo.get("preregistered", False)
        is_exploratory = hypo.get("exploratory", False)
        if is_prereg and is_exploratory:
            errors.append(
                f"{prefix}Contradictory hypothesis: cannot be both preregistered=True and exploratory=True"
            )

        # Rule 9: Zero production effect: production_effect must strictly be "NONE"
        gov = trial.get("governance", {})
        prod_eff = gov.get("production_effect")
        if prod_eff != "NONE":
            errors.append(
                f"{prefix}Governance violation: governance.production_effect must strictly be 'NONE', got '{prod_eff}'"
            )

        # Rule 10: Legacy backfill integrity
        record_type = trial.get("ledger_record_type")
        recorded_after = trial.get("recorded_after_experiment")
        if record_type == "LEGACY_BACKFILL":
            if not recorded_after:
                errors.append(
                    f"{prefix}Anti-historical revisionism violation: LEGACY_BACKFILL must have recorded_after_experiment=True"
                )

        # Rule 4: Sealed trial immutability & commit presence
        res = trial.get("result", {})
        if res.get("status") == "SEALED":
            commit = res.get("sealed_commit")
            if not commit or not isinstance(commit, str) or not commit.strip():
                errors.append(
                    f"{prefix}Governance violation: SEALED trial must have a valid non-empty sealed_commit hash"
                )

        # Rule 3: Lineage check against all_trials
        if all_trials is not None:
            pid = trial.get("parent_trial_id")
            if pid is not None:
                if pid not in all_trials:
                    errors.append(
                        f"{prefix}Invalid parent_trial_id '{pid}': parent trial does not exist in ledger"
                    )

        # ======================================================================
        # Future Confirmation Reservation Semantics
        # ======================================================================
        claim = trial.get("confirmation_claim")
        data_claim = data.get("independent_confirmation", False)

        if claim:
            cstatus = claim.get("confirmation_status")
            pseen = claim.get("performance_seen", False)
            completed = claim.get("independent_confirmation_completed", False)
            # Untouched future claim is not completed confirmation
            if cstatus == "RESERVED_UNTOUCHED":
                if pseen is True:
                    errors.append(
                        f"{prefix}Governance violation: confirmation_claim has confirmation_status=RESERVED_UNTOUCHED, so performance_seen must be False"
                    )
                if completed is True:
                    errors.append(
                        f"{prefix}Governance violation: confirmation_claim has confirmation_status=RESERVED_UNTOUCHED, so independent_confirmation_completed cannot be True"
                    )

        # ======================================================================
        # Scoped Exposure and Anti-Bypass Lineage Validation
        # ======================================================================
        claims_to_check: List[Tuple[str, Optional[str], Optional[str], str, Optional[str]]] = []
        if claim:
            is_active_claim = (
                claim.get("intended_independent_confirmation") is True
                or claim.get("independent_confirmation") is True
                or claim.get("independent_confirmation_completed") is True
            )
            if is_active_claim:
                c_ds = claim.get("dataset_id")
                c_family = claim.get("dataset_family_id") or data.get("dataset_family_id")
                c_lineage = claim.get("dataset_lineage_id") or data.get("dataset_lineage_id")
                c_start = self._to_date_str(claim.get("start_date"))
                c_end = self._to_date_str(claim.get("end_date"))
                if c_ds and c_start:
                    claims_to_check.append((c_ds, c_family, c_lineage, c_start, c_end))

        if data_claim and not claim:
            d_ds = data.get("dataset_id")
            d_family = data.get("dataset_family_id")
            d_lineage = data.get("dataset_lineage_id")
            d_start = self._to_date_str(data.get("start_date"))
            d_end = self._to_date_str(data.get("end_date"))
            if d_ds and d_start:
                claims_to_check.append((d_ds, d_family, d_lineage, d_start, d_end))

        all_exposures = self._collect_ancestor_exposures(trial, all_trials)

        for c_ds, c_family, c_lineage, c_start, c_end in claims_to_check:
            # Rule 6: Open-ended future confirmation contract check
            if c_end is None:
                untouched = (
                    res.get("FUTURE_CONFIRMATION_UNTOUCHED") is True
                    or trial.get("future_confirmation_untouched") is True
                    or (claim and claim.get("confirmation_status") == "RESERVED_UNTOUCHED")
                )
                if not untouched:
                    errors.append(
                        f"{prefix}Governance violation: open-ended confirmation slice ({c_start} to null) "
                        f"must have FUTURE_CONFIRMATION_UNTOUCHED=true"
                    )

            # Check overlap against all seen exposures
            for exp in all_exposures:
                if not exp.get("seen", False):
                    continue

                exp_ds = exp.get("dataset_id")
                exp_family = exp.get("dataset_family_id")
                exp_lineage = exp.get("dataset_lineage_id")
                exp_start = self._to_date_str(exp.get("start_date"))
                exp_end = self._to_date_str(exp.get("end_date"))
                exp_role = exp.get("role", "UNKNOWN")

                # Anti-bypass identity check:
                # Same dataset_id OR same dataset_family_id OR same dataset_lineage_id
                is_same_source = (
                    (exp_ds == c_ds)
                    or (bool(c_family) and bool(exp_family) and c_family == exp_family)
                    or (bool(c_lineage) and bool(exp_lineage) and c_lineage == exp_lineage)
                )

                if is_same_source and exp_start:
                    # Calculate date overlap between [c_start, c_end] and [exp_start, exp_end]
                    overlap = False
                    if c_end is not None and exp_end is not None:
                        overlap = (c_start <= exp_end) and (c_end >= exp_start)
                    elif c_end is None and exp_end is not None:
                        overlap = (c_start <= exp_end)
                    elif c_end is not None and exp_end is None:
                        overlap = (c_end >= exp_start)
                    else:  # both open-ended
                        overlap = True

                    if overlap:
                        alias_info = ""
                        if exp_ds != c_ds:
                            alias_info = f" (aliased from '{exp_ds}' via family='{c_family}'/lineage='{c_lineage}')"
                        if exp_role in ("HOLDOUT", "OOS"):
                            errors.append(
                                f"{prefix}Governance violation: confirmation slice [{c_start}, {c_end or 'open'}] "
                                f"overlaps with previously seen {exp_role} slice [{exp_start}, {exp_end or 'open'}] "
                                f"on dataset '{c_ds}'{alias_info}. Previously seen {exp_role} data cannot be claimed as independent confirmation."
                            )
                        else:
                            errors.append(
                                f"{prefix}Governance violation: confirmation slice [{c_start}, {c_end or 'open'}] "
                                f"overlaps with exposed {exp_role} slice [{exp_start}, {exp_end or 'open'}] (seen=True) "
                                f"on dataset '{c_ds}'{alias_info}. Cannot claim independent confirmation."
                            )

        return errors

    def validate_single_trial(
        self,
        trial: Dict[str, Any],
        all_trials: Optional[Dict[str, Dict[str, Any]]] = None,
        trial_ref: str = "",
    ) -> List[str]:
        """Run all schema and semantic validations on a single trial."""
        schema_errors = self.validate_schema(trial, trial_ref=trial_ref)
        if schema_errors:
            return schema_errors
        return self.validate_semantics(trial, all_trials=all_trials, trial_ref=trial_ref)

    def validate_ledger_directory(
        self, directory: Optional[Path] = None
    ) -> Tuple[bool, Dict[str, List[str]]]:
        """Validate all trial YAML files in directory including cross-trial invariants."""
        target_dir = Path(directory or self.trials_dir)
        results: Dict[str, List[str]] = {}

        if not target_dir.exists() or not target_dir.is_dir():
            results["[SYSTEM]"] = [f"Directory not found: {target_dir}"]
            return False, results

        yaml_files = sorted(list(target_dir.glob("*.yaml")) + list(target_dir.glob("*.yml")))
        if not yaml_files:
            results["[SYSTEM]"] = [f"No YAML trial files found in {target_dir}"]
            return False, results

        # 1. Load all trials
        loaded_trials: Dict[str, Dict[str, Any]] = {}
        file_map: Dict[str, Path] = {}
        duplicate_errors: List[str] = []

        for yf in yaml_files:
            rel_name = yf.name
            try:
                with open(yf, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                results[rel_name] = [f"YAML parsing error: {e}"]
                continue

            if not isinstance(data, dict):
                results[rel_name] = ["File content must be a YAML mapping/dictionary"]
                continue

            tid = data.get("trial_id")
            if tid:
                # Rule 2: trial_id unique
                if tid in loaded_trials:
                    prev_file = file_map[tid].name
                    duplicate_errors.append(
                        f"Duplicate trial_id '{tid}' found in {rel_name} (previously defined in {prev_file})"
                    )
                else:
                    loaded_trials[tid] = data
                    file_map[tid] = yf
            results[rel_name] = []

        if duplicate_errors:
            results.setdefault("[GLOBAL]", []).extend(duplicate_errors)

        # 2. Check acyclic parent lineage across all trials
        def has_cycle(start_id: str, visited: Set[str], path: List[str]) -> Optional[List[str]]:
            visited.add(start_id)
            parent = loaded_trials.get(start_id, {}).get("parent_trial_id")
            if parent:
                if parent in path:
                    return path + [parent]
                if parent in loaded_trials and parent not in visited:
                    res = has_cycle(parent, visited, path + [parent])
                    if res:
                        return res
            return None

        visited_nodes: Set[str] = set()
        for tid in loaded_trials:
            if tid not in visited_nodes:
                cycle = has_cycle(tid, visited_nodes, [tid])
                if cycle:
                    cycle_str = " -> ".join(cycle)
                    results.setdefault("[GLOBAL]", []).append(
                        f"Cyclic parent_trial_id lineage detected: {cycle_str}"
                    )
                    break

        # 3. Validate each trial file
        for yf in yaml_files:
            rel_name = yf.name
            if rel_name in results and results[rel_name]:
                # Already errored on load
                continue

            with open(yf, "r", encoding="utf-8") as f:
                trial_data = yaml.safe_load(f)

            file_errors = self.validate_single_trial(
                trial_data, all_trials=loaded_trials, trial_ref=rel_name
            )
            results[rel_name] = file_errors

        # Determine overall success
        all_passed = all(len(errs) == 0 for errs in results.values())
        return all_passed, results


def validate_trial_file(file_path: Path | str) -> List[str]:
    """Convenience helper to validate a single trial file."""
    path = Path(file_path)
    if not path.exists():
        return [f"File not found: {path}"]
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    validator = TrialLedgerValidator()
    return validator.validate_single_trial(data, trial_ref=path.name)


def validate_all_trials(trials_dir: Optional[Path | str] = None) -> Tuple[bool, Dict[str, List[str]]]:
    """Convenience helper to validate all trials in a directory."""
    validator = TrialLedgerValidator(Path(trials_dir) if trials_dir else None)
    return validator.validate_ledger_directory()


def main() -> int:
    """CLI entrypoint for trial ledger validation."""
    parser = argparse.ArgumentParser(
        description="EasyStock Research Trial Ledger Validator (Pardo Degrees-of-Freedom Governance)"
    )
    parser.add_argument(
        "--trials-dir",
        type=str,
        default=None,
        help="Path to trials directory (default: docs/research_governance/trials)",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Validate a single trial YAML file instead of the full directory",
    )
    args = parser.parse_args()

    validator = TrialLedgerValidator(Path(args.trials_dir) if args.trials_dir else None)

    print("=" * 70)
    print("EasyStock Research Governance — Trial Ledger Validator v1")
    print("=" * 70)

    if args.file:
        file_path = Path(args.file)
        print(f"Validating single trial file: {file_path.name}")
        errors = validate_trial_file(file_path)
        if errors:
            print(f"FAILED: {len(errors)} error(s) found:")
            for err in errors:
                print(f"  - {err}")
            return 1
        else:
            print(f"PASS: {file_path.name} is compliant with Research Trial Ledger Schema v1.")
            return 0

    target_dir = validator.trials_dir
    print(f"Validating trials directory: {target_dir}")
    passed, results = validator.validate_ledger_directory()

    print("-" * 70)
    print(f"{'TRIAL / ARTIFACT':<40} {'STATUS':<12} {'DETAILS'}")
    print("-" * 70)

    total_files = 0
    failed_files = 0

    for item, errors in results.items():
        if item.startswith("["):
            # Global or system error
            status = "SYSTEM_FAIL"
            print(f"{item:<40} {status:<12} {'; '.join(errors)}")
            failed_files += 1
            continue

        total_files += 1
        if len(errors) == 0:
            status = "PASS"
            print(f"{item:<40} {status:<12} All rules satisfied")
        else:
            status = "FAIL"
            failed_files += 1
            print(f"{item:<40} {status:<12} {len(errors)} violation(s)")
            for err in errors:
                print(f"    -> {err}")

    print("-" * 70)
    if passed and failed_files == 0:
        print(f"RESULT: ALL {total_files} TRIALS PASSED VALIDATION.")
        print("Research Trial Ledger is healthy, acyclic, and compliant.")
        return 0
    else:
        print(f"RESULT: VALIDATION FAILED. {failed_files} file(s) with violations.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
