#!/usr/bin/env bash
# Operator deployment: install the market events tracker timers and run one full sync.
set -euo pipefail
cd /home/ubuntu/easystock
sudo install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/easystock-market-events
for unit in easystock-market-events.service easystock-market-events.timer \
            easystock-market-events-realtime.service easystock-market-events-realtime.timer; do
  sudo install -m 0644 "deploy/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now easystock-market-events.timer easystock-market-events-realtime.timer
sudo systemctl start easystock-market-events.service
