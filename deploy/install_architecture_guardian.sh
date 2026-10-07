#!/usr/bin/env bash
# Operator deployment only; Guardian CLI cannot invoke this installer.
set -euo pipefail
cd /home/ubuntu/easystock
timer=easystock-architecture-guardian.timer
installed=0
enabled=0
[[ -f /etc/systemd/system/$timer ]] && installed=1
systemctl is-enabled --quiet "$timer" && enabled=1
sudo install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/easystock-architecture-guardian
for unit in easystock-architecture-guardian.service easystock-architecture-guardian.timer; do
  sudo install -m 0644 "deploy/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
if [[ "$installed" == 0 || "$enabled" == 1 ]]; then
  sudo systemctl enable --now "$timer"
else
  echo 'Architecture Guardian timer was deliberately disabled; preserving that state.'
fi
sudo systemctl start easystock-architecture-guardian.service
