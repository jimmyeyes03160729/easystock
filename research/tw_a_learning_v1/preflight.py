"""Inspect an explicit metadata manifest only. No dataset/model is opened.

This command cannot train, backtest, download, promote or deploy anything.
Even complete metadata is a checklist result, not access authorization.
"""
import argparse
from datetime import date
from importlib import metadata
import json
from pathlib import Path
import re

SCHEMA = "tw-a-learning-manifest-v1"
MAX_HISTORY_DATE = date(2026, 10, 2)
CANDIDATES = (
    {"id": "logistic_tw", "kind": "local_baseline", "package": None, "checkpoint": None},
    {"id": "lightgbm_tw", "kind": "local_training", "package": "lightgbm", "checkpoint": None},
    {"id": "tabpfn_v2_tw", "kind": "external_prior", "package": "tabpfn", "checkpoint": "Prior-Labs/TabPFN-v2-clf"},
    {"id": "logistic_tw_plus_kronos_mini", "kind": "external_prior_feature", "package": "torch", "checkpoint": "NeoQuasar/Kronos-mini"},
)
DATA_PROOFS = (
    "registry_scope_verified", "training_eligible", "holdout_exclusion_verified",
    "point_in_time_verified", "twse_tpex_identity_verified", "official_index_context_verified",
    "execution_depth_verified", "sample_profile_verified", "labels_match_a_paper_costs",
    "calendar_and_reference_verified", "exposure_ledger_registered",
)


def check_manifest(manifest):
    checks = []

    def check(name, passed):
        checks.append({"check": name, "passed": passed is True})

    check("schema", manifest.get("schema_version") == SCHEMA)
    check("research_only", manifest.get("research_only") is True)
    check("production_effect_none", manifest.get("production_effect") == "NONE")
    data = manifest.get("dataset")
    if not isinstance(data, dict):
        data = {}
    check("taiwan_training_only", data.get("training_markets") == ["TW"])
    check("ordinary_stocks_only", data.get("instrument_type") == "COMMON_STOCK")
    check("registered_dataset_id", isinstance(data.get("dataset_id"), str) and bool(data["dataset_id"].strip()))
    try:
        start, end = date.fromisoformat(data["start_date"]), date.fromisoformat(data["end_date"])
        valid_scope = start <= end <= MAX_HISTORY_DATE
    except (KeyError, TypeError, ValueError):
        valid_scope = False
    check("historical_scope_through_2026_10_02", valid_scope)
    for key in DATA_PROOFS:
        check(key, data.get(key) is True)
    hashes = manifest.get("freeze_hashes")
    if not isinstance(hashes, dict):
        hashes = {}
    for key in ("preregistration", "dataset_registry", "exposure_ledger", "cost_model", "evaluation_plan", "baseline_policy"):
        check("sha256_" + key, bool(re.fullmatch(r"[a-f0-9]{64}", str(hashes.get(key, "")))))
    check("preregistration_committed", bool(re.fullmatch(r"[a-f0-9]{40}", str(manifest.get("preregistration_commit", "")))))
    versions = manifest.get("models")
    if not isinstance(versions, dict):
        versions = {}
    shared_ok = all(c["passed"] for c in checks)
    candidates = []
    for candidate in CANDIDATES:
        desc = versions.get(candidate["id"])
        if not isinstance(desc, dict):
            desc = {}
        blockers = []
        if not shared_ok:
            blockers.append("dataset_or_freeze_metadata_incomplete")
        if desc.get("implementation_reviewed") is not True:
            blockers.append("comparison_adapter_not_reviewed_or_implemented")
        if candidate["package"]:
            try:
                installed = metadata.version(candidate["package"])
            except metadata.PackageNotFoundError:
                installed = None
            if not installed or installed != desc.get("package_version"):
                blockers.append("dependency_missing_or_not_pinned")
        else:
            installed = "stdlib"
        if candidate["checkpoint"]:
            if desc.get("checkpoint") != candidate["checkpoint"]:
                blockers.append("checkpoint_must_match_fixed_arm")
            if not re.fullmatch(r"[a-f0-9]{40}", str(desc.get("revision", ""))):
                blockers.append("immutable_weight_revision_missing")
            if not re.fullmatch(r"[a-f0-9]{64}", str(desc.get("weight_sha256", ""))):
                blockers.append("weight_hash_missing")
            if desc.get("license_reviewed") is not True:
                blockers.append("weight_license_not_reviewed")
            if desc.get("pretraining_overlap_status") != "AUDITED_NO_EVALUATION_OVERLAP":
                blockers.append("pretraining_evaluation_overlap_not_audited")
            if desc.get("inference_resource_verified") is not True:
                blockers.append("inference_resources_not_verified")
        candidates.append({**candidate, "installed_package_version": installed,
                           "metadata_complete": not blockers, "blockers": blockers})
    return {
        "schema_version": SCHEMA, "stage": "DESIGN_PREFLIGHT_ONLY",
        "status": "METADATA_COMPLETE_NOT_AUTHORIZED" if all(c["metadata_complete"] for c in candidates) else "BLOCKED_NOT_READY",
        "checks": checks, "candidates": candidates,
        "monitor": {"id": "river_adwin", "role": "research_alert_only", "may_change_market_gate": False},
        "metadata_is_self_declared_not_authenticated": True,
        "market_data_opened": False, "model_weights_opened": False,
        "training_executed": False, "training_authorized": False,
        "backtest_executed": False, "holdout_outcomes_touched": False,
        "production_changed": False, "production_ready": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Explicit metadata JSON, never a price/label file")
    args = parser.parse_args(argv)
    if args.manifest.stat().st_size > 65536:
        parser.error("metadata manifest exceeds 64 KiB")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA:
        parser.error("not a Taiwan research metadata manifest")
    report = check_manifest(manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "METADATA_COMPLETE_NOT_AUTHORIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
