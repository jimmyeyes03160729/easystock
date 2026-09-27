#!/usr/bin/env bash
# Main-only update, preserving VM-local work and data; never resumes intraday automatically.
set -euo pipefail
cd /home/ubuntu/easystock
export GIT_PAGER=cat SYSTEMD_PAGER=cat
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
python3 - "$backup" <<'PY'
from contextlib import closing
from pathlib import Path
import shutil,sqlite3,subprocess,sys
backup=Path(sys.argv[1])
source=Path('/home/ubuntu/easystock-admin/state.sqlite')
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(backup/'state-before.sqlite')) as dst:
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
.venv/bin/python3 vm_runtime/tests/test_cash_ledger.py -q
.venv/bin/python3 vm_runtime/tests/test_runtime_safety.py -q
.venv/bin/python3 history/test_daily_history.py -q
.venv/bin/python3 tests/test_paper_legacy.py -q
.venv/bin/python3 deploy/verify_paper_ledger.py --runtime /home/ubuntu/easystock
printf '主線更新完成：'
git rev-parse --short HEAD
printf '備份位置：%s\n' "$backup"
echo '當沖 timer 保持停用；帳本副本驗證通過後，仍需核對模型與訓練服務。歷史下載於原排程執行時更新近期日期並嘗試擴充至 100 檔。'
