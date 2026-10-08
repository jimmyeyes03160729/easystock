#!/usr/bin/env bash
# Main-only update, preserving VM-local work, data, and the prior timer mode.
set -euo pipefail
cd /home/ubuntu/easystock
export GIT_PAGER=cat SYSTEMD_PAGER=cat
restore_intraday_timer=0
collect_only_before=0
systemctl is-enabled --quiet easystock-intraday.timer && restore_intraday_timer=1
test -f /etc/easystock/collect-only && collect_only_before=1
# preflight: checkout untouched. code: checkout changed, nothing else yet, so a
# failure rolls the checkout back. mutating: migrations / env / services may have
# changed, so a failure keeps the new checkout and leaves the timer off.
phase=preflight
pre_update_head=''
backup=''
rollback_code() {
  git reset --hard --quiet "$pre_update_head" || return 1
  if [[ -d "$backup/untracked" ]]; then
    cp -a "$backup/untracked/." ./ || return 1
  fi
  if [[ -f "$backup/release-info-before.json" ]]; then
    cp -p "$backup/release-info-before.json" release-info.json || return 1
  else
    rm -f release-info.json || return 1
  fi
  [[ "$(git rev-parse HEAD)" == "$pre_update_head" ]] && git diff --quiet HEAD --
}
restore_timer() {
  status=$?
  trap - EXIT
  timer_safe=1
  if [[ "$status" != 0 && "$phase" == code ]]; then
    echo "更新後驗證失敗；將程式回滾到 ${pre_update_head:0:12}。" >&2
    if rollback_code; then
      echo "已回滾到更新前的程式：$(git rev-parse --short HEAD)。" >&2
    else
      echo "程式回滾失敗；目前 HEAD=$(git rev-parse --short HEAD)，備份：$backup" >&2
      timer_safe=0
    fi
  elif [[ "$status" != 0 && "$phase" == mutating ]]; then
    echo "migrate / 安裝步驟失敗；資料庫或服務設定可能已變更，不自動回滾程式。備份：$backup" >&2
    timer_safe=0
  fi
  if [[ "$restore_intraday_timer" == 1 ]] && ! systemctl is-enabled --quiet easystock-intraday.timer; then
    if [[ "$collect_only_before" == 1 ]]; then
      restore_command=(bash deploy/enable_collect_only.sh)
      restore_label='collect-only 排程'
    else
      restore_command=(sudo systemctl enable --now easystock-intraday.timer)
      restore_label='模擬買進排程'
    fi
    if [[ "$timer_safe" != 1 ]]; then
      echo "不自動恢復${restore_label}；人工確認程式與資料後再執行：${restore_command[*]}" >&2
    elif "${restore_command[@]}"; then
      echo "已恢復同步前的${restore_label}。"
    else
      echo "無法自動恢復${restore_label}；請檢查上方輸出。" >&2
      [[ "$status" == 0 ]] && status=1
    fi
  fi
  exit "$status"
}
trap restore_timer EXIT
sudo systemctl disable --now easystock-intraday.timer
for unit in easystock-intraday.service easystock-learning.service easystock-paper-train.service easystock-history-download.service easystock-history-train.service; do
  if systemctl is-active --quiet "$unit"; then
    echo "仍在執行：$unit；尚未更新程式，請待該工作結束。"
    exit 1
  fi
done
if ! git diff --quiet HEAD --; then
  echo 'VM 有已追蹤檔案的本機修改，保留原檔並停止更新。'
  git status --short
  exit 1
fi
git fetch origin main
git merge-base --is-ancestor HEAD origin/main || {
  echo 'VM 有尚未整合的提交，保留提交並停止更新。'; exit 1;
}
backup="/home/ubuntu/easystock-maintenance/main-update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 "$backup"
printf '備份位置：%s\n' "$backup"
git bundle create "$backup/repo-before.bundle" --all
pre_update_head="$(git rev-parse HEAD)"
if [[ -f release-info.json ]]; then
  cp -p release-info.json "$backup/release-info-before.json"
fi
phase=code
python3 - "$backup" <<'PY'
from contextlib import closing
from pathlib import Path
import os
import shutil,sqlite3,subprocess,sys
backup=Path(sys.argv[1])
source=Path('/home/ubuntu/easystock-admin/state.sqlite')
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(backup/'state-before.sqlite')) as dst:
    src.backup(dst)
research_source = Path(os.environ.get('LEARNING_DATA_DIR', '/home/ubuntu/easystock-learning-data'))/'research.sqlite'
if research_source.exists():
    with closing(sqlite3.connect(research_source.resolve().as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(backup/'research-before.sqlite')) as dst:
        src.backup(dst)
# Preserve locally installed, untracked modules before Git starts tracking them.
paths=subprocess.check_output(['git','ls-tree','-rz','--name-only','origin/main']).decode().split('\0')
for rel in filter(None,paths):
    path=Path(rel)
    tracked=subprocess.run(['git','ls-files','--error-unmatch','--',rel],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if path.exists() and not tracked:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Untracked path requires review: '+rel)
        dest=backup/'untracked'/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(path),str(dest))
        print('已備份本機檔案：'+rel)
PY
git merge --ff-only origin/main
current="$(git branch --show-current)"
if [[ "$current" != main ]]; then
  if git show-ref --verify --quiet refs/heads/main; then
    git branch -m main "vm-previous-main-$(date +%Y%m%d-%H%M%S)"
  fi
  git branch -m main
fi
git branch --set-upstream-to=origin/main main
commit="$(git rev-parse HEAD)"
cat > release-info.json <<EOF
{
  "release_id": "main-${commit:0:12}",
  "source_commit": "${commit}",
  "channel": "main"
}
EOF
chmod 600 release-info.json
.venv/bin/python3 vm_runtime/tests/test_cash_ledger.py -q
.venv/bin/python3 deploy/verify_research_episodes.py
.venv/bin/python3 tests/test_market_risk_gate.py -q
.venv/bin/python3 vm_runtime/tests/test_runtime_safety.py -q
.venv/bin/python3 history/test_daily_history.py -q
.venv/bin/python3 tests/test_paper_legacy.py -q
.venv/bin/python3 tests/test_research_schedule.py -q
.venv/bin/python3 deploy/verify_paper_ledger.py --runtime /home/ubuntu/easystock
phase=mutating
.venv/bin/python3 deploy/migrate_paper_daily_limit.py --apply --backup-dir "$backup"
python3 - <<'PY'
from pathlib import Path
import os

updates={
    'LIVE_ENTRY_MODE':'model',
    'AI_PAPER_MODEL_PATH':'/home/ubuntu/easystock-learning-data/models/latest-approved.json',
    'MODEL_RUNTIME_STATUS_PATH':'/home/ubuntu/easystock-learning-data/models/runtime-model-status.json',
}
paths = [Path('/home/ubuntu/easystock/.env'), Path('/home/ubuntu/easystock-ai-paper.env')]
for path in paths:
    if not path.exists() and path.name != '.env':
        continue
    lines=path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    seen=set(); out=[]
    for line in lines:
        key=line.split('=',1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
        if key in updates:
            if key not in seen:
                out.append(f'{key}={updates[key]}'); seen.add(key)
        else:
            out.append(line)
    for key,value in updates.items():
        if key not in seen: out.append(f'{key}={value}')
    temp=path.with_name(path.name+'.env.tmp')
    temp.write_text('\n'.join(out)+'\n',encoding='utf-8')
    temp.chmod(0o600); os.replace(temp,path)
    print('已更新正式 intraday 環境：'+str(path))
PY
bash deploy/install_market_data.sh
bash deploy/install_history_schedule.sh
bash deploy/install_rebound_research.sh
.venv/bin/python -m guardian.cli validate-policy
bash deploy/install_architecture_guardian.sh
phase=done
printf '主線更新完成：'
git rev-parse --short HEAD
printf '備份位置：%s\n' "$backup"
if [[ "$restore_intraday_timer" == 1 ]]; then
  echo '同步前 timer 已啟用；結束時會自動恢復相同模式。'
else
  echo '當沖 timer 保持停用；帳本副本驗證通過後，仍需核對模型與訓練服務。歷史下載於原排程執行時更新近期日期並嘗試擴充至 100 檔。'
fi
