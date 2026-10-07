# AI Architecture Guardian v1 acceptance evidence — 2026-10-07 Taipei

## Scope and release identity

Implemented observation-only SCAN / ANALYZE / REPORT / NOTIFY. Guardian cannot
submit orders, alter switches, edit production code, deploy, select stocks,
change strategy/model/risk thresholds, or promote a model. Blocking findings
are advisory only; enforcement is false.

Implementation commit: `6ffa5bc00d0fa6a59d0591ae4358932dc8045883`.
The existing main-only checkout was fast-forwarded without a new branch.
Concurrent incoming main changes through `db47c0b4f5ff67453b53e877f98bbe538941e147`
were inspected and preserved, including the authenticated manual-order UI.
That UI was not exercised against a production broker.

## Deterministic scan

Policy validation: VALID, 24 rules, 52 required byte-equivalent mirror pairs,
5 documented allowed differences and 12 runtime-only files.
Completed working-tree scan on the implementation commit: REVIEW, Critical 0,
High 6, Medium 0, Low 0. No finding is hidden in the empty accepted baseline.
The findings are review evidence, not proof that every execution path is safe:

| Rule | Relative evidence | Interpretation |
| --- | --- | --- |
| ARCH-002 | history/collector_core.py | Existing required root/runtime mirror differs. |
| ARCH-002 | history/daily_history.py | Existing required root/runtime mirror differs. |
| ARCH-002 | premarket_ai.py | Existing required root/runtime mirror differs. |
| RESEARCH-004 | daytrade_learning/research.py:66 | Existing approved-model write requires gate/bootstrap review. |
| RESEARCH-004 | daytrade_learning/champion.py:145 | Existing approved-model write requires gate/bootstrap review. |
| SECURITY-004 | index.html:5070 | Intended public Owner entry link requires exposure review; endpoint redacted. |

No automatic mirror copy, promotion change or public-link removal was performed.
Static analysis has documented limits for dynamic control flow, indirect SQL,
cross-function taint and intent-dependent promotion/reconciliation behavior.

## Tests and configuration validation

- G1–G20 and additional precision/security regressions: 32 Guardian Python tests.
- Integrated Guardian plus existing Admin order safety: 39 passed / 11 subtests.
- `pnpm test` after integration: all groups passed, including 50 Node-runner
  cases, the 9 incoming manual-order UI cases, Guardian auth/logout/private-data
  clearing, mobile navigation, provider context and live-console tests.
- Isolated Linux full-root regression on inspected `d176f7a` plus Guardian:
  556 passed / 59 subtests. Research/Admin/history: 99 passed.
  VM runtime: 168 passed / 36 subtests.
- Final integrated Linux root rerun on `6ffa5bc`: 559 passed / 59 subtests,
  537.90 seconds; the batch completed with explicit `QA_FINAL_EXIT_0`.
- Windows root run: 555 passed, 1 skipped, 57 passed subtests and 2 failed
  subtests caused by missing bash. This is not reported as a full Windows pass;
  the isolated Linux run exercises those existing shell regressions.
- Python compile, shell syntax, `git diff --check`, and the three workflows'
  official actionlint v1.7.12 syntax/context checks passed.
- Immutable diff review on `db47c0b..6ffa5bc` completed with no findings in
  the changed scope and review_required true. This does not clear the six
  existing full-scan High findings. Bounded weekly bundle generation passed
  and reported AI NOT_CONFIGURED / enforcement false.

Tests use synthetic temporary repositories/accounts and an isolated Linux
checkout/venv, without production credentials or broker submission.
GitHub daily/weekly, CodeQL, Dependabot and pinned official Trivy configuration
are implemented. Hosted first-run security scan outcomes remain unverified;
local configuration validation is not a successful hosted CodeQL/Trivy scan.

## Optional AI and notifications

AI provider execution: NOT_CONFIGURED. Provider-neutral interface, bounded
review bundle and fixed prompt are available without a paid API call. Invalid
JSON/schema and command-like output are rejected, never executed. No raw full
repository/diff, credentials or private endpoint is exported in the bundle.
Notification tests reuse existing LINE/Telegram senders with synthetic callbacks;
no production test message was sent. Production notification remains Owner
opt-in and generic High/Critical counts with private Admin guidance.

## VM pre-deployment evidence — PENDING_RUNNING_GUARD

Read-only SSH inspection found production HEAD
`c62512f4a4880b3aa25dea256f92e2669279cf1e`. History training is still active;
the other four canonical updater guard services are inactive. The updater was
not invoked, timers were not paused, and no job was stopped or killed.
Guardian scanner/Admin runtime are NOT YET DEPLOYED, not NOT_REQUIRED.

Read-only `audit_live_preflight.py --firebase` completed on 2026-10-07:
SQLite integrity ok; Paper fills 30 / logs 7 / positions 0. Premarket Firebase
GET returned that day's 08:35 brief, YELLOW/valid. Premarket, intraday,
research-cycle and provider-health timers are enabled and active/waiting.
Separate read-only SQL confirmed console mode OFF, kill switch false and
live order rows 0. File-level live flags and the two-factor ordering guard are
false; this is not independent proof of broker-side positions or service env.

Two pre-existing failed units were observed: market-update and learning-status.
Their status was not cleared and their publishing jobs were not restarted.
They must remain visible in eventual deployment verification; do not claim
failed units zero without actual evidence or make unrelated publisher repairs.
Local untracked archives and VM-local untracked modules/data are preserved.

The user authorized silent five-minute continuation in this same chat. It is
an operator continuation, not a Guardian auto-deploy capability. Once guard
jobs naturally finish, inspect latest main and VM-local state, deploy only via
`bash deploy/update_vm_main.sh`, verify explicit exit 0, release identity,
private report permissions/status, Owner API authorization, timers and
read-only ledger/Firebase state. Newly arrived code must be inspected/tested,
not overwritten. Record sanitized deployment evidence only after it occurs;
sync that evidence commit via the same canonical updater and verify final SHA.
Stop the continuation on completion; report a genuine failure or user-action
requirement rather than silently clearing it.

## Safety and open acceptance gates

Real orders submitted by this work: 0. LIVE AUTO observed OFF. No change to
LIVE ordering guards, KILL state, account, ENTRY/EXIT, Market Risk, threshold,
Paper daily limit, labels, Champion gate or Pristine Holdout contents.
No secret values were committed or included in reports/evidence.
Full-session Market Risk and natural Paper over-limit live cases remain pending;
this work does not claim LIVE VERIFIED or production-ready research models.
