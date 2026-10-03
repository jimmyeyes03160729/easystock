#!/usr/bin/env bash
# Read-only operational checks for the NAS backup job.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${NAS_CONFIG:-$SCRIPT_DIR/nas.env}"
[[ -r "$CONFIG_FILE" ]] && source "$CONFIG_FILE"
VM_HOST="${VM_HOST:-141.147.182.42}"; VM_USER="${VM_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-/workspace/.ssh/easystock_nas_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-/workspace/.ssh/known_hosts}"
BACKUP_ROOT="${BACKUP_ROOT:-/data/backup/vm}"
MAX_LAST_SUCCESS_AGE_HOURS="${MAX_LAST_SUCCESS_AGE_HOURS:-30}"
status=0
ok() { printf 'OK      %s\n' "$*"; }
warn() { printf 'WARNING %s\n' "$*"; (( status < 1 )) && status=1; return 0; }
bad() { printf 'FAIL    %s\n' "$*"; status=2; }

printf 'EasyStock NAS backup healthcheck — %s\n' "$(date -Iseconds)"
for cmd in ssh rsync python3; do command -v "$cmd" >/dev/null && ok "$cmd available" || bad "$cmd missing"; done
[[ -r "$SSH_KEY" ]] && ok "SSH key readable" || bad "SSH key not readable: $SSH_KEY"
if command -v mountpoint >/dev/null && mountpoint -q /data; then
  ok '/data is a mount point'
elif [[ -d "$BACKUP_ROOT" ]] && command -v mountpoint >/dev/null && mountpoint -q "$BACKUP_ROOT"; then
  ok "$BACKUP_ROOT is a mount point (container bind mount)"
else
  bad '/data or backup root is not a mount point'
fi
[[ -d /workspace/easystock || -d /opt/easystock/ops/nas ]] && ok 'EasyStock environment present' || bad 'EasyStock workspace missing'
capacity_path=/data
[[ -d "$BACKUP_ROOT" ]] && capacity_path="$BACKUP_ROOT"
if [[ -d "$capacity_path" ]]; then
  df -h "$capacity_path" | tail -n 1
  use=$(df -P "$capacity_path" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
  [[ ${use:-100} -lt 90 ]] && ok "$capacity_path capacity ${use}% used" || warn "$capacity_path capacity ${use:-unknown}% used (threshold: 90%)"
fi
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10)
SSH_OPTS+=(-o UserKnownHostsFile="$KNOWN_HOSTS" -o StrictHostKeyChecking=yes)
[[ -r "$KNOWN_HOSTS" ]] && ok 'verified known_hosts readable' || bad "known_hosts missing: $KNOWN_HOSTS"
if [[ -r "$SSH_KEY" ]] && ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_HOST" 'true' >/dev/null 2>&1; then ok "SSH reachable: $VM_USER@$VM_HOST"; else bad "SSH unreachable: $VM_USER@$VM_HOST"; fi
if [[ -f "$BACKUP_ROOT/LAST_SUCCESS" ]]; then
  last=$(cat "$BACKUP_ROOT/LAST_SUCCESS")
  if age=$(python3 - "$last" <<'PY'
import datetime, sys
stamp = datetime.datetime.fromisoformat(sys.argv[1])
if stamp.tzinfo is None:
    raise SystemExit('LAST_SUCCESS must include timezone')
print(int((datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds()))
PY
  ); then
    if (( age < 0 )); then bad "LAST_SUCCESS is in the future: $last";
    elif (( age <= MAX_LAST_SUCCESS_AGE_HOURS * 3600 )); then ok "LAST_SUCCESS: $last";
    else warn "LAST_SUCCESS is ${age}s old (limit: ${MAX_LAST_SUCCESS_AGE_HOURS}h): $last"; fi
  else
    bad "LAST_SUCCESS is invalid: $last"
  fi
else
  bad "LAST_SUCCESS is missing: $BACKUP_ROOT/LAST_SUCCESS"
fi
exit "$status"
