#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/easystock
test -x /usr/bin/node
test -d vm_runtime/esun_marketdata/node_modules/@esun/marketdata
sudo install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/easystock-market-data
for name in easystock-esun-marketdata.service easystock-provider-health.service easystock-provider-health.timer; do
  sudo install -m 644 "deploy/$name" "/etc/systemd/system/$name"
done
sudo systemctl daemon-reload
sudo systemctl enable easystock-esun-marketdata.service
sudo systemctl enable --now easystock-provider-health.timer
sudo systemctl restart easystock-esun-marketdata.service
.venv/bin/python deploy/install_provider_rules.py
sudo systemctl start easystock-provider-health.service
# Reload the authenticated admin dashboard served by the existing web process.
sudo systemctl try-restart easystock-line-stock-bot.service
