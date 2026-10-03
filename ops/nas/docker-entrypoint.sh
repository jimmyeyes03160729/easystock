#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf '[scheduler] ERROR: %s\n' "$*" >&2; exit 1; }

for required in /config/nas.env /workspace/.ssh/easystock_nas_ed25519 /workspace/.ssh/known_hosts; do
  [[ -f "$required" && -r "$required" ]] || die "Required file missing or unreadable: $required"
done

backup_root=/data/backup/vm
[[ -d "$backup_root" && -r "$backup_root" && -w "$backup_root" && -x "$backup_root" ]] \
  || die "Backup directory must be accessible and writable: $backup_root"
# Verify logs can be opened for append without truncating existing content.
for logfile in "$backup_root/sync.log" "$backup_root/healthcheck.log"; do
  : >> "$logfile" || die "Cannot append to log: $logfile"
done

[[ "${TZ:-Asia/Taipei}" == Asia/Taipei ]] || die 'TZ must be Asia/Taipei'
export TZ=Asia/Taipei NAS_CONFIG=/config/nas.env
# Debian cron schedules against system localtime, not just the job's TZ.
ln -snf /usr/share/zoneinfo/Asia/Taipei /etc/localtime
printf 'Asia/Taipei\n' > /etc/timezone
[[ "$(/bin/date +%z)" == +0800 ]] || die 'Expected timezone offset +0800'
printf '[scheduler] Timezone: %s; date: %s\n' "$TZ" "$(/bin/date --iso-8601=seconds)"
printf '[scheduler] Installed cron schedule:\n'
/bin/cat /etc/cron.d/easystock-backup

# Default command is foreground cron; an explicit command permits manual checks.
if (( $# == 0 )); then
  set -- /usr/sbin/cron -f
fi
exec "$@"
