"""Read-only structure inventory, limited to historical dates <= 2026-10-02.

Never imports trading code, opens a broker session, evaluates a return, trains
or writes on the source machine. Recent partitions are filename metadata only.
JSON decoding of permitted historical labels is necessary for schema/count
checks; outcome values are not inspected, classified or exported.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

CUTOFF = "2026-10-02"
FEATURE_COUNT = 5
MAX_SAMPLE_BYTES = 32 * 1024 * 1024
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def allowed_day(day):
    try:
        return bool(DATE_RE.fullmatch(day)) and date.fromisoformat(day).isoformat() <= CUTOFF
    except (TypeError, ValueError):
        return False


def read_scoped_json(path, *, root, day, compressed=False):
    """Check filename, resolved containment and day BEFORE opening content."""
    path, root = Path(path), Path(root)
    if not allowed_day(day) or root.is_symlink() or path.is_symlink() or path.parent.is_symlink():
        raise ValueError("scope_or_symlink_rejected")
    expected_parent = root if path.name == day + ".json" else root / day
    if path.parent.resolve() != expected_parent.resolve():
        raise ValueError("outside_declared_partition")
    opener = gzip.open if compressed else open
    with opener(path, "rb") as stream:
        raw = stream.read(MAX_SAMPLE_BYTES + 1)
    if len(raw) > MAX_SAMPLE_BYTES:
        raise ValueError("bounded_schema_sample_too_large")
    return json.loads(raw)


def label_inventory(root):
    root = Path(root)
    result = {"source": "learning_labels", "grain": "symbol x observation_time x profile",
              "files": [], "profiles": [], "fields_present": {}, "field_types": {},
              "rows": 0, "invalid_identity_rows": 0, "out_of_scope_code_rows": 0, "duplicate_keys": 0,
              "valid_five_feature_rows": 0, "invalid_five_feature_rows": 0,
              "explicit_label_available_at_rows": 0, "explicit_taiwan_observation_time_rows": 0,
              "valid_exit_time_order_rows": 0, "bar_pack_file_exists_rows": 0,
              "expanded_raw_file_exists_rows": 0, "contents_opened": [], "out_of_scope_codes": {}}
    if not root.is_dir() or root.is_symlink():
        result["exists"] = False
        return result
    result["exists"] = True
    fields, types, profiles, seen, excluded_codes = Counter(), defaultdict(Counter), {}, set(), Counter()
    for path in sorted(root.glob("*.json")):
        day = path.stem
        if not DATE_RE.fullmatch(day):
            continue
        item = {"date": day, "file_exists": True, "content_read": False}
        result["files"].append(item)
        if not allowed_day(day):
            item["status"] = "EXCLUDED_AFTER_CUTOFF_CONTENT_NOT_READ"
            continue
        try:
            rows = read_scoped_json(path, root=root, day=day)
        except (OSError, ValueError) as exc:
            item.update(status="READ_ERROR", error=str(exc))
            continue
        item["content_read"] = True
        result["contents_opened"].append(day)
        if not isinstance(rows, list):
            item["status"] = "INVALID_LABEL_CONTAINER"
            continue
        item.update(status="SCHEMA_AUDITED_NOT_TRAINING_APPROVED", rows=len(rows))
        day_profiles, symbols, day_keys = Counter(), set(), set()
        for row in rows:
            result["rows"] += 1
            if not isinstance(row, dict):
                result["invalid_identity_rows"] += 1
                continue
            for key, value in row.items():
                fields[key] += 1
                types[key][type(value).__name__] += 1
            # Dates/keys/profile are provenance metadata, never return values.
            at, profile, symbol = row.get("at"), row.get("profile"), row.get("symbol")
            try:
                observed = datetime.fromisoformat(at)
                valid = (row.get("date") == day and observed.date().isoformat() == day
                         and isinstance(profile, str) and bool(profile)
                         and isinstance(symbol, str) and bool(symbol))
            except (TypeError, ValueError):
                valid = False
            if not valid:
                result["invalid_identity_rows"] += 1
                continue
            key = (symbol, at, profile)
            result["duplicate_keys"] += key in seen
            seen.add(key)
            day_profiles[profile] += 1
            group = profiles.setdefault(profile, {"profile": profile, "rows": 0, "common_stock_code_rows": 0, "dates": set()})
            group["rows"] += 1
            group["dates"].add(day)
            if not re.fullmatch(r"[1-9][0-9]{3}", symbol):
                result["out_of_scope_code_rows"] += 1
                excluded_codes[symbol] += 1
                continue
            group["common_stock_code_rows"] += 1
            symbols.add(symbol)
            day_keys.add((symbol, at))
            # File existence only; does not assert complete coverage or open prices.
            result["bar_pack_file_exists_rows"] += (root.parent / "bars" / day / (symbol + ".json")).is_file()
            expanded = root.parent.parent / "easystock-history-expanded-data/raw"
            result["expanded_raw_file_exists_rows"] += (expanded / day / (symbol + ".json.gz")).is_file()
            result["explicit_taiwan_observation_time_rows"] += observed.utcoffset() == timedelta(hours=8)
            try:
                exit_at = datetime.fromisoformat(row.get("exit_at"))
                result["valid_exit_time_order_rows"] += (exit_at.utcoffset() == timedelta(hours=8)
                    and observed.utcoffset() == timedelta(hours=8)
                    and exit_at.date() == observed.date() and exit_at >= observed)
            except (TypeError, ValueError):
                pass
            features = row.get("features")
            good = (isinstance(features, list) and len(features) == FEATURE_COUNT
                    and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in features))
            result["valid_five_feature_rows" if good else "invalid_five_feature_rows"] += 1
            result["explicit_label_available_at_rows"] += isinstance(row.get("label_available_at"), str)
        item.update(profiles=dict(day_profiles), distinct_common_stock_codes=len(symbols),
                    journal_join=journal_metadata(root.parent, day, day_keys))
    result["fields_present"] = dict(sorted(fields.items()))
    result["field_types"] = {k: dict(v) for k, v in sorted(types.items())}
    result["out_of_scope_codes"] = dict(excluded_codes)
    for group in profiles.values():
        dates = sorted(group.pop("dates"))
        group.update(days=len(dates), start_date=dates[0], end_date=dates[-1])
        result["profiles"].append(group)
    result["profiles"].sort(key=lambda g: g["start_date"])
    return result


def journal_metadata(root, day, label_keys):
    """Only provenance fields from allowed-day sample events; no exit outcomes."""
    root = Path(root)
    path = root / ("journal-" + day + ".jsonl")
    result = {"file_exists": path.exists(), "label_keys": len(label_keys), "matched_keys": 0,
              "quote_time_present": 0, "quote_time_causal_and_fresh": 0, "policy_present": 0, "corrupt_lines": 0,
              "complete_scan": False}
    if not result["file_exists"]:
        return result
    if not allowed_day(day) or root.is_symlink() or path.is_symlink() or path.parent.resolve() != root.resolve():
        raise ValueError("journal_scope_rejected")
    matched, with_quote, with_policy, fresh_quotes = set(), set(), set(), set()
    policy_fields = set()
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index >= 500000:
                break
            try:
                record = json.loads(line)
                if record.get("kind") != "sample":
                    continue
                data = record["data"]
                key = (data.get("symbol"), data.get("observed_at"))
                if key not in label_keys:
                    continue
                matched.add(key)
                if isinstance(data.get("quote_at"), str):
                    with_quote.add(key)
                    try:
                        observed, quoted = datetime.fromisoformat(key[1]), datetime.fromisoformat(data["quote_at"])
                        if (observed.utcoffset() == quoted.utcoffset() == timedelta(hours=8)
                                and observed.date() == quoted.date()
                                and 0 <= (observed - quoted).total_seconds() <= 30):
                            fresh_quotes.add(key)
                    except (TypeError, ValueError):
                        pass
                if isinstance(data.get("policy"), dict):
                    with_policy.add(key)
                    policy_fields.update(data["policy"])
            except (ValueError, KeyError, TypeError, AttributeError):
                result["corrupt_lines"] += 1
        else:
            result["complete_scan"] = True
    result.update(matched_keys=len(matched), quote_time_present=len(with_quote),
                  quote_time_causal_and_fresh=len(fresh_quotes),
                  policy_present=len(with_policy), policy_field_names=sorted(policy_fields))
    return result


def partition_inventory(root, *, compressed):
    root = Path(root)
    result = {"exists": root.is_dir(), "date_partitions": [], "schema_samples": []}
    if not root.is_dir() or root.is_symlink():
        return result
    extension = "*.json.gz" if compressed else "*.json"
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not allowed_day(directory.name) or directory.is_symlink():
            continue
        files = [p for p in directory.glob(extension) if not p.is_symlink()]
        result["date_partitions"].append({"date": directory.name, "files": len(files)})
    dates = result["date_partitions"]
    result["allowed_date_partitions"] = len(dates)
    result["allowed_file_count"] = sum(d["files"] for d in dates)
    # Fixed schema sample: first/last available allowed day, first symbol by name.
    for day in dict.fromkeys([d["date"] for d in dates[:1] + dates[-1:]]):
        candidates = sorted(p for p in (root / day).glob(extension) if not p.is_symlink())
        if not candidates:
            continue
        path = candidates[0]
        sample = {"date": day, "filename": path.name, "selection": "first_symbol_first_or_last_allowed_day"}
        try:
            payload = read_scoped_json(path, root=root, day=day, compressed=compressed)
            sample["top_fields"] = sorted(payload) if isinstance(payload, dict) else []
            for key in ("ticks", "kbars", "audit"):
                if isinstance(payload.get(key), dict):
                    sample[key + "_fields"] = sorted(payload[key])
            if isinstance(payload.get("audit"), dict):
                sample["training_eligible"] = payload["audit"].get("training_eligible")
                sample["training_reason"] = payload["audit"].get("reason")
            bars = payload.get("bars")
            if isinstance(bars, list) and bars and isinstance(bars[0], dict):
                sample["bar_fields"] = sorted(bars[0])
            sample["status"] = "SCHEMA_ONLY_VALUES_NOT_EXPORTED"
        except (OSError, ValueError, AttributeError) as exc:
            sample.update(status="NOT_INSPECTED", reason=str(exc))
        result["schema_samples"].append(sample)
    return result


def sqlite_schemas(filename):
    path = Path(filename)
    if not path.exists():
        return {"exists": False}
    if path.is_symlink():
        return {"exists": True, "status": "SYMLINK_NOT_OPENED"}
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        schemas = {}
        for table in tables:
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table):
                continue
            schemas[table] = [{"name": r[1], "type": r[2]} for r in db.execute('PRAGMA table_info("' + table + '")')]
        return {"exists": True, "tables": schemas, "data_rows_read": False}
    finally:
        db.close()


def collect(home=Path("/home/ubuntu")):
    home = Path(home)
    learning = home / "easystock-learning-data"
    source_root = home / "easystock"
    report = {"schema_version": "tw-a-data-audit-v1", "cutoff": CUTOFF,
              "captured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "labels": label_inventory(learning / "labels"),
              "partitions": {}, "sqlite_schemas": {}, "code": {}}
    report["saved_cost_assumptions"] = []
    reports = learning / "reports"
    for day in report["labels"]["contents_opened"]:
        path = reports / (day + ".json")
        if not path.exists():
            report["saved_cost_assumptions"].append({"date": day, "status": "REPORT_MISSING"})
            continue
        try:
            payload = read_scoped_json(path, root=reports, day=day)
            costs = payload.get("cost_assumptions")
            if not isinstance(costs, dict):
                raise ValueError("cost_snapshot_missing")
            report["saved_cost_assumptions"].append({"date": day, "status": "SAVED_REPORT_SETTINGS",
                "costs": {k: costs[k] for k in ("fee_rate", "minimum_fee_twd", "sell_tax_rate", "slippage_bps", "shares", "scenario") if k in costs}})
        except (OSError, ValueError, AttributeError) as exc:
            report["saved_cost_assumptions"].append({"date": day, "status": "NOT_VERIFIED", "reason": str(exc)})
    for key, root, compressed in (
        ("learning_bars", learning / "bars", False),
        ("history_raw", home / "easystock-history-data/raw", True),
        ("expanded_raw", home / "easystock-history-expanded-data/raw", True),
    ):
        report["partitions"][key] = partition_inventory(root, compressed=compressed)
    for key, path in (
        ("research", learning / "research.sqlite"),
        ("official_daily", learning / "rebound/market-daily.sqlite"),
    ):
        report["sqlite_schemas"][key] = sqlite_schemas(path)
    for name in ("daytrade_learning/settings.json", "daytrade_learning/research.py", "daytrade_learning/features.py",
                 "paper_execution.py", "paper_ledger.py", "history/collector_core.py"):
        path = source_root / name
        if not path.exists():
            continue
        raw = path.read_bytes()
        entry = {"sha256": hashlib.sha256(raw).hexdigest()}
        if name.endswith("settings.json"):
            entry["settings"] = json.loads(raw)
        report["code"][name] = entry
    report["outcome_values_exported"] = False
    report["performance_calculated"] = False
    report["post_cutoff_content_opened"] = False
    report["holdout_content_opened"] = False
    report["source_writes"] = False
    return report


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=True))
