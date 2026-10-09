#!/usr/bin/env bash
# REVENUE_FORWARD_V1 daily trigger (cron 21:00 Taiwan time). Freezes the decile picks on the deadline evening only.
# The daily DB records today's session only after the 22:30 collector, so today's open/closed state comes from the
# production trading calendar (exit 0 = open).
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
PY=/home/ubuntu/easystock-learning-venv/bin/python
OPEN=()
if (cd /home/ubuntu/easystock && .venv/bin/python market_calendar.py --check-today >/dev/null 2>&1); then
  OPEN=(--open-today)
fi
M=$($PY rev_fwd.py due "${OPEN[@]}") || exit 0
echo "=== $(date -Is) deadline evening, revenue month $M"
$PY fwd_fetch.py "$M" && $PY rev_fwd.py picks --month "$M" "${OPEN[@]}"
