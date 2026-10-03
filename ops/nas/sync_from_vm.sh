#!/usr/bin/env bash
# NAS-initiated backup. VM writes are limited to generated snapshot files.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${NAS_CONFIG:-$SCRIPT_DIR/nas.env}"
[[ -r "$CONFIG_FILE" ]] && source "$CONFIG_FILE"

VM_HOST="${VM_HOST:-141.147.182.42}"
VM_USER="${VM_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-/workspace/.ssh/easystock_nas_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-/workspace/.ssh/known_hosts}"
BACKUP_ROOT="${BACKUP_ROOT:-/data/backup/vm}"
REMOTE_LEARNING_DIR="${REMOTE_LEARNING_DIR:-/home/ubuntu/easystock-learning-data}"
REMOTE_REBOUND_DB="${REMOTE_REBOUND_DB:-/home/ubuntu/easystock-learning-data/rebound/dataset.sqlite}"
REMOTE_RESEARCH_DB="${REMOTE_RESEARCH_DB:-/home/ubuntu/easystock-learning-data/research.sqlite}"
REMOTE_DECISIONS_DB="${REMOTE_DECISIONS_DB:-/home/ubuntu/easystock-learning-data/decisions.sqlite}"
REMOTE_ADMIN_DB="${REMOTE_ADMIN_DB:-/home/ubuntu/easystock-admin/state.sqlite}"
REMOTE_SNAPSHOT_ROOT="${REMOTE_SNAPSHOT_ROOT:-/home/ubuntu/easystock-sync-snapshots}"

log() { printf '%s [sync] %s\n' "$(date -Iseconds)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

[[ -r "$SSH_KEY" ]] || die "SSH key is not readable: $SSH_KEY"
command -v ssh >/dev/null || die 'ssh is required'
command -v rsync >/dev/null || die 'rsync is required'
command -v python3 >/dev/null || die 'python3 is required for local SQLite validation'
command -v mountpoint >/dev/null || die 'mountpoint is required'
mountpoint -q /data || mountpoint -q "$BACKUP_ROOT" || die '/data or backup root must be a persistent mount point'

mkdir -p "$BACKUP_ROOT/learning-data" "$BACKUP_ROOT/sqlite"
command -v flock >/dev/null || die 'flock is required'
exec 9>"$BACKUP_ROOT/.sync.lock"
flock -n 9 || die 'another NAS sync is already running'
STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET_DIR="$BACKUP_ROOT/sqlite/$STAMP"
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20)
[[ -r "$KNOWN_HOSTS" ]] || die "verified known_hosts is required: $KNOWN_HOSTS"
SSH_OPTS+=(-o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes)
REMOTE="$VM_USER@$VM_HOST"

cleanup_local() {
  if [[ -d "$TARGET_DIR" && ! -f "$TARGET_DIR/.complete" ]]; then
    log "Keeping incomplete NAS snapshot for investigation: $TARGET_DIR"
  fi
}
trap cleanup_local EXIT

log "Checking SSH reachability to $REMOTE"
ssh "${SSH_OPTS[@]}" "$REMOTE" 'true' || die 'Oracle VM SSH check failed'

log 'Synchronizing non-SQLite learning data'
# No --delete: a transient remote problem can never remove an NAS backup copy.
rsync -a --human-readable --partial \
  --exclude='*.sqlite' --exclude='*.sqlite-wal' --exclude='*.sqlite-shm' \
  -e "ssh ${SSH_OPTS[*]}" \
  "$REMOTE:$REMOTE_LEARNING_DIR/" "$BACKUP_ROOT/learning-data/"

log 'Creating consistent SQLite backups on the VM using sqlite3.Connection.backup()'
# Quote remote configuration safely for bash, including spaces and apostrophes.
printf -v REMOTE_COMMAND 'env REMOTE_REBOUND_DB=%q REMOTE_RESEARCH_DB=%q REMOTE_DECISIONS_DB=%q REMOTE_ADMIN_DB=%q REMOTE_SNAPSHOT_ROOT=%q STAMP=%q bash -s' \
  "$REMOTE_REBOUND_DB" "$REMOTE_RESEARCH_DB" "$REMOTE_DECISIONS_DB" "$REMOTE_ADMIN_DB" "$REMOTE_SNAPSHOT_ROOT" "$STAMP"
REMOTE_SNAPSHOT_DIR="$(ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "$REMOTE_COMMAND" <<'REMOTE_PY'
set -Eeuo pipefail
python3 - <<'PY'
import os, pathlib, sqlite3, sys

snapshot_root = pathlib.Path(os.environ['REMOTE_SNAPSHOT_ROOT']).resolve()
stamp = os.environ['STAMP']
sources = {
    'rebound-dataset.sqlite': pathlib.Path(os.environ['REMOTE_REBOUND_DB']).resolve(),
    'research.sqlite': pathlib.Path(os.environ['REMOTE_RESEARCH_DB']).resolve(),
    'decisions.sqlite': pathlib.Path(os.environ['REMOTE_DECISIONS_DB']).resolve(),
    'admin-state.sqlite': pathlib.Path(os.environ['REMOTE_ADMIN_DB']).resolve(),
}
for name, source in sources.items():
    if not source.is_file():
        raise SystemExit(f'{name}: live database missing: {source}')
    if source == snapshot_root or snapshot_root in source.parents:
        raise SystemExit(f'{name}: source must not be inside snapshot directory')
target = snapshot_root / stamp
target.mkdir(parents=True, exist_ok=False)
try:
    for name, source in sources.items():
        dest = target / name
        src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        try:
            out = sqlite3.connect(dest)
            try:
                src.backup(out)
                result = out.execute('PRAGMA integrity_check').fetchall()
                if result != [('ok',)]:
                    raise RuntimeError(f'{name}: remote integrity_check returned {result!r}')
            finally:
                out.close()
        finally:
            src.close()
    print(target)
except Exception:
    # Only remove the generated, incomplete directory; never touch source databases.
    import shutil
    shutil.rmtree(target, ignore_errors=True)
    raise
PY
REMOTE_PY
)" || die 'VM SQLite snapshot creation failed'
[[ "$REMOTE_SNAPSHOT_DIR" == /* ]] || die "Unexpected VM snapshot path: $REMOTE_SNAPSHOT_DIR"

log "Copying SQLite snapshot to $TARGET_DIR"
mkdir -p "$TARGET_DIR"
rsync -a --human-readable --partial -e "ssh ${SSH_OPTS[*]}" \
  "$REMOTE:$REMOTE_SNAPSHOT_DIR/" "$TARGET_DIR/" || die 'SQLite snapshot transfer failed'

log 'Validating copied SQLite snapshots'
python3 - "$TARGET_DIR" <<'PY'
import pathlib, sqlite3, sys
folder = pathlib.Path(sys.argv[1])
for name in ('rebound-dataset.sqlite', 'research.sqlite', 'decisions.sqlite', 'admin-state.sqlite'):
    path = folder / name
    if not path.is_file():
        raise SystemExit(f'missing snapshot: {path}')
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        result = con.execute('PRAGMA integrity_check').fetchall()
    finally:
        con.close()
    if result != [('ok',)]:
        raise SystemExit(f'{name}: integrity_check returned {result!r}')
    print(f'{name}: ok')
PY

touch "$TARGET_DIR/.complete"
# Retention applies only to resolved direct children of the configured local snapshot root.
SNAPSHOT_ROOT_REAL="$(realpath "$BACKUP_ROOT/sqlite")"
while IFS= read -r -d '' old_dir; do
  old_dir_real="$(realpath "$old_dir")"
  case "$old_dir_real" in
    "$SNAPSHOT_ROOT_REAL"/*) rm -rf -- "$old_dir_real" ;;
    *) die "refusing to prune outside snapshot root: $old_dir_real" ;;
  esac
done < <(find "$SNAPSHOT_ROOT_REAL" -mindepth 1 -maxdepth 1 -type d -name '????????-??????' -mtime +13 -print0)
TMP_LAST="$BACKUP_ROOT/.LAST_SUCCESS.$$.tmp"
date -Iseconds > "$TMP_LAST"
mv -f "$TMP_LAST" "$BACKUP_ROOT/LAST_SUCCESS"
log "SUCCESS: backup completed; LAST_SUCCESS updated"
