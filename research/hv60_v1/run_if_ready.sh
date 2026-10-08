#!/usr/bin/env bash
# HV60_V1 daily trigger (cron). Research only: reads the archive and the official daily DB, never edits the repo.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
[ -f DONE ] && exit 0
exec 9>run.lock
flock -n 9 || exit 0
echo "=== $(date -Is) check"
python3 gate.py >> gate.log || { echo "gate not passed"; exit 0; }
echo "gate passed; running workers"
nice -n 15 python3 hv60_run.py 0 2 > worker_0.log 2>&1 &
P0=$!
nice -n 15 python3 hv60_run.py 1 2 > worker_1.log 2>&1 &
P1=$!
wait $P0; wait $P1
if python3 hv60_finalize.py > finalize.log 2>&1; then
  date -Is > DONE
  echo "done"; cat output/FINAL_LINES.txt
else
  echo "finalize failed; see finalize.log (will retry next run)"
fi
