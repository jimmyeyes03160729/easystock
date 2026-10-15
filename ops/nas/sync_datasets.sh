#!/usr/bin/env bash
# NAS-initiated copy of backtest datasets that sync_from_vm.sh does not cover.
# Copy only: nothing on the VM is deleted except this run's own generated SQLite snapshot.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${NAS_CONFIG:-$SCRIPT_DIR/nas.env}"
[[ -r "$CONFIG_FILE" ]] && source "$CONFIG_FILE"

VM_HOST="${VM_HOST:-141.147.182.42}"
VM_USER="${VM_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-/workspace/.ssh/easystock_nas_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-/workspace/.ssh/known_hosts}"
DATASETS_ROOT="${DATASETS_ROOT:-/data/backup/vm/datasets}"
REMOTE_RECORDINGS_DIR="${REMOTE_RECORDINGS_DIR:-/home/ubuntu/easystock-runway-v2/recordings}"
REMOTE_HISTORY_DIR="${REMOTE_HISTORY_DIR:-/home/ubuntu/easystock-history-expanded-data}"
REMOTE_MARKET_DAILY_DB="${REMOTE_MARKET_DAILY_DB:-/home/ubuntu/easystock-learning-data/rebound/market-daily.sqlite}"
REMOTE_REBOUND_V2_DB="${REMOTE_REBOUND_V2_DB:-/home/ubuntu/easystock-learning-data/rebound/dataset-v2.sqlite}"
REMOTE_SNAPSHOT_ROOT="${REMOTE_SNAPSHOT_ROOT:-/home/ubuntu/easystock-sync-snapshots}"
DATASET_SNAPSHOT_KEEP_DAYS="${DATASET_SNAPSHOT_KEEP_DAYS:-7}"

log() { printf '%s [datasets] %s\n' "$(date -Iseconds)" "$*"; }
# Optional uid:gid (e.g. the NAS login account) so copies are readable without root; unset keeps VM ownership.
RSYNC_OWNER=(); [[ -n "${BACKUP_CHOWN:-}" ]] && RSYNC_OWNER=(--chown="$BACKUP_CHOWN" --chmod=D750,F640)
die() { log "ERROR: $*" >&2; exit 1; }

[[ -r "$SSH_KEY" ]] || die "SSH key is not readable: $SSH_KEY"
[[ -r "$KNOWN_HOSTS" ]] || die "verified known_hosts is required: $KNOWN_HOSTS"
for cmd in ssh rsync python3 flock mountpoint; do command -v "$cmd" >/dev/null || die "$cmd is required"; done
mountpoint -q /data || mountpoint -q /data/backup/vm || die '/data or /data/backup/vm must be a persistent mount point'

mkdir -p "$DATASETS_ROOT/runway-recordings" "$DATASETS_ROOT/history-expanded" "$DATASETS_ROOT/sqlite"
exec 9>"$DATASETS_ROOT/.sync.lock"
flock -n 9 || die 'another dataset sync is already running'

STAMP="$(date +%Y%m%d-%H%M%S)"
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20 -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes)
REMOTE="$VM_USER@$VM_HOST"
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

log "Checking SSH reachability to $REMOTE"
ssh "${SSH_OPTS[@]}" "$REMOTE" 'true' || die 'Oracle VM SSH check failed'

# Recordings and tick archives are immutable per day; rsync is incremental and never uses --delete,
# so a VM-side cleanup can never remove the NAS copy.
log 'Copying B-lane input recordings'
rsync -a "${RSYNC_OWNER[@]}" --human-readable --partial --exclude='*.tmp' -e "$RSYNC_SSH" \
  "$REMOTE:$REMOTE_RECORDINGS_DIR/" "$DATASETS_ROOT/runway-recordings/" || die 'recordings rsync failed'

log 'Copying expanded tick and 1-minute history (completed files only)'
rsync -a "${RSYNC_OWNER[@]}" --human-readable --partial --exclude='*.tmp' --exclude='*.lock' --exclude='parts/' -e "$RSYNC_SSH" \
  "$REMOTE:$REMOTE_HISTORY_DIR/" "$DATASETS_ROOT/history-expanded/" || die 'history rsync failed'

log 'Creating consistent SQLite snapshots on the VM'
printf -v REMOTE_COMMAND 'env REMOTE_MARKET_DAILY_DB=%q REMOTE_REBOUND_V2_DB=%q REMOTE_SNAPSHOT_ROOT=%q STAMP=%q bash -s' \
  "$REMOTE_MARKET_DAILY_DB" "$REMOTE_REBOUND_V2_DB" "$REMOTE_SNAPSHOT_ROOT" "$STAMP"
REMOTE_SNAPSHOT_DIR="$(ssh "${SSH_OPTS[@]}" "$REMOTE" "$REMOTE_COMMAND" <<'REMOTE_PY'
set -Eeuo pipefail
python3 - <<'PY'
import os, pathlib, shutil, sqlite3
root = pathlib.Path(os.environ['REMOTE_SNAPSHOT_ROOT']).resolve()
sources = {'market-daily.sqlite': pathlib.Path(os.environ['REMOTE_MARKET_DAILY_DB']).resolve(),
           'rebound-dataset-v2.sqlite': pathlib.Path(os.environ['REMOTE_REBOUND_V2_DB']).resolve()}
need = sum(p.stat().st_size for p in sources.values() if p.is_file())
for name, source in sources.items():
    if not source.is_file():
        raise SystemExit(f'{name}: live database missing: {source}')
    if source == root or root in source.parents:
        raise SystemExit(f'{name}: source must not be inside snapshot directory')
root.mkdir(parents=True, exist_ok=True)
# Keep a 3 GB reserve so a snapshot can never fill the trading VM's disk.
if shutil.disk_usage(root).free < need + 3 * 1024 ** 3:
    raise SystemExit('not enough free VM disk for dataset snapshots')
target = root / ('datasets-' + os.environ['STAMP'])
target.mkdir(exist_ok=False)
for name, source in sources.items():
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        out = sqlite3.connect(target / name)
        try:
            src.backup(out)
            if out.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError(f'{name}: remote integrity_check failed')
        finally:
            out.close()
    finally:
        src.close()
print(target)
PY
REMOTE_PY
)" || die 'VM SQLite snapshot creation failed (VM snapshot kept for investigation)'
[[ "$REMOTE_SNAPSHOT_DIR" == "$REMOTE_SNAPSHOT_ROOT/datasets-$STAMP" ]] || die "Unexpected VM snapshot path: $REMOTE_SNAPSHOT_DIR"

# Staging persists between runs so rsync only transfers changed pages of the large databases.
STAGING="$DATASETS_ROOT/sqlite/.staging"
TARGET_DIR="$DATASETS_ROOT/sqlite/$STAMP"
mkdir -p "$STAGING"
log "Copying SQLite snapshots to $TARGET_DIR"
rsync -a "${RSYNC_OWNER[@]}" --human-readable --partial --inplace --no-whole-file -e "$RSYNC_SSH" \
  "$REMOTE:$REMOTE_SNAPSHOT_DIR/" "$STAGING/" || die 'SQLite snapshot transfer failed'
python3 - "$STAGING" <<'PY'
import pathlib, sqlite3, sys
folder = pathlib.Path(sys.argv[1])
for name in ('market-daily.sqlite', 'rebound-dataset-v2.sqlite'):
    con = sqlite3.connect((folder / name).resolve().as_uri() + '?mode=ro', uri=True)
    try:
        result = con.execute('PRAGMA integrity_check').fetchall()
    finally:
        con.close()
    if result != [('ok',)]:
        raise SystemExit(f'{name}: integrity_check returned {result!r}')
    print(f'{name}: ok')
PY
mkdir -p "$TARGET_DIR"
cp --reflink=auto "$STAGING/market-daily.sqlite" "$STAGING/rebound-dataset-v2.sqlite" "$TARGET_DIR/"
touch "$TARGET_DIR/.complete"
# cp runs as root, so hand the dated copy to the configured reader as well.
[[ -n "${BACKUP_CHOWN:-}" ]] && chown -R "$BACKUP_CHOWN" "$TARGET_DIR"

log 'Removing this run'"'"'s VM snapshot after NAS validation'
ssh "${SSH_OPTS[@]}" "$REMOTE" "$REMOTE_COMMAND" <<'REMOTE_CLEANUP' || die 'VM snapshot cleanup failed; LAST_SUCCESS not updated'
set -Eeuo pipefail
python3 - <<'PY'
import os, pathlib, re, shutil
allowed_root = pathlib.Path('/home/ubuntu/easystock-sync-snapshots')
root = pathlib.Path(os.environ['REMOTE_SNAPSHOT_ROOT'])
stamp = os.environ['STAMP']
if root != allowed_root or root.resolve() != allowed_root:
    raise SystemExit(f'refusing cleanup outside dedicated VM snapshot root: {root}')
if not re.fullmatch(r'\d{8}-\d{6}', stamp):
    raise SystemExit('refusing cleanup with invalid snapshot timestamp')
target = root / ('datasets-' + stamp)
if target.is_symlink() or not target.is_dir() or target.resolve().parent != allowed_root:
    raise SystemExit(f'refusing cleanup of unexpected snapshot directory: {target}')
for key in ('REMOTE_MARKET_DAILY_DB', 'REMOTE_REBOUND_V2_DB'):
    source = pathlib.Path(os.environ[key]).resolve()
    if target in source.parents:
        raise SystemExit(f'refusing cleanup containing source database: {source}')
expected = {'market-daily.sqlite', 'rebound-dataset-v2.sqlite'}
entries = list(target.iterdir())
if {e.name for e in entries} != expected or any(e.is_symlink() or not e.is_file() for e in entries):
    raise SystemExit('refusing cleanup of VM snapshot containing unexpected entries')
shutil.rmtree(target)
PY
REMOTE_CLEANUP

# Retention applies only to completed, dated direct children of the local SQLite snapshot root.
SQLITE_ROOT_REAL="$(realpath "$DATASETS_ROOT/sqlite")"
while IFS= read -r -d '' old_dir; do
  old_real="$(realpath "$old_dir")"
  case "$old_real" in
    "$SQLITE_ROOT_REAL"/*) rm -rf -- "$old_real" ;;
    *) die "refusing to prune outside SQLite snapshot root: $old_real" ;;
  esac
done < <(find "$SQLITE_ROOT_REAL" -mindepth 1 -maxdepth 1 -type d -name '????????-??????' \
           -mtime +"$((DATASET_SNAPSHOT_KEEP_DAYS - 1))" -print0)

TMP_LAST="$DATASETS_ROOT/.LAST_SUCCESS.$$.tmp"
date -Iseconds > "$TMP_LAST"
mv -f "$TMP_LAST" "$DATASETS_ROOT/LAST_SUCCESS"
log 'SUCCESS: datasets copied; LAST_SUCCESS updated'
