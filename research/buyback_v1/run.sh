#!/usr/bin/env bash
# BUYBACK_V1 one-shot run on the VM. Research only: reads the buyback table and the official daily DB, never edits the repo.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
exec 9>run.lock
flock -n 9 || { echo "already running"; exit 0; }
echo "=== $(date -Is) start"
nice -n 15 /home/ubuntu/easystock-learning-venv/bin/python bb_study.py > study.log 2>&1 && date -Is > DONE && cat output/FINAL_LINES.txt || echo "study failed; see study.log"
