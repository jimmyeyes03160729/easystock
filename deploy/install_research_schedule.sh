#!/usr/bin/env bash
# Switch the post-close schedule to the current five-feature candidate pipeline.
# Does not start an intraday engine or promote any model.
set -euo pipefail
cd /home/ubuntu/easystock
export SYSTEMD_PAGER=cat

if systemctl is-active --quiet easystock-intraday.timer ||
   systemctl is-active --quiet easystock-intraday.service ||
   systemctl is-active --quiet easystock-research-cycle.service; then
  echo '交易或研究服務正在執行，停止排程變更。' >&2
  exit 1
fi

.venv/bin/python3 -m py_compile learning_cycle.py learning_eod.py
if [[ ! -x /home/ubuntu/easystock-learning-venv/bin/python ]]; then
  echo '缺少研究用 Python 環境。' >&2
  exit 1
fi
/home/ubuntu/easystock-learning-venv/bin/python -c 'import sklearn, dotenv, daytrade_learning.research'

backup="/home/ubuntu/easystock-maintenance/research-schedule-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 "$backup"
for name in easystock-research-cycle.service easystock-research-cycle.timer; do
  if [[ -f "/etc/systemd/system/$name" ]]; then
    sudo cp -p "/etc/systemd/system/$name" "$backup/$name"
  fi
done
sudo install -m 0644 deploy/easystock-research-cycle.service /etc/systemd/system/easystock-research-cycle.service
sudo install -m 0644 deploy/easystock-research-cycle.timer /etc/systemd/system/easystock-research-cycle.timer
sudo systemctl daemon-reload
sudo systemctl disable --now easystock-paper-train.timer easystock-paper-feedback.timer
sudo systemctl enable --now easystock-research-cycle.timer

echo "Schedule backup: $backup"
for unit in easystock-intraday.timer easystock-learning.timer easystock-paper-train.timer easystock-paper-feedback.timer easystock-research-cycle.timer; do
  printf '%s: ' "$unit"
  systemctl is-active "$unit" || true
  systemctl is-enabled "$unit" || true
done
systemctl list-timers --all easystock-research-cycle.timer --no-pager
