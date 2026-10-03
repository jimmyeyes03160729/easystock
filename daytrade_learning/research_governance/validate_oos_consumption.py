"""EasyStock Research Governance — OOS Consumption Ledger Validator v1.

Validates data consumption events, exposure levels, lineage preservation,
and pristine reservation invariants against the Central Dataset Registry.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

EXPOSURE_LEVEL_ORDER = {
    "LEVEL_0_UNTOUCHED": 0,
    "LEVEL_1_FEATURE_STRUCTURE_SEEN": 1,
    "LEVEL_2_AGGREGATE_METRICS_SEEN": 2,
    "LEVEL_3_SUBGROUP_RESULTS_SEEN": 3,
    "LEVEL_4_PARAMETER_SELECTION_USED": 4,
    "LEVEL_5_REPEATED_RESEARCH_EXPOSED": 5,
}

SUBGROUP_DIMENSION_KEYWORDS = {
    "year",
    "time-of-day",
    "time_of_day",
    "direction",
    "candidate",
    "regime",
    "volatility",
    "breadth",
    "opening",
    "15m",
    "30m",
    "long",
    "short",
}

ADMIN_METADATA_WHITELIST = {
    "file_existence",
    "ingestion_success",
    "schema_version",
    "checksum",
    "trading_calendar_membership",
}

MARKET_DATA_PROHIBITED_FOR_LEVEL_0 = {
    "ohlcv",
    "ohlcv_values",
    "market_row_stats",
    "activity_statistics",
    "row_count",
    "tick_count",
    "feature_values",
    "feature_distributions",
    "labels",
    "signals",
    "pnl",
    "returns",
    "performance_metrics",
    "subgroup_metrics",
}


def parse_date(date_val: Optional[str]) -> Optional[datetime.date]:
    """Parse YYYY-MM-DD string to datetime.date object."""
    if not date_val:
        return None
    if isinstance(date_val, datetime.date):
        return date_val
    if isinstance(date_val, datetime.datetime):
        return date_val.date()
    return datetime.datetime.strptime(str(date_val).strip(), "%Y-%m-%d").date()


class DatasetRegistry:
    """Authoritative Central Dataset Registry loader and lookup."""

    def __init__(self, registry_path: str):
        self.registry_path = registry_path
        self.datasets: Dict[str, Dict[str, Any]] = {}
        self.parent_graph: Dict[str, List[str]] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.registry_path):
            raise FileNotFoundError(f"Dataset registry not found at: {self.registry_path}")
        with open(self.registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        raw_list = data.get("datasets", [])
        for entry in raw_list:
            ds_id = entry.get("dataset_id")
            if ds_id:
                self.datasets[ds_id] = entry
                self.parent_graph[ds_id] = entry.get("parent_dataset_ids", []) or []

    def get(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        return self.datasets.get(dataset_id)

    def contains(self, dataset_id: str) -> bool:
        return dataset_id in self.datasets

    def get_all_ancestor_ids(self, dataset_id: str) -> Set[str]:
        """Traverse parent_dataset_ids recursively to find all ancestors."""
        ancestors: Set[str] = set()
        stack = list(self.parent_graph.get(dataset_id, []))
        while stack:
            parent = stack.pop()
            if parent not in ancestors:
                ancestors.add(parent)
                stack.extend(self.parent_graph.get(parent, []))
        return ancestors

    def shares_lineage_or_family(self, ds_id_a: str, ds_id_b: str) -> bool:
        """Check if two dataset IDs share lineage, family, alias, or parent-child derivation."""
        if ds_id_a == ds_id_b:
            return True
        info_a = self.get(ds_id_a)
        info_b = self.get(ds_id_b)
        if not info_a or not info_b:
            return False

        lineage_a = info_a.get("dataset_lineage_id")
        lineage_b = info_b.get("dataset_lineage_id")
        if lineage_a and lineage_b and (lineage_a != "LINEAGE_UNKNOWN") and (lineage_a == lineage_b):
            return True

        family_a = info_a.get("dataset_family_id")
        family_b = info_b.get("dataset_family_id")
        if family_a and family_b and (family_a == family_b):
            return True

        # Check derivation relationship
        ancestors_a = self.get_all_ancestor_ids(ds_id_a)
        ancestors_b = self.get_all_ancestor_ids(ds_id_b)
        if ds_id_a in ancestors_b or ds_id_b in ancestors_a or bool(ancestors_a.intersection(ancestors_b)):
            return True

        return False


def dates_overlap(
    s1: datetime.date,
    e1: Optional[datetime.date],
    s2: datetime.date,
    e2: Optional[datetime.date],
) -> bool:
    """Check whether two closed or open date intervals overlap."""
    eff_e1 = e1 or datetime.date(2099, 12, 31)
    eff_e2 = e2 or datetime.date(2099, 12, 31)
    return max(s1, s2) <= min(eff_e1, eff_e2)


class OOSConsumptionValidator:
    """Validator for OOS Consumption Ledger events and governance rules."""

    def __init__(self, registry: DatasetRegistry):
        self.registry = registry

    def validate_single_event(
        self,
        event: Dict[str, Any],
        seen_ids: Set[str],
        prior_events: List[Dict[str, Any]],
    ) -> List[str]:
        """Validate a single consumption event."""
        errors: List[str] = []
        c_id = event.get("consumption_id")

        if not c_id:
            errors.append("Missing required field: consumption_id")
            return errors

        # 1. consumption_id format and uniqueness
        if not re.match(r"^CNS_[A-Za-z0-9_]+$", str(c_id)):
            errors.append(f"Invalid consumption_id format: '{c_id}'. Must match ^CNS_[A-Za-z0-9_]+$")
        if c_id in seen_ids:
            errors.append(f"Duplicate consumption_id detected: '{c_id}'")
        seen_ids.add(c_id)

        # 2. dataset_id existence in Central Registry
        ds_id = event.get("dataset_id")
        if not ds_id or not self.registry.contains(ds_id):
            errors.append(f"[{c_id}] dataset_id '{ds_id}' does not exist in Central Dataset Registry")
            return errors

        reg_info = self.registry.get(ds_id)
        assert reg_info is not None

        # 3. Family and lineage must match authoritative Registry
        reg_family = reg_info.get("dataset_family_id")
        reg_lineage = reg_info.get("dataset_lineage_id")

        ev_family = event.get("dataset_family_id")
        ev_lineage = event.get("dataset_lineage_id")

        if ev_family != reg_family:
            errors.append(
                f"[{c_id}] dataset_family_id mismatch for '{ds_id}': "
                f"event specifies '{ev_family}' but registry authoritative value is '{reg_family}'"
            )
        if ev_lineage != reg_lineage:
            errors.append(
                f"[{c_id}] dataset_lineage_id mismatch for '{ds_id}': "
                f"event specifies '{ev_lineage}' but registry authoritative value is '{reg_lineage}'"
            )

        # 4. LINEAGE_UNKNOWN cannot claim pristine independent evidence
        gov = event.get("governance", {}) or {}
        if ev_lineage == "LINEAGE_UNKNOWN":
            if gov.get("independent_confirmation_eligible_after") is True or gov.get("pristine_after") is True:
                errors.append(
                    f"[{c_id}] Unknown lineage (LINEAGE_UNKNOWN) cannot automatically claim pristine "
                    "or independent confirmation eligibility without explicit governance review"
                )

        # 5. Date range validation
        slice_info = event.get("slice", {}) or {}
        start_date_raw = slice_info.get("start_date")
        end_date_raw = slice_info.get("end_date")
        info_incomplete = slice_info.get("historical_information_incomplete", False)
        range_unknown = slice_info.get("historical_exposure_range") == "UNKNOWN"

        if start_date_raw is None:
            if not (info_incomplete or range_unknown):
                errors.append(
                    f"[{c_id}] slice.start_date is required unless historical_information_incomplete is true "
                    "or historical_exposure_range is UNKNOWN"
                )
                return errors
            start_date = None
            end_date = None
        else:
            try:
                start_date = parse_date(start_date_raw)
                end_date = parse_date(end_date_raw)
            except Exception as e:
                errors.append(f"[{c_id}] Invalid date format in slice: {e}")
                return errors

            assert start_date is not None
            if end_date and start_date > end_date:
                errors.append(f"[{c_id}] Invalid date range: start_date ({start_date}) > end_date ({end_date})")

            # Slice bounds vs Registry bounds
            reg_start = parse_date(reg_info.get("start_date"))
            reg_end = parse_date(reg_info.get("end_date"))
            if reg_start and start_date < reg_start:
                errors.append(
                    f"[{c_id}] slice start_date ({start_date}) precedes registered dataset start_date ({reg_start})"
                )
            if reg_end and end_date and end_date > reg_end:
                errors.append(
                    f"[{c_id}] slice end_date ({end_date}) exceeds registered dataset end_date ({reg_end})"
                )

        # 6. Exposure flags and exposure_level consistency
        exposure = event.get("exposure", {}) or {}
        exp_level = event.get("exposure_level")
        perf_seen = exposure.get("performance_seen", False)
        labels_seen = exposure.get("labels_seen", False)
        agg_seen = exposure.get("aggregate_metrics_seen", False)
        subgroup_seen = exposure.get("subgroup_results_seen", False)
        param_infl = exposure.get("parameter_selection_influenced", False)
        human_seen = exposure.get("human_seen", False)
        ai_seen = exposure.get("ai_seen", False)
        dims = event.get("dimensions_seen", []) or []
        admin_meta = exposure.get("admin_metadata_inspected", []) or []
        market_meta = exposure.get("market_data_inspected", []) or []

        if exp_level not in EXPOSURE_LEVEL_ORDER:
            errors.append(f"[{c_id}] Invalid exposure_level: '{exp_level}'")
            return errors

        # Level 0 invariants (ADMIN_METADATA_ONLY permitted)
        if exp_level == "LEVEL_0_UNTOUCHED":
            if any([perf_seen, labels_seen, agg_seen, subgroup_seen, param_infl, human_seen, ai_seen]):
                errors.append(
                    f"[{c_id}] LEVEL_0_UNTOUCHED violation: all exposure flags must be false. "
                    f"Got perf={perf_seen}, agg={agg_seen}, subgroup={subgroup_seen}, human={human_seen}, ai={ai_seen}"
                )
            if len(dims) > 0:
                errors.append(f"[{c_id}] LEVEL_0_UNTOUCHED cannot have dimensions_seen; found: {dims}")
            if gov.get("pristine_before") is not True or gov.get("pristine_after") is not True:
                errors.append(f"[{c_id}] LEVEL_0_UNTOUCHED must have pristine_before=true and pristine_after=true")

            # Admin metadata whitelist check
            for item in admin_meta:
                if item not in ADMIN_METADATA_WHITELIST:
                    errors.append(
                        f"[{c_id}] LEVEL_0_UNTOUCHED inspected non-whitelisted admin metadata: '{item}'. "
                        f"Permitted whitelist: {sorted(list(ADMIN_METADATA_WHITELIST))}. Must upgrade exposure level."
                    )

            # Prohibited market data check (burns holdout)
            for item in market_meta:
                errors.append(
                    f"[{c_id}] LEVEL_0_UNTOUCHED violation: market data inspection '{item}' burns holdout "
                    "and requires upgrading exposure level (e.g. LEVEL_1+)."
                )
        else:
            if market_meta and EXPOSURE_LEVEL_ORDER[exp_level] < EXPOSURE_LEVEL_ORDER["LEVEL_1_FEATURE_STRUCTURE_SEEN"]:
                errors.append(
                    f"[{c_id}] market_data_inspected requires at least LEVEL_1_FEATURE_STRUCTURE_SEEN; got '{exp_level}'"
                )

        # Level 2 requirement: aggregate metrics seen
        if agg_seen and EXPOSURE_LEVEL_ORDER[exp_level] < EXPOSURE_LEVEL_ORDER["LEVEL_2_AGGREGATE_METRICS_SEEN"]:
            errors.append(
                f"[{c_id}] aggregate_metrics_seen=true requires at least LEVEL_2_AGGREGATE_METRICS_SEEN; got '{exp_level}'"
            )

        # Subgroup dimension check
        has_subgroup_dim = any(
            any(k in dim.lower() for k in SUBGROUP_DIMENSION_KEYWORDS) for dim in dims
        )
        if (subgroup_seen or has_subgroup_dim) and EXPOSURE_LEVEL_ORDER[exp_level] < EXPOSURE_LEVEL_ORDER["LEVEL_3_SUBGROUP_RESULTS_SEEN"]:
            errors.append(
                f"[{c_id}] subgroup_results_seen=true or subgroup dimensions seen requires at least "
                f"LEVEL_3_SUBGROUP_RESULTS_SEEN; got '{exp_level}'"
            )

        # Level 4 requirement: parameter selection influenced or candidate selection influenced
        cand_infl = exposure.get("candidate_selection_influenced", False)
        if param_infl and EXPOSURE_LEVEL_ORDER[exp_level] < EXPOSURE_LEVEL_ORDER["LEVEL_4_PARAMETER_SELECTION_USED"]:
            errors.append(
                f"[{c_id}] parameter_selection_influenced=true requires at least LEVEL_4_PARAMETER_SELECTION_USED; got '{exp_level}'"
            )
        elif cand_infl and EXPOSURE_LEVEL_ORDER[exp_level] < EXPOSURE_LEVEL_ORDER["LEVEL_4_PARAMETER_SELECTION_USED"]:
            errors.append(
                f"[{c_id}] candidate_selection_influenced=true requires at least LEVEL_4_PARAMETER_SELECTION_USED; got '{exp_level}'"
            )

        # 7. RESERVED_UNTOUCHED and Confirmation invariants
        role = event.get("role")
        record_type = event.get("record_type")
        conf_status = reg_info.get("canonical_status")

        if role == "CONFIRMATION" or record_type in ("RESERVATION", "CONFIRMATION_RESERVATION") or conf_status == "RESERVED_UNTOUCHED":
            if perf_seen or labels_seen or agg_seen or subgroup_seen:
                errors.append(
                    f"[{c_id}] RESERVED_UNTOUCHED confirmation reservation cannot contain performance/outcome exposure"
                )
            if gov.get("independent_confirmation_completed") is True:
                errors.append(
                    f"[{c_id}] RESERVED_UNTOUCHED confirmation reservation cannot be marked completed "
                    "(independent_confirmation_completed must be false)"
                )
            if exp_level != "LEVEL_0_UNTOUCHED":
                errors.append(
                    f"[{c_id}] Confirmation reservation must be LEVEL_0_UNTOUCHED; got '{exp_level}'"
                )
            if event.get("consumed_at") is not None:
                errors.append(
                    f"[{c_id}] Reservation record must have consumed_at: null; got '{event.get('consumed_at')}'"
                )

        # 8. Legacy Backfill integrity
        if record_type == "LEGACY_BACKFILL":
            if event.get("recorded_after_exposure") is not True:
                errors.append(
                    f"[{c_id}] LEGACY_BACKFILL must declare recorded_after_exposure: true"
                )

        # 9. Pristine transition & Re-pristining invariants (Cross-event check)
        pristine_before = gov.get("pristine_before", False)
        pristine_after = gov.get("pristine_after", False)

        if exp_level != "LEVEL_0_UNTOUCHED" and pristine_after is True:
            errors.append(
                f"[{c_id}] Re-pristining violation: data exposed to '{exp_level}' cannot declare pristine_after=true"
            )

        # Cross-event history inspection against all prior events
        for prior in prior_events:
            p_id = prior.get("consumption_id")
            p_ds = prior.get("dataset_id")
            p_level = prior.get("exposure_level", "LEVEL_0_UNTOUCHED")
            p_slice = prior.get("slice", {}) or {}
            p_start = parse_date(p_slice.get("start_date"))
            p_end = parse_date(p_slice.get("end_date"))

            if not p_start:
                continue

            # Check if datasets share lineage, family, or parent-child derivation
            if self.registry.shares_lineage_or_family(ds_id, p_ds):
                # Check date overlap only if both start dates are known
                if start_date is not None and p_start is not None:
                    if dates_overlap(start_date, end_date, p_start, p_end):
                        # If prior event was exposed (level > 0), this slice cannot be pristine_before
                        if EXPOSURE_LEVEL_ORDER.get(p_level, 0) > 0 and pristine_before is True:
                            errors.append(
                                f"[{c_id}] Overlap violation: slice [{start_date} ~ {end_date or 'OPEN'}] "
                                f"overlaps with previously exposed slice [{p_start} ~ {p_end or 'OPEN'}] "
                                f"from [{p_id}] ({p_level}). It cannot claim pristine_before=true."
                            )

        return errors

    def validate_ledger_file(
        self,
        file_path: str,
        seen_ids: Set[str],
        accumulated_events: List[Dict[str, Any]],
    ) -> Tuple[bool, List[str]]:
        """Validate an entire consumption ledger YAML file."""
        errors: List[str] = []
        if not os.path.exists(file_path):
            return False, [f"File not found: {file_path}"]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            return False, [f"YAML parse error in {file_path}: {e}"]

        schema_ver = data.get("schema_version")
        if schema_ver != "OOS_CONSUMPTION_LEDGER_SCHEMA_v1":
            errors.append(f"Invalid schema_version: '{schema_ver}'. Expected 'OOS_CONSUMPTION_LEDGER_SCHEMA_v1'")

        events = data.get("consumption_events", [])
        if not isinstance(events, list):
            errors.append("Field 'consumption_events' must be a list")
            return False, errors

        file_events: List[Dict[str, Any]] = []
        for ev in events:
            ev_errors = self.validate_single_event(ev, seen_ids, accumulated_events)
            if ev_errors:
                errors.extend(ev_errors)
            else:
                file_events.append(ev)
                accumulated_events.append(ev)

        return len(errors) == 0, errors


def compute_slice_consumption_stats(
    registry: DatasetRegistry,
    consumption_events: List[Dict[str, Any]],
    dataset_id: str,
    start_date: datetime.date,
    end_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Compute audit metrics and exposure accounting for a specific dataset slice.

    Note: This is exposure governance accounting, not statistical significance adjustment.
    """
    total_consumption_events = 0
    train_consumption_count = 0
    oos_consumption_count = 0
    descriptive_consumption_count = 0
    confirmation_consumption_count = 0
    human_exposure_count = 0
    ai_exposure_count = 0
    distinct_trials: Set[str] = set()
    distinct_dimensions: Set[str] = set()
    max_level_idx = 0
    max_level_name = "LEVEL_0_UNTOUCHED"

    for ev in consumption_events:
        ev_ds = ev.get("dataset_id")
        if not ev_ds:
            continue

        # Check lineage/family match via Registry
        if not registry.shares_lineage_or_family(dataset_id, ev_ds):
            continue

        # Reservations are NOT consumption events: they represent pristine held-out partitions
        # and contribute zero to consumption, exposure, or outcome counts.
        rec_type = ev.get("record_type")
        is_reservation = (
            rec_type in ("RESERVATION", "CONFIRMATION_RESERVATION")
            or ev.get("consumed_at") is None
            or ev.get("exposure_level") == "LEVEL_0_UNTOUCHED"
        )
        if is_reservation:
            continue

        sl = ev.get("slice", {}) or {}
        ev_start = parse_date(sl.get("start_date"))
        ev_end = parse_date(sl.get("end_date"))
        if not ev_start:
            if sl.get("historical_information_incomplete") or sl.get("historical_exposure_range") == "UNKNOWN":
                total_consumption_events += 1
                role = ev.get("role")
                if role == "TRAIN":
                    train_consumption_count += 1
                elif role == "OOS":
                    oos_consumption_count += 1
                elif role in ("DESCRIPTIVE", "EXPLORATORY"):
                    descriptive_consumption_count += 1
                elif role in ("CONFIRMATION", "HOLDOUT"):
                    confirmation_consumption_count += 1
                t_id = ev.get("trial_id")
                if t_id:
                    distinct_trials.add(t_id)
                for dim in ev.get("dimensions_seen", []) or []:
                    distinct_dimensions.add(dim)
                lvl = ev.get("exposure_level", "LEVEL_0_UNTOUCHED")
                lvl_idx = EXPOSURE_LEVEL_ORDER.get(lvl, 0)
                if lvl_idx > max_level_idx:
                    max_level_idx = lvl_idx
                    max_level_name = lvl
            continue

        if dates_overlap(start_date, end_date, ev_start, ev_end):
            total_consumption_events += 1
            role = ev.get("role")
            if role == "TRAIN":
                train_consumption_count += 1
            elif role == "OOS":
                oos_consumption_count += 1
            elif role in ("DESCRIPTIVE", "EXPLORATORY"):
                descriptive_consumption_count += 1
            elif role in ("CONFIRMATION", "HOLDOUT"):
                confirmation_consumption_count += 1

            exposure = ev.get("exposure", {}) or {}
            if exposure.get("human_seen"):
                human_exposure_count += 1
            if exposure.get("ai_seen"):
                ai_exposure_count += 1

            t_id = ev.get("trial_id")
            if t_id:
                distinct_trials.add(t_id)

            for dim in ev.get("dimensions_seen", []) or []:
                distinct_dimensions.add(dim)

            lvl = ev.get("exposure_level", "LEVEL_0_UNTOUCHED")
            lvl_idx = EXPOSURE_LEVEL_ORDER.get(lvl, 0)
            if lvl_idx > max_level_idx:
                max_level_idx = lvl_idx
                max_level_name = lvl

    is_pristine = (max_level_idx == 0) and (total_consumption_events == 0 or max_level_name == "LEVEL_0_UNTOUCHED")

    return {
        "dataset_id": dataset_id,
        "slice_start": str(start_date),
        "slice_end": str(end_date) if end_date else "OPEN",
        "total_consumption_events": total_consumption_events,
        "train_consumption_count": train_consumption_count,
        "oos_consumption_count": oos_consumption_count,
        "descriptive_consumption_count": descriptive_consumption_count,
        "confirmation_consumption_count": confirmation_consumption_count,
        "human_exposure_count": human_exposure_count,
        "ai_exposure_count": ai_exposure_count,
        "distinct_trial_count": len(distinct_trials),
        "distinct_trials": sorted(list(distinct_trials)),
        "distinct_dimension_count": len(distinct_dimensions),
        "distinct_dimensions": sorted(list(distinct_dimensions)),
        "max_exposure_level": max_level_name,
        "is_pristine": is_pristine,
    }


def validate_all(
    registry_path: str,
    ledgers_dir: str,
) -> Tuple[bool, Dict[str, Tuple[bool, List[str]]]]:
    """Validate central registry and all ledger files in ledgers_dir."""
    registry = DatasetRegistry(registry_path)
    validator = OOSConsumptionValidator(registry)

    results: Dict[str, Tuple[bool, List[str]]] = {}
    seen_ids: Set[str] = set()
    accumulated_events: List[Dict[str, Any]] = []

    if not os.path.exists(ledgers_dir):
        return False, {"directory": (False, [f"Ledgers directory not found: {ledgers_dir}"])}

    files = sorted([f for f in os.listdir(ledgers_dir) if f.endswith(".yaml") or f.endswith(".yml")])
    all_passed = True

    for filename in files:
        full_path = os.path.join(ledgers_dir, filename)
        passed, errors = validator.validate_ledger_file(full_path, seen_ids, accumulated_events)
        results[filename] = (passed, errors)
        if not passed:
            all_passed = False

    return all_passed, results


def main() -> int:
    """CLI Entry point for OOS consumption ledger validation."""
    parser = argparse.ArgumentParser(description="EasyStock OOS Consumption Ledger Validator v1")
    parser.add_argument(
        "--registry",
        default="docs/research_governance/DATASET_REGISTRY_v1.yaml",
        help="Path to DATASET_REGISTRY_v1.yaml",
    )
    parser.add_argument(
        "--ledgers-dir",
        default="docs/research_governance/oos_consumption",
        help="Directory containing consumption ledger files",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("EasyStock Research Governance — OOS Consumption Ledger Validator v1")
    print("=" * 70)
    print(f"Registry:    {args.registry}")
    print(f"Ledgers Dir: {args.ledgers_dir}")
    print("-" * 70)

    try:
        registry = DatasetRegistry(args.registry)
        print(f"Loaded Central Dataset Registry with {len(registry.datasets)} datasets.")
        for ds_id, ds in registry.datasets.items():
            print(f"  • {ds_id} (Family: {ds.get('dataset_family_id')}, Lineage: {ds.get('dataset_lineage_id')})")
    except Exception as e:
        print(f"ERROR loading registry: {e}")
        return 1

    print("-" * 70)
    print(f"{'FILE / ARTIFACT':<40} {'STATUS':<12} {'DETAILS'}")
    print("-" * 70)

    all_passed, results = validate_all(args.registry, args.ledgers_dir)

    for filename, (passed, errors) in results.items():
        status_str = "PASS" if passed else "FAIL"
        details_str = "All rules satisfied" if passed else "; ".join(errors)
        print(f"{filename:<40} {status_str:<12} {details_str}")

    print("-" * 70)
    # Accounting summary
    consumption_count = 0
    reservation_count = 0
    for filename in sorted(os.listdir(args.ledgers_dir)):
        if filename.endswith(".yaml") or filename.endswith(".yml"):
            p = os.path.join(args.ledgers_dir, filename)
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f) or {}
            for ev in d.get("consumption_events", []):
                if ev.get("record_type") in ("RESERVATION", "CONFIRMATION_RESERVATION") or ev.get("consumed_at") is None:
                    reservation_count += 1
                else:
                    consumption_count += 1
    total_records = consumption_count + reservation_count

    print(f"CONSUMPTION_EVENTS_BACKFILLED: {consumption_count}")
    print(f"RESERVATION_RECORDS:           {reservation_count}")
    print(f"LEDGER_RECORDS_TOTAL:          {total_records}")
    print("-" * 70)

    if all_passed:
        print("RESULT: ALL OOS CONSUMPTION LEDGERS PASSED VALIDATION.")
        print("Lineage integrity, exposure boundaries, and pristine reservations intact.")
        return 0
    else:
        print("RESULT: VALIDATION FAILED WITH INTEGRITY VIOLATIONS.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
