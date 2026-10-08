"""
EasyStock Research Governance — blinded eligible-day counter for pristine holdouts.

Counts the FIRST_60_ELIGIBLE_TRADING_DAYS of a holdout from administrative metadata only:
trading-calendar membership, partition (directory) existence, expected file count, gzip CRC
integrity and file naming. It never parses market data, so no price, volume, signal or outcome
can influence which days are counted. Documented exclusions (e.g. Amendment 1: 2026-10-06) are
skipped before counting. The counter reports; it does not edit the holdout record.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import re
import zlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import yaml

CHECKS = ("partition_exists", "ingestion_success", "schema_valid", "checksum_valid")
FILE_PATTERN = re.compile(r"^\d{4,6}\.json\.gz$")


def trading_days(start: datetime.date, end: datetime.date, closed: Iterable[str]) -> List[str]:
    """Weekdays in [start, end] that are not official closures."""
    closed = set(closed)
    out, d = [], start
    while d <= end:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in closed:
            out.append(iso)
        d += datetime.timedelta(days=1)
    return out


def count_eligible_days(candidate_days: Sequence[str], checks: Dict[str, Dict[str, bool]],
                        excluded_dates: Iterable[str], start_date: str, target: int = 60) -> dict:
    """Pure counting rule. ``checks[day]`` holds only the four boolean metadata checks."""
    excluded = set(excluded_dates)
    eligible: List[str] = []
    skipped: List[dict] = []
    for day in sorted(candidate_days):
        if day < start_date:
            continue
        if len(eligible) >= target:
            break
        if day in excluded:
            skipped.append({"day": day, "reasons": ["documented_exclusion"]})
            continue
        c = checks.get(day) or {}
        failed = [k for k in CHECKS if c.get(k) is not True]
        if failed:
            skipped.append({"day": day, "reasons": failed})
            continue
        eligible.append(day)
    complete = len(eligible) >= target
    return {"eligible_days_collected": len(eligible), "target_eligible_days": target,
            "collected_eligible_trading_days": eligible, "skipped": skipped, "complete": complete,
            "holdout_end_date": eligible[-1] if complete else None}


def load_holdout(path: Path) -> dict:
    rec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    part = rec.get("partition_definition", {}) or {}
    excluded = [e["date"] if isinstance(e, dict) else str(e) for e in part.get("excluded_dates", []) or []]
    return {"holdout_id": rec.get("holdout_id"), "start_date": str(part.get("expected_start_date")),
            "target": int(part.get("target_eligible_days", 60)), "excluded_dates": excluded}


def gzip_crc_ok(path: Path) -> bool:
    """Decompress to verify the gzip CRC; the decompressed bytes are discarded unread."""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except (OSError, EOFError, zlib.error):
        return False


def archive_checks(day_dir: Path, expected_files: int) -> Dict[str, bool]:
    exists = day_dir.is_dir()
    files = sorted(day_dir.glob("*.json.gz")) if exists else []
    return {
        "partition_exists": exists and bool(files),
        "ingestion_success": len(files) >= expected_files,
        "schema_valid": bool(files) and all(FILE_PATTERN.match(f.name) for f in files),
        "checksum_valid": bool(files) and all(gzip_crc_ok(f) for f in files),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--holdout", default="docs/research_governance/holdouts/PHASE2C_FUTURE_60D_HOLDOUT.yaml")
    p.add_argument("--archive", default="/home/ubuntu/easystock-history-expanded-data/raw")
    p.add_argument("--expected-files", type=int, default=100)
    p.add_argument("--closed", default=None, help="JSON list/dict of official closed dates (e.g. market_calendar cache)")
    p.add_argument("--until", default=datetime.date.today().isoformat())
    a = p.parse_args(argv)
    h = load_holdout(Path(a.holdout))
    closed = []
    if a.closed:
        raw = json.loads(Path(a.closed).read_text(encoding="utf-8"))
        closed = list(raw.get("closed_map", raw.get("closed", raw))) if isinstance(raw, dict) else list(raw)
    start = datetime.date.fromisoformat(h["start_date"])
    days = trading_days(start, datetime.date.fromisoformat(a.until), closed)
    checks = {d: archive_checks(Path(a.archive) / d, a.expected_files) for d in days}
    res = count_eligible_days(days, checks, h["excluded_dates"], h["start_date"], h["target"])
    res["holdout_id"] = h["holdout_id"]
    res["metadata_only"] = True
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
