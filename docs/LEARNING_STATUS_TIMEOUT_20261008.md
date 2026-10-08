# Learning Status timeout fix — 2026-10-08

Scope: CODE FIX + OFFLINE TESTS + PR only. No deployment, service restart,
unit/drop-in edit, Firebase publication or production data changes.

## Read-only runtime evidence

VM systemd definition: oneshot, `learning_status.py --publish`,
`TimeoutStartSec=50` / effective `TimeoutStartUSec=50s`.
At inspection, the last run started 10:14:02 and exited 10:14:52 Taipei;
Result timeout, ExecMainStatus 15, CPU time 24.320 seconds.

Systemd-only journal events since 2026-10-05: 2,751 completed runs and 491
start-operation timeouts. Completed wall durations: min 10.487 seconds,
median 17.595, p95 45.790, max 50.108 (journal timing includes scheduling
variance). Median reported CPU time: 17.418 seconds. Recent timeout events
include 2026-10-08 10:07:21, 10:09:16, 10:13:01 and 10:14:52 Taipei,
approximately 50 seconds after start.

Installed Firebase Admin 7.5.0 / requests 2.34.2 / urllib3 2.7.0:
SDK default HTTP timeout 120 seconds; SDK retry configuration
`Retry(total=10, connect=1, read=1, status=4)`. The old FirebaseStore does
not supply an `httpTimeout`; learning-status has no process operation deadline.
The confirmed defect is a network/deadline budget incompatible with systemd,
not an absence of an SDK timeout altogether.

Two-core host at 10:15:38: load averages 5.27 / 6.03 / 5.08; CPU PSI
some avg60 37.71%, I/O PSI some avg60 39.76% / full avg60 14.81%.
These are point-in-time resource pressure observations, not proof of the
cause of each historical timeout. Existing logs have no stage timings:
Firebase/DNS/token refresh, local reads, compute and competing jobs cannot
be individually attributed. No production probe/aggregation was run to fill
this evidence gap. Post-deployment stage attribution is RUNTIME UNVERIFIED.

Journal output was limited to systemd lifecycle/results, elapsed/CPU durations
and exception class names; no application signal/result payload was emitted.

## Boundaries and transport

Changes are restricted to root and mirrored `learning_status.py`, synthetic
tests and this evidence document. Shared FirebaseStore and all other services,
history/premarket/Guardian/research files are unchanged.

- Entire inspection worker: 40-second monotonic deadline, leaving ten seconds
  below the unchanged 50-second systemd deadline. Termination/kill joins are
  bounded to at most one additional second under ordinary scheduling.
- Firebase initialization/read/publish stage: at most eight seconds, capped
  by remaining overall time. The parent reaps only its own worker on expiry,
  so DNS stalls and response trickles cannot leave a delayed publisher running.
- Dedicated Firebase Admin app with public `httpTimeout=4`; a learning-only
  authorized session actually passes requests `timeout=(2, 4)` for connect/read.
  OAuth token requests use the same socket bounds. This app's SDK adapters use
  zero automatic retries; default/shared apps and FirebaseStore are untouched.
- At most two attempts per transient GET with 0.25-second bounded backoff;
  failures after stage/overall expiry cannot start another attempt. No automatic
  credential-refresh-on-401 replay. Non-transient errors fail immediately.
- One complete PUT, no application or transport write retry. Timeout is an
  unsuccessful/unknown publication outcome: the server may have accepted a
  complete PUT before the client lost its acknowledgement. We never claim that
  a timed-out write definitely left server state unchanged, or retry/rollback it.
- Private SDK client/session integration is tested against 7.5.0 (VM version)
  and 7.7.0 (local). An incompatible transport fails before publishing; an SDK
  upgrade requires rerunning these contract tests.

The socket timeout alone is not a total wall-clock deadline. References:
[Firebase Admin timeout option](https://firebase.google.com/docs/reference/admin/python/firebase_admin),
[Requests timeout semantics](https://requests.readthedocs.io/en/stable/user/advanced/#timeouts),
[urllib3 DNS/read limitations](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Timeout).

## Fail closed and performance

Read/auth/shape/local parse/compute/deadline failure returns nonzero and does
not call the publication PUT: the last valid status/time is retained and the
unchanged UI three-minute freshness gate marks it stale. No zeros, placeholder
state, half-built report, delete/reset, or renewed timestamp is published on
failure. Successful JSON null retains the old absent-node semantics; a read
exception is never converted to JSON null/empty data. Successful snapshot field
semantics and research date/sample selection are unchanged.

Diagnostic JSON includes fixed stage/status, exception *type*, duration,
file count or attempt only. Exception text, URLs, credentials, file names,
symbols, labels, returns and outcomes are not logged. Model error projection
also omits exception text. Reports/journal/labels scans, aggregate compute,
network operations, model status and total process duration are measured.

Code inspection confirms full historical JSON/JSONL traversal and O(total
input size) cost. Historical totals require those inputs; no scan was proven
unnecessary. No cache/truncation/date restriction or statistics optimization
was introduced without production stage evidence. Compute exceeding its
budget preserves the old snapshot instead of publishing partial statistics.

## Offline verification

- New T1–T9 coverage: 20 tests passed on both Admin SDK 7.7.0 and isolated 7.5.0.
  Includes actual SDK-to-requests adapter timeout/retry assertions for RTDB GET,
  PUT and OAuth POST; mocked connect/read/write failures, bounded retries,
  worker reaping (simulated stuck DNS and slow compute), no late publish, full
  snapshot/old-time preservation, timing redaction and root/runtime byte parity.
- Related root suites: 165 passed / 17 subtests, including these 20 tests,
  Research episodes, Paper limits/legacy, Market Risk, Rebound, Owner Live
  Console, Admin order safety and Guardian. Compile and diff check passed.
- Entire `package.json` test script passed, including 50 Node-runner cases,
  frontend freshness, Rebound, mobile navigation, Admin/Owner/Guardian tests.
  Direct Node execution used existing jsdom dependencies read-only because
  pnpm's automatic dependency materialization failed with Windows EPERM;
  that pnpm invocation itself is not claimed as passed.
- Combined root/VM attempt: 163 passed / 43 subtests, 14 failures and one
  teardown error in Windows VM wallet tests (open SQLite handles / subprocess
  encoding). Repeating the two VM suites with the *unmodified* base-main
  learning_status module produced the same 14 failures / one error, with
  30 passed / 26 subtests. Unrelated wallet files were not repaired or skipped
  to manufacture a full pass. Full Linux acceptance is not inferred from this.

All data/network cases are generated synthetic fixtures and temporary
directories. Pristine Holdout exposure = 0; real training/backtest/replay = 0;
production research data changed = 0. No retained-period data, SQLite payload,
outcome archive or private dataset partition was opened by this work.

## Owner deployment handoff

PR review/merge is required; no main push or auto-merge. Afterwards only the
Owner may authorize `bash deploy/update_vm_main.sh` and any runtime observation.
Do not raise TimeoutStartSec, restart/stop publishers, reset-failed, or invoke
the publisher manually just to obtain a green service result. Inspect sanitized
stage logs on naturally scheduled runs; verify exit status and that unavailable
states retain the old timestamp. Runtime resolution of the intermittent incident
remains unverified until that authorized deployment/observation occurs.
