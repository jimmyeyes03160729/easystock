# EasyStock Guardian

Built for the existing Oracle VM. Health checks run once per minute. Codex is
started only for a persistent incident, in a separate OS account and systemd
sandbox. This package never calls a broker order API or changes cash, positions,
strategy thresholds, or model settings.

## Installed layout

- `/opt/easystock-guardian`: root-owned code, tests, approved baseline and CLI metadata.
- `/var/lib/easystock-guardian`: private state, evidence, backups, notification outbox.
- `/var/lib/easystock-codex/jobs`: isolated source copies, agent output and proposed patches.
- `/etc/easystock-guardian/config.json`: enable flag, model, notification flag, daily limits.
- `easystock-guardian.timer`: approximately once per minute, including outside market hours.
- `easystock-guardian-worker.service`: bounded controller, only predefined recovery operations.
- `easystock-codex@.service`: unprivileged agent, no production credentials or direct Internet.
- `easystock-guardian-proxy.service`: loopback Responses API gateway; keeps the real key outside the agent.
- `easystock-guardian-calendar.timer`: refresh official TWSE holiday calendar at 08:10 Taipei.

## Health rules

Checks use Asia/Taipei dates and the official annual TWSE holiday table.
At 08:40, inspect yesterday's OPEN records and ledger consistency. From 08:58
until 13:00, require the service and a current snapshot (maximum 120 seconds old).
From 09:05 until 12:30, require radar updates within 180 seconds.
After 13:05, check for today's closed session and remaining simulated positions.
Weekends/holidays and outside the monitoring session are marked `outside_session`,
not as proof of intraday recovery. Add typhoon/emergency closure dates to
`extra_closed_dates` in the config. An unavailable calendar disables automatic
recovery. The annual schedule does not predict unscheduled closures.

An incident requires two successive failed checks. A resolved notification needs
three in-session healthy checks with today's data. The same incident is not
repeatedly restarted or sent to Codex. Default: maximum two agent incidents per day,
12 API requests per incident, 30 API requests / 1.5 MB request bodies per day,
4096 maximum output tokens per request, 450-second agent lifetime. These are
request/runtime limits, not a guaranteed monetary spending cap; API usage uses
the existing OpenAI project's billing. OpenAI project spend limits remain separate.

## Automatic actions and boundaries

1. **Quarantine proven unfilled ghost records.** Requires stopped service (or a
   restart loop which the controller stops), no genuine remote/local OPEN records,
   missing entry identity/shares/entry price, no matching SQLite fills and matching
   skipped-BUY records. Archive the entire old Firebase snapshot first, recheck
   SQLite, then compare-and-set the live node. Preserve all closed trades and dates.
2. **Restart the intraday service.** Only 08:55–12:29 on a known trading day, with
   no open positions/mismatch or syntax errors. Require the approved engine and
   position-manager hashes and existing `AI_PAPER_MODE=1`; source drift blocks
   unattended restart until reviewed. Never change the mode to make a restart pass.
3. **Restore the approved data adapter.** Only for a syntax-broken
   `firebase_store.py`, no open positions, and a stopped service. Verify baseline
   hash/tests, back up the deployed file and compare its hash before replacement.
   If post-start health verification fails, revert that code change only, provided
   no positions or external edits appeared. Never reverse ledger transactions.
4. **New code fixes.** Codex can modify/test the copied adapter. Unknown patches
   are retained under the incident directory for review, never automatically
   granted production deployment rights. Credentials, strategy, ledger, trading
   engine and guardian policy files are outside that write capability.

If conditions cannot be proven, preserve the evidence and notify. This is bounded
self-recovery, not a promise that arbitrary future bugs can be safely auto-fixed.

## Notifications and independent watchdog

The user authorized system notifications to the existing Telegram group configured
in `/home/ubuntu/easystock-telegram.env`. Notify on persistent failure, recovery
result, manual attention and verified resolution; healthy polls stay quiet. Failed
deliveries are retained and retried. Only operational summaries are sent.

Each check publishes a minimal public heartbeat under
`market_data/intraday_live/guardian_health`, without updating the market-data timestamp.
The GitHub Actions watchdog independently reads it every five minutes during Taiwan
weekday market hours and hourly otherwise. A missing/older-than-ten-minutes heartbeat
or degraded report fails the workflow. GitHub schedule execution can be delayed;
GitHub failure notifications depend on the repository owner's notification settings.
If the VM is entirely offline, its Telegram sender is also offline; the independent
GitHub alert is the fallback. No Telegram token is stored in GitHub.

## Operations

```bash
sudo /home/ubuntu/easystock/.venv/bin/python3 /opt/easystock-guardian/guardianctl.py status
sudo /home/ubuntu/easystock/.venv/bin/python3 /opt/easystock-guardian/guardianctl.py pause
sudo /home/ubuntu/easystock/.venv/bin/python3 /opt/easystock-guardian/guardianctl.py resume
sudo /home/ubuntu/easystock/.venv/bin/python3 /opt/easystock-guardian/guardianctl.py test
sudo journalctl -u easystock-guardian.service -u easystock-guardian-worker.service --since today
```

Pause stops new automatic recovery work, retaining monitoring and allowing an
already-running action to finish safely. Do not reset incident counters to force
repeated restarts. Inspect the saved diagnosis first.

The source package contains no credential values. Initial installation downloads
the official Codex CLI and matching code-mode host with release SHA-256 validation,
copies this package to `/tmp/easystock-guardian-install`, then runs `install.py`
as root. The installer sets up services but does not enable the monitor timer until
smoke/isolation checks pass. Production .env and ledger credentials stay on the VM.
Baseline updates after legitimate engine changes require deliberate operator review.
