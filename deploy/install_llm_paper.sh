#!/usr/bin/env bash
# Operator deployment: install the LLM paper-test timers. API keys go in /home/ubuntu/easystock/.env
# (OPENAI_API_KEY, ANTHROPIC_API_KEY); a missing key only drops that provider for the day.
set -euo pipefail
cd /home/ubuntu/easystock
sudo install -d -m 0700 -o ubuntu -g ubuntu /home/ubuntu/easystock-llm-paper
for unit in easystock-llm-pick.service easystock-llm-pick.timer easystock-llm-feed.service easystock-llm-feed.timer; do
  sudo install -m 0644 "deploy/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now easystock-llm-pick.timer easystock-llm-feed.timer
for k in OPENAI_API_KEY ANTHROPIC_API_KEY; do
  if grep -q "^$k=." .env 2>/dev/null; then echo "$k: set"; else echo "$k: MISSING"; fi
done
systemctl list-timers 'easystock-llm-*' --no-pager
