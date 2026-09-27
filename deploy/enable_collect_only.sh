#!/usr/bin/env bash
# Schedule a paper engine that records observations but cannot create ENTRY.
set -euo pipefail
cd /home/ubuntu/easystock
export SYSTEMD_PAGER=cat

sudo systemctl disable --now easystock-intraday.timer
if systemctl is-active --quiet easystock-intraday.service; then
  echo '當沖服務正在執行，停止模式切換。' >&2
  exit 1
fi
cmp intraday_live.py vm_runtime/intraday_live.py
.venv/bin/python3 -m py_compile intraday_live.py
.venv/bin/python3 vm_runtime/tests/test_runtime_safety.py -q
.venv/bin/python3 - <<'PY'
import sqlite3
from pathlib import Path
db = Path('/home/ubuntu/easystock-admin/state.sqlite')
with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as con:
    count = con.execute('SELECT COUNT(*) FROM paper_trade_positions').fetchone()[0]
if count:
    raise SystemExit(f'尚有 {count} 筆持倉；停止啟動只收資料模式。')
print('持倉數：0')
PY

sudo install -d -m 0755 /etc/easystock
printf 'collect-only\n' | sudo tee /etc/easystock/collect-only >/dev/null
sudo chmod 0644 /etc/easystock/collect-only
test -f /etc/easystock/collect-only
sudo systemctl enable --now easystock-intraday.timer
echo '只收資料標記已建立；當沖 timer 已排程，ENTRY 在程式與帳本 callback 雙重阻擋。'
systemctl list-timers --all easystock-intraday.timer --no-pager
