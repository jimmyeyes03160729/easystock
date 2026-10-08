#!/usr/bin/env bash
# PASSIVE_FILL_V1 one-shot run. Research only: reads the archive and the official daily DB, never edits the repo.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
exec 9>run.lock
flock -n 9 || { echo "already running"; exit 0; }
PY=/home/ubuntu/easystock-learning-venv/bin/python
echo "=== $(date -Is) start"
nice -n 15 $PY pf_run.py 0 2 > worker_0.log 2>&1 &
P0=$!
nice -n 15 $PY pf_run.py 1 2 > worker_1.log 2>&1 &
P1=$!
wait $P0; wait $P1
$PY pf_finalize.py > finalize.log 2>&1 && date -Is > DONE && cat output/FINAL_LINES.txt || echo "finalize failed; see finalize.log"
