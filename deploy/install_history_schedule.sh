#!/usr/bin/env bash
# Update only the download timer; preserve disabled schedules and running jobs.
set -euo pipefail
cd /home/ubuntu/easystock
timer=easystock-history-download.timer
was_active=0
systemctl is-active --quiet "$timer" && was_active=1
backup="/home/ubuntu/easystock-maintenance/history-timer-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 "$backup"
if [[ -f "/etc/systemd/system/$timer" ]]; then
  sudo cp -p "/etc/systemd/system/$timer" "$backup/"
fi
sudo install -m 0644 "deploy/$timer" "/etc/systemd/system/$timer"
sudo systemctl daemon-reload
if [[ "$was_active" == 1 ]]; then
  sudo systemctl restart "$timer"
  echo '歷史補抓 timer 已更新：每 15 分鐘觸發，由程式檢查設定時段與安全限制。'
else
  echo '歷史補抓 timer 已更新；保留原本未啟動狀態。'
fi
echo "備份位置：$backup"
