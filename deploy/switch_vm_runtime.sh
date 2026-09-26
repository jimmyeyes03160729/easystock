#!/usr/bin/env bash
# One-time migration from the audited VM-only commit. Run as ubuntu, never as root.
# Usage: bash switch_vm_runtime.sh <reviewed-branch-commit-sha>
set -Eeuo pipefail
umask 077

cd /home/ubuntu/easystock
old=ff381b8060778239f762660bd55b4f4697fcd146
target="${1:?Pass the exact reviewed GitHub commit SHA}"
backup=vm-backup-ff381-20260927
new_branch="deploy/daytrade-${target:0:7}"

[[ "$target" =~ ^[0-9a-f]{40}$ ]] || { echo "需要完整 40 字元提交 SHA" >&2; exit 1; }
test "$(git rev-parse HEAD)" = "$old"
test "$(git rev-parse "$backup")" = "$old"
test "$(git rev-parse origin/fix/daytrade-runtime-audit)" = "$target"
test -z "$(git status --porcelain --untracked-files=no)"
if systemctl is-active --quiet easystock-intraday.timer ||
   systemctl is-active --quiet easystock-intraday.service; then
    echo "請先停止當沖 timer 與服務，再執行切換。" >&2
    exit 1
fi
if git show-ref --verify --quiet "refs/heads/$new_branch"; then
    echo "部署分支已存在，停止以避免覆蓋。" >&2
    exit 1
fi

mapfile -t timers < <(systemctl list-units --type=timer --state=active --no-pager --no-legend --plain |
    awk '$1 ~ /^easystock-/ {print $1}')
services=()
for unit in easystock-telegram-stock-bot.service easystock-line-stock-bot.service easystock-guardian-proxy.service; do
    if systemctl is-active --quiet "$unit"; then services+=("$unit"); fi
done
switched=0
restore() {
    result=$?
    trap - EXIT
    if (( result != 0 )); then
        echo "部署失敗；嘗試切回 VM 原版。" >&2
        if (( ${#timers[@]} )); then sudo systemctl stop "${timers[@]}" || true; fi
        if (( ${#services[@]} )); then sudo systemctl stop "${services[@]}" || true; fi
        if (( switched )); then
            git switch main || echo "無法自動切回 main，請保持當沖 timer 停用。" >&2
        fi
        for unit in easystock-guardian-proxy.service easystock-line-stock-bot.service easystock-telegram-stock-bot.service; do
            for active in "${services[@]}"; do
                if [[ "$active" == "$unit" ]]; then sudo systemctl start "$unit" || echo "重啟失敗：$unit" >&2; fi
            done
        done
        if (( ${#timers[@]} )); then
            sudo systemctl start "${timers[@]}" || echo "部分 timer 未恢復，請檢查 systemctl。" >&2
        fi
    fi
    exit "$result"
}
trap restore EXIT

if (( ${#timers[@]} )); then sudo systemctl stop "${timers[@]}"; fi
if (( ${#services[@]} )); then sudo systemctl stop "${services[@]}"; fi

.venv/bin/python3 - <<'PY'
from pathlib import Path
from datetime import datetime
from dotenv import dotenv_values
import sqlite3

values = {}
for filename in ('/home/ubuntu/easystock/.env',
                 '/home/ubuntu/easystock-ai-paper.env',
                 '/home/ubuntu/easystock-admin.env',
                 '/home/ubuntu/easystock-learning.env'):
    if Path(filename).exists():
        values.update(dotenv_values(filename))
source = Path(values.get('EASYSTOCK_ADMIN_DB') or '/home/ubuntu/easystock-admin/state.sqlite')
if source.is_file():
    directory = Path('/home/ubuntu/easystock-maintenance/db-backups')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / ('state-before-daytrade-deploy-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite')
    with sqlite3.connect(str(source)) as current, sqlite3.connect(str(destination)) as saved:
        current.backup(saved)
    print('SQLite 已備份：', destination)
else:
    print('未找到預設的模擬帳務 SQLite，請核對 EASYSTOCK_ADMIN_DB；停止部署。')
    raise SystemExit(1)
PY

git switch -c "$new_branch" "$target"
switched=1
.venv/bin/python3 deploy/install_intraday_runtime.py --check-only
.venv/bin/python3 deploy/install_intraday_runtime.py
PYTHONPATH=vm_runtime:. .venv/bin/python3 vm_runtime/tests/test_runtime_safety.py -q
test -z "$(git status --porcelain --untracked-files=no)"

for unit in easystock-guardian-proxy.service easystock-line-stock-bot.service easystock-telegram-stock-bot.service; do
    for active in "${services[@]}"; do
        if [[ "$active" == "$unit" ]]; then
            sudo systemctl start "$unit"
            systemctl is-active --quiet "$unit"
        fi
    done
done
if (( ${#timers[@]} )); then sudo systemctl start "${timers[@]}"; fi
trap - EXIT
echo "部署驗證通過：$(git rev-parse --short HEAD)"
echo "當沖 timer 保持停用，等待下一交易日資料驗收。"
