#!/usr/bin/env bash
# REVENUE_FORWARD_V1 daily trigger (cron 21:00 Taiwan time). Freezes the decile picks on the deadline evening only.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
PY=/home/ubuntu/easystock-learning-venv/bin/python
M=$($PY rev_fwd.py due) || exit 0
echo "=== $(date -Is) deadline evening, revenue month $M"
$PY fwd_fetch.py "$M" && $PY rev_fwd.py picks --month "$M"
