#!/usr/bin/env bash
# Operator-only after deployment authorization. Preserve all published/history data.
set -euo pipefail
if systemctl cat easystock-short-term.timer >/dev/null 2>&1; then
  sudo systemctl disable --now easystock-short-term.timer
fi
if systemctl cat easystock-short-term.service >/dev/null 2>&1; then
  sudo systemctl stop easystock-short-term.service
fi
for unit in easystock-short-term.timer easystock-short-term.service; do
  sudo rm -f -- "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl reset-failed easystock-short-term.service 2>/dev/null || true
echo 'Retired old scheduler; existing data, frozen snapshots and research are preserved.'
