#!/usr/bin/env python3
"""Promote candidate-2026-10-08 to latest-approved on VM."""
import json
from pathlib import Path
from daytrade_learning.research import promote_candidate
from daytrade_learning.model_runtime import DaytradeModel

data_dir = Path("/home/ubuntu/easystock-learning-data")
cand_path = data_dir / "models" / "candidate-2026-10-08.json"

if not cand_path.exists():
    raise SystemExit(f"Candidate file not found: {cand_path}")

cand = json.loads(cand_path.read_text(encoding="utf-8"))
print(f"Loaded candidate: version={cand.get('version')} trained_through={cand.get('trained_through')} status={cand.get('status')}")

promoted = promote_candidate(data_dir, cand, write_log=True, archive_previous=True)
print(f"Promoted: version={promoted.get('version')} approved={promoted.get('approved')} status={promoted.get('status')}")

# Verify DaytradeModel loads it without stale error
model = DaytradeModel(data_dir / "models" / "latest-approved.json")
print(f"DaytradeModel test: active={model.artifact is not None} reason={model.reason} version={model.model_version}")
if model.artifact is None:
    raise SystemExit(f"Model failed to load: {model.reason}")
print("SUCCESS: Approved model loaded successfully!")
