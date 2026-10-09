#!/usr/bin/env bash
# NAS-initiated five-level BidAsk archive move: pull sealed VM days, verify every sha256 on the NAS, then ask the VM
# to delete only days that are verified here AND at least 5 days old (the VM re-checks the manifest hash itself).
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${NAS_CONFIG:-$SCRIPT_DIR/nas.env}"
[[ -r "$CONFIG_FILE" ]] && source "$CONFIG_FILE"

VM_HOST="${VM_HOST:-141.147.182.42}"
VM_USER="${VM_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-/workspace/.ssh/easystock_nas_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-/workspace/.ssh/known_hosts}"
ORDERBOOK_ROOT="${ORDERBOOK_ROOT:-/data/backup/orderbook}"
REMOTE_ORDERBOOK_DIR="${REMOTE_ORDERBOOK_DIR:-/home/ubuntu/easystock-orderbook}"
REMOTE_PY="${REMOTE_PY:-/home/ubuntu/easystock/.venv/bin/python}"
REMOTE_REPO="${REMOTE_REPO:-/home/ubuntu/easystock}"

log() { printf '%s [orderbook] %s\n' "$(date -Iseconds)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

mountpoint -q /data || die '/data must be a persistent mount point'
[[ -r "$KNOWN_HOSTS" ]] || die "verified known_hosts is required: $KNOWN_HOSTS"
mkdir -p "$ORDERBOOK_ROOT/raw"
exec 9>"$ORDERBOOK_ROOT/.sync.lock"
flock -n 9 || die 'another orderbook sync is already running'
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20 -o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes)
REMOTE="$VM_USER@$VM_HOST"

mapfile -t DAYS < <(ssh "${SSH_OPTS[@]}" "$REMOTE" \
  "cd '$REMOTE_ORDERBOOK_DIR/raw' 2>/dev/null && for d in ????-??-??; do [ -f \"\$d/COMPLETE\" ] && echo \"\$d\"; done; true")
log "sealed days on VM: ${#DAYS[@]}"
failed=0
for day in "${DAYS[@]}"; do
  [[ "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { log "skip odd name $day"; continue; }
  dest="$ORDERBOOK_ROOT/raw/$day"
  mkdir -p "$dest"
  rsync -a -e "ssh ${SSH_OPTS[*]}" "$REMOTE:$REMOTE_ORDERBOOK_DIR/raw/$day/" "$dest/" || { log "rsync failed $day"; failed=1; continue; }
  if ! python3 - "$dest" <<'PY'
import hashlib, json, sys
from pathlib import Path
d = Path(sys.argv[1])
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()
m = d / 'MANIFEST.json'
assert (d / 'COMPLETE').read_text().strip() == sha(m), 'manifest hash'
for f in json.loads(m.read_text())['files']:
    assert sha(d / f['name']) == f['sha256'], f['name']
(d / '.verified').write_text(sha(m) + '\n')
PY
  then log "verify failed $day"; rm -f "$dest/.verified"; failed=1; continue; fi
  msha="$(cat "$dest/.verified")"
  out="$(ssh "${SSH_OPTS[@]}" "$REMOTE" "cd '$REMOTE_REPO' && '$REMOTE_PY' -m market_data.bidask_archive prune --root '$REMOTE_ORDERBOOK_DIR' --day '$day' --manifest-sha '$msha'" || true)"
  log "$day verified; vm prune: $out"
done
date -Iseconds > "$ORDERBOOK_ROOT/LAST_RUN"
[[ $failed -eq 0 ]] && date -Iseconds > "$ORDERBOOK_ROOT/LAST_SUCCESS"
exit $failed
