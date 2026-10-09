#!/usr/bin/env bash
# REVENUE_HIST_V1 one-shot runner (VM). Resumable: both fetchers skip what is already stored.
# 1) revenue 2014-01..2021-12  2) wait for other TWSE bulk fetchers  3) daily 2014-11-03..2022-03-31  4) study once.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
BASE=/home/ubuntu/easystock-research/revenue_hist_v1
REPO=$(cd ../.. && pwd)
PY=/home/ubuntu/easystock/.venv/bin/python
mkdir -p "$BASE/data" "$BASE/daily" "$BASE/output"
[ -e "$BASE/DONE" ] && { echo "already DONE"; exit 0; }

echo "=== $(date -Is) revenue fetch"
$PY hist_fetch_revenue.py "$BASE/data"

# Do not hit TWSE in parallel with another bulk fetcher (burst blocks).
while pgrep -f 'fetch_inst.py' >/dev/null; do sleep 300; done

echo "=== $(date -Is) daily fetch"
(cd "$REPO" && EASYSTOCK_REBOUND_DATA_DIR="$BASE/daily" $PY -m rebound_learning.market_daily --from 2014-11-03 --to 2022-03-31)
(cd "$REPO" && EASYSTOCK_REBOUND_DATA_DIR="$BASE/daily" $PY -m rebound_learning.market_daily --status) | tee "$BASE/output/daily_status.json"

echo "=== $(date -Is) study"
HIST_CODE_COMMIT=${HIST_CODE_COMMIT:-unknown} $PY hist_study.py | tee "$BASE/output/study.out"
echo "${HIST_CODE_COMMIT:-unknown} $(date -Is)" > "$BASE/DONE"
