#!/usr/bin/env bash
# REVENUE_EARLY_V1 daily collector (cron 21:10 Taiwan time). Acts only on days 1-15; reads no price.
set -u
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
exec 9>snapshot.lock
flock -n 9 || { echo "already running"; exit 0; }
echo "=== $(date -Is)"
/usr/bin/python3 -I rev_snapshot.py
