#!/usr/bin/env bash
# Approved display/chart release. Never changes orders, ledger, env, or trading timers.
set -euo pipefail
target="${1:?Expected source commit is required}"
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit'; exit 1; }
runtime="${EASYSTOCK_RUNTIME:-/home/ubuntu/easystock}"
backup_root="${EASYSTOCK_HOME_BACKUPS:-/home/ubuntu/easystock-maintenance}"
cd "$runtime"
if systemctl is-active --quiet easystock-intraday.service; then
  echo 'Intraday engine is running; preserve its current source and deploy after the session'; exit 1
fi
exec 9>/tmp/easystock-homepage-deploy.lock
flock -n 9 || { echo 'Another homepage deployment is running'; exit 1; }
[[ "$(git branch --show-current)" == main ]] || { echo 'VM checkout is not on main; preserving it'; exit 1; }
git diff --quiet HEAD -- || { echo 'VM has tracked local changes; preserving them'; git status --short --untracked-files=no; exit 1; }
before="$(git rev-parse HEAD)"
git fetch "${EASYSTOCK_HOME_REMOTE:-https://github.com/jimmyeyes03160729/easystock.git}" main
[[ "$(git rev-parse FETCH_HEAD)" == "$target" ]] || { echo 'Main moved after approval; stop and recheck'; exit 1; }
git merge-base --is-ancestor HEAD "$target" || { echo 'VM has divergent commits; preserving them'; exit 1; }
while IFS= read -r file; do
  case "$file" in
    index.html|assets/*|tests/*.cjs|tests/test_trade_chart_feed.py|package.json|.github/workflows/deploy-homepage-vm.yml|.github/workflows/deploy-trade-charts-vm.yml|.github/workflows/inspect-trade-charts.yml|deploy/sync_homepage_vm.sh|deploy/sync_trade_charts_vm.sh|deploy/inspect_trade_charts.py|deploy/publish_trade_charts.py|deploy/grant_trade_chart_read.py|firebase.rules.json|deploy/easystock-trade-charts.service|deploy/easystock-trade-charts.timer|deploy/install_intraday_runtime.py|intraday_live.py|vm_runtime/intraday_live.py|trade_chart_feed.py|vm_runtime/trade_chart_feed.py|docs/HOMEPAGE_RELEASE_2026-10-17.md|docs/TRADE_CHARTS.md) ;;
    *) echo "Non-homepage change requires separate review: $file"; exit 1 ;;
  esac
done < <(git diff --name-only "$before" "$target")
# Validate the exact incoming blobs before touching the working checkout.
python3 - "$target" <<'PY'
import ast,hashlib,re,subprocess,sys
commit=sys.argv[1]
def blob(path): return subprocess.check_output(['git','show',f'{commit}:{path}'])
html=blob('index.html').decode()
assert 'home-v2' in html and 'assets/chrome-logo.svg' in html
for path,digest in re.findall(r'(assets/[^"?]+\.(?:css|js))\?v=([0-9a-f]{12})',html):
    data=blob(path).decode().replace('\r\n','\n').encode()
    assert hashlib.sha256(data).hexdigest()[:12]==digest,path
for path in ['assets/glass-home.js','assets/glass-home.css','assets/chrome-logo.svg']:
    assert blob(path),path
# The engine change is restricted to starting/stopping the display-only worker.
for path in ['intraday_live.py','vm_runtime/intraday_live.py']:
    old=subprocess.check_output(['git','show',f'HEAD:{path}']).decode()
    expected=old.replace('        self.install_callback()\n', '        self.install_callback()\n        # Public price charts reuse received bars; no broker requests or orders.\n        from trade_chart_feed import ChartPublisher\n        self.chart_publisher = ChartPublisher(self.store, self.bars)\n        self.chart_publisher.start()\n').replace('        self.running = False\n', "        self.running = False\n        charts = getattr(self, 'chart_publisher', None)\n        if charts: charts.stop()\n")
    incoming=blob(path).decode()
    assert incoming==expected or incoming==old,path+' contains an unexpected engine change'
    ast.parse(incoming)
assert blob('trade_chart_feed.py')==blob('vm_runtime/trade_chart_feed.py')
for path in ['trade_chart_feed.py','deploy/publish_trade_charts.py']:
    ast.parse(blob(path).decode())
print('Incoming homepage and chart-only engine hook verified')
PY
backup="$backup_root/homepage-$(date -u +%Y%m%dT%H%M%SZ)-${before:0:8}"
mkdir -p "$backup"
chmod 700 "$backup"
git archive "$before" -- index.html assets intraday_live.py vm_runtime/intraday_live.py deploy/install_intraday_runtime.py | gzip > "$backup/homepage-before.tar.gz"
printf '%s\n' "$before" > "$backup/source-before.txt"
git merge --ff-only "$target"
[[ "$(git rev-parse HEAD)" == "$target" ]]
git diff --quiet HEAD --
printf '%s\n' "$target" > "$backup/source-after.txt"
sha256sum index.html assets/glass-home.js assets/glass-home.css assets/chrome-logo.svg
printf 'Homepage source synchronized: %s\nBackup: %s\n' "$target" "$backup"

# Run isolated tests before enabling only the new price-cache publisher.
.venv/bin/python -m unittest discover -s tests -p test_trade_chart_feed.py -q
sudo systemd-analyze verify deploy/easystock-trade-charts.service deploy/easystock-trade-charts.timer
for unit in easystock-trade-charts.service easystock-trade-charts.timer; do
  if [[ -f "/etc/systemd/system/$unit" ]]; then cp "/etc/systemd/system/$unit" "$backup/$unit"; fi
  sudo install -m 644 "deploy/$unit" "/etc/systemd/system/$unit"
done
sudo systemctl daemon-reload
sudo systemctl start easystock-trade-charts.service
.venv/bin/python deploy/grant_trade_chart_read.py --backup-dir "$backup"
sudo systemctl enable --now easystock-trade-charts.timer
systemctl show easystock-trade-charts.service -p Result -p ExecMainStatus
systemctl is-active easystock-trade-charts.timer
printf 'Display-only chart feed installed; trading services were not restarted.\n'
