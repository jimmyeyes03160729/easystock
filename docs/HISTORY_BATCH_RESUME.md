# Resuming capped history batches

Previously the collector exited successfully at `history_max_pairs`, but its
timer only triggered at 14:00 Taipei or after boot. A completed batch could
therefore remain idle for the rest of the collection window.

The download timer now triggers every 15 minutes. `daily_history.py` still
checks the configured window and weekend policy before accessing archives or
logging in. Every run retains the pair cap, quota and disk reserves, manual
stop flag, retry backoff and exclusive download/training locks. Existing raw
archives are skipped, so another batch resumes without resetting progress.
Systemd does not start another instance of an already active service.

The admin health summary now uses the actual service and timer state. A saved
`pair_limit` checkpoint is displayed as waiting when the service is inactive,
with the next timer time if available. Disabled timers and failed services are
reported explicitly. Missing VM status cannot claim automatic continuation.

On an existing VM, use the canonical update:

```bash
cd /home/ubuntu/easystock
bash deploy/update_vm_main.sh
```

The updater invokes `deploy/install_history_schedule.sh`, which backs up the
installed timer, reloads systemd, and restarts only a previously active timer.
It does not restart or stop a running download/training service, or enable a
paused schedule. Wait for active jobs to finish when the canonical updater's
guard blocks an update. Pulling Git alone does not update `/etc/systemd/system`.
