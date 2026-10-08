#!/usr/bin/env bash
# META_B_FILTER_V1 Stage 1 one-shot run. Research only: reads archive days <= 2026-08-27 and the official daily DB
# (<= 2026-10-02), never edits the repo or touches live services. Run from a git archive of a merged commit.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
export MB_CODE_COMMIT="${MB_CODE_COMMIT:-unknown}"
exec 9>run.lock
flock -n 9 || { echo "already running"; exit 0; }
PY=/home/ubuntu/easystock-learning-venv/bin/python
echo "=== $(date -Is) start commit=$MB_CODE_COMMIT"
nice -n 15 $PY -I mb_run.py 0 2 > worker_0.log 2>&1 &
P0=$!
nice -n 15 $PY -I mb_run.py 1 2 > worker_1.log 2>&1 &
P1=$!
wait $P0; wait $P1
$PY -I mb_finalize.py > finalize.log 2>&1 && date -Is > DONE && cat output/FINAL_LINES.txt || echo "finalize failed; see finalize.log"
