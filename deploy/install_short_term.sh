#!/usr/bin/env bash
# Operator deployment: install the short-term feed timer and publish once.
set -euo pipefail
cd /home/ubuntu/easystock
sudo install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/easystock-short-term
for unit in easystock-short-term.service easystock-short-term.timer; do
  sudo install -m 0644 "deploy/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now easystock-short-term.timer
sudo systemctl start easystock-short-term.service
