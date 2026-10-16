#!/usr/bin/env bash
# Frontend-only main fast-forward. Never restarts jobs, migrates data, or edits env.
set -euo pipefail
target="${1:?Expected source commit is required}"
[[ "$target" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit'; exit 1; }
runtime="${EASYSTOCK_RUNTIME:-/home/ubuntu/easystock}"
backup_root="${EASYSTOCK_HOME_BACKUPS:-/home/ubuntu/easystock-maintenance}"
cd "$runtime"
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
    index.html|assets/*|tests/*.cjs|package.json|.github/workflows/deploy-homepage-vm.yml|deploy/sync_homepage_vm.sh|docs/HOMEPAGE_RELEASE_2026-10-17.md) ;;
    *) echo "Non-homepage change requires separate review: $file"; exit 1 ;;
  esac
done < <(git diff --name-only "$before" "$target")
# Validate the exact incoming blobs before touching the working checkout.
python3 - "$target" <<'PY'
import hashlib,re,subprocess,sys
commit=sys.argv[1]
def blob(path): return subprocess.check_output(['git','show',f'{commit}:{path}'])
html=blob('index.html').decode()
assert 'home-v2' in html and 'assets/chrome-logo.svg' in html
for path,digest in re.findall(r'(assets/[^"?]+\.(?:css|js))\?v=([0-9a-f]{12})',html):
    data=blob(path).decode().replace('\r\n','\n').encode()
    assert hashlib.sha256(data).hexdigest()[:12]==digest,path
for path in ['assets/glass-home.js','assets/glass-home.css','assets/chrome-logo.svg']:
    assert blob(path),path
print('Incoming homepage assets verified')
PY
backup="$backup_root/homepage-$(date -u +%Y%m%dT%H%M%SZ)-${before:0:8}"
mkdir -p "$backup"
chmod 700 "$backup"
git archive "$before" -- index.html assets | gzip > "$backup/homepage-before.tar.gz"
printf '%s\n' "$before" > "$backup/source-before.txt"
git merge --ff-only "$target"
[[ "$(git rev-parse HEAD)" == "$target" ]]
git diff --quiet HEAD --
printf '%s\n' "$target" > "$backup/source-after.txt"
sha256sum index.html assets/glass-home.js assets/glass-home.css assets/chrome-logo.svg
printf 'Homepage source synchronized: %s\nBackup: %s\n' "$target" "$backup"
