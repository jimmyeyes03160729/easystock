# Live daytrade evidence — 2026-10-03

Status: CODE VERIFIED / VM DEPLOYED / READY_FOR_LIVE_VALIDATION.
Saturday inspection is not a complete
trading-session validation. No synthetic event was written to production.

## Read-only production evidence

- Premarket timer enabled/active. Journal confirms successful 2026-10-01 and
  2026-10-02 publication; weekend service is skipped by its weekday condition.
- Firebase GET: scan_date 2026-10-02, generated_at 2026-10-02T08:35:15+08:00,
  base_risk_score 48. On Saturday this is UNKNOWN / premarket_missing_or_stale,
  not market RED. No same-day weekend brief was fabricated.
- Intraday timer enabled/active; next trading schedule 2026-10-05 08:55 Taipei.
  Last service result success / exit 0, presently inactive between sessions.
- Research-cycle timer enabled/active; last run 2026-10-02 16:10:01 success.
  Provider-health timer enabled/active; last inspected run success / exit 0.
- systemctl --failed: 0 units. SQLite integrity_check: ok.
- Before deployment: paper_trade_fills 30, paper_trade_logs 4,
  paper_trade_positions 0. No schema change is introduced by this patch.
- File flags LIVE_AUTO, ENABLE_LIVE_TRADING, ENABLE_REAL_ORDERS are not enabled.
  These file checks are not an independent audit of broker account state.

## Historical research, 2026-10-02

Durable production records: 4 accepted, 4 closed, 0 open; Paper 1 FILLED,
3 SKIPPED (legacy insufficient_cash). Wins 2, losses 2. Sum of per-trade net
returns -0.7885095111 percentage points, not a portfolio return. Average MFE
0.692492%, average MAE -0.274424%; exits trailing 2, fixed stop 1, breakeven 1.
Research-only records remain present after close. This historical evidence
does not validate the newly deployed execution guard.

Natural daily_buy_limit_exceeded case: not observed in this inspected date.
Full-day Market source-age/recovery evidence: unavailable in historical logs;
new private date-scoped JSONL starts after deployment. Do not close either
live-validation item using regression fixtures.

## Reproducible safe checks

From the canonical VM checkout:

```sh
.venv/bin/python deploy/audit_live_preflight.py --firebase
.venv/bin/python deploy/verify_live_daytrade.py --date YYYY-MM-DD
systemctl --failed --no-pager
```

Both Python tools only read production state. Output excludes credentials,
accounts and private endpoints. Review complete-session coverage, source
freshness, distinct-quote recovery, block reasons, model readiness and natural
Paper skips before marking LIVE VERIFIED. Do not inject quotes, lower limits,
force symbols or relax thresholds to obtain a live case.

## Regression and deployment

Windows targeted: 107 passed / 6 subtests. pnpm test: passed.
Linux VM-runtime suites: 168 passed / 35 subtests in isolated checkout.
Linux full root suites: 471 passed / 48 subtests. Compile and git diff --check
passed; root/vm_runtime execution-core byte equality passed. Deployment completed
as documented below; the guard section records the earlier deferred attempt.
Admin fixture isolates systemd state; Linux optional sklearn dependency is
installed only in the isolated test environment, not the production venv.
Windows full-suite collection requires Linux fcntl and is not counted as pass.

## Earlier deployment guard (resolved)

Code commit 096300a49803e79db2558380041836b81ab639d5 pushed to origin/main.
Canonical updater exited 1 before changing the checkout because
easystock-history-train.service was running (started 22:10:14 Taipei).
The updater restored the previously enabled intraday timer. No job was killed.
Final read-only check instead found checkout 096300a49803e79db2558380041836b81ab639d5:
reflog records a separate pull --ff-only at 23:02:39 Taipei. The guarded updater
log still confirms it stopped before update. release-info remains main-e0ce9e7dfc2f
(source e0ce9e7dfc2f55af53f58ccb03fe29cfe9d284fb), inconsistent with HEAD.
At that inspection an advanced checkout was NOT a verified release. Completion
was still pending, and the compliance roadmap item remained unchecked.

A same-chat five-minute follow-up is configured to wait silently while guard
jobs remain active, then run the canonical updater and record its exit result,
release identity, timer state and unchanged ledger integrity. It must never
fabricate a live case or stop production work. Desktop follow-up requires the
computer and Codex app to remain running; completion is not guaranteed while
they are offline. The follow-up must stop after successful final verification.

## Successful canonical deployment — 2026-10-03 Taipei

At 23:11 all five guard services were inactive, including history training;
no job was interrupted. Latest main added 88f622d (standalone research-governance
validator/docs/tests, no trading-runtime changes). Inspection and the 24 new
governance tests passed; governance plus compliance Windows tests: 39 passed.

`bash deploy/update_vm_main.sh` completed with exit 0. Backup:
`/home/ubuntu/easystock-maintenance/main-update-20261003-231312`.
Ledger migration verification reported original rows unchanged: fills 30,
logs 4, positions 0, events 457; integrity before/after ok and semantics unchanged.
Existing admin/research SQLite backups were preserved by the updater.

Post-deploy HEAD and origin/main both 88f622d5c096f8f9185f5a4e0d2d5c53800d7511;
release_id main-88f622d5c096, source_commit matched HEAD. Failed units 0.
Premarket/intraday/research-cycle/provider-health timers all enabled/active.
Premarket weekend exec-condition and stale 10/2 brief are expected; no fake
10/3 publication was produced. Read-only Firebase GET remains scan_date 10/2,
generated_at 08:35:15+08:00, score 48. Account integrity ok, rows still 30/4/0.
Checked file flags including LIVE_ORDERING_ENABLED are false; the admin's
two-factor file switch is not enabled. This is not an independent broker audit.

Production checkout targeted regression plus the new governance suite:
131 passed / 6 subtests. Root and mirrored runtime compile passed.
Only evidence/docs are committed next; the same canonical updater will sync
that documentation commit, followed by final identity/timer/ledger verification.
No LIVE VERIFIED claim: full-day Market evidence and a naturally occurring
over-limit Paper case remain open. No thresholds, orders or live switches changed.
