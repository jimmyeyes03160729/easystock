#!/usr/bin/env bash
# Independent research timer; preserve deliberate disablement on later deploys.
set -euo pipefail
timer=easystock-rebound-research.timer
service=easystock-rebound-research.service
installed=0
active=0
[[ -f "/etc/systemd/system/$timer" ]] && installed=1
systemctl is-enabled --quiet "$timer" && active=1
sudo install -d -o ubuntu -g ubuntu -m 0700 /home/ubuntu/easystock-learning-data/rebound
sudo install -m 0644 "deploy/$timer" "/etc/systemd/system/$timer"
sudo install -m 0644 "deploy/$service" "/etc/systemd/system/$service"
sudo systemctl daemon-reload
if [[ "$installed" == 0 || "$active" == 1 ]]; then
  sudo systemctl enable --now "$timer"
else
  echo 'Rebound research timer was deliberately disabled; left disabled.'
fi
