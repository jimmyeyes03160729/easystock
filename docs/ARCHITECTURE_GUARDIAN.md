# AI Architecture Guardian v1

Guardian is an observation-only architecture / trading-safety / research-governance
reviewer. Its capabilities are **SCAN, ANALYZE, REPORT, NOTIFY**. It is not a trading
AI or the existing operational recovery agent under `ops/guardian/`.

It cannot place/cancel orders, pick stocks, change ENTRY/EXIT, Market Risk, model
thresholds, approved models, KILL, accounts, LIVE AUTO, credentials, production
source or deployment. `blocks_live_auto` is an Owner advisory, **not enforcement**.
SAFE is not LIVE VERIFIED or permission to trade.

## Structure and policy

`guardian/policy.yaml` is machine-readable YAML 1.2 in JSON syntax; runtime needs
only the Python standard library. `validate-policy` checks rules, regular
expressions and the non-overlapping runtime manifest. Layer definitions cover UI,
Admin, Market Data, Strategy, Research, Paper and Live Broker.

| Rules | Structural checks |
| --- | --- |
| TRADING-001…007 | Research execution dependencies/calls; Paper/Live SQL boundary; LIVE dual guard and submission guard; KILL versus liquidation; client-order reservation; broker truth overwrite; silent enable defaults |
| RESEARCH-001…005 | Local holdout-to-optimization taint; future feature operations versus legitimate labels; visible profile comparison; approved write versus Champion gate; production decision writes |
| ARCH-001…003 | Same responsibility and normalized AST body, paired evidence; explicit mirror classification; eager module-import cycles |
| SECURITY-001…004 | Credential shapes and literal secret assignments; sensitive tracked filenames; public sensitive fields/dependencies; public operational endpoint references |
| DEPLOY-001…003 | Canonical updater preservation markers; bounded cleanup versus destructive ambiguity; protected-data destinations |
| DIFF-001 / SCAN-001 | Changed decision/safety boundary requires review; incomplete scan is UNKNOWN |

Python is parsed, never imported or evaluated. Source reads are bounded Git
tracked files, including working-tree changes; diff uses immutable historical
trees without checkout. Untracked credentials, archives, DBs and market/holdout
outcome datasets are not consumed. Sensitive tracked binaries are classified by
filename without loading contents. No source snippets or secret values enter
findings; evidence contains relative paths, lines and controlled descriptions.

Secret shape scanning also runs on test files. Explicit fake/example placeholders
are allowed; the canonical synthetic identity fixture is exempt **only in tests**.
Real token/PEM/JWT shapes remain findings even in tests. Public identity projection
is independent of literal-secret detection. Owner-only certificate-configured
diagnostics are not public exposure. Public operational endpoint references are
HIGH for intent review, not proof that an intended Owner link is a credential leak.

Paper import aliases and temporary Paper verification scripts are not broker
execution. Docker package-cache cleanup is image-scoped. The existing NAS snapshot
retention is recognized only with its resolved-path/direct-child rejection guard.
Ambiguous cleanup is HIGH, not blindly CRITICAL.

## Runtime mirror manifest and first-scan review

`guardian/runtime_mirror_manifest.json` explicitly defines 52 required byte-identical
pairs, five allowed differences with reasons, and twelve runtime-only paths. The
calendar wrapper, runtime-specific requirements and retained subset tests are not
blanket drift failures. Byte-identical pairs are scanned once.

Existing required differences in `history/collector_core.py`,
`history/daily_history.py` and `premarket_ai.py` remain HIGH review items. This
implementation does not silently synchronize them. Existing Paper bootstrap
approved writes in `daytrade_learning/research.py` and `champion.py` also require
policy review; a static finding does not assert that they promoted a live model.
The intended public Owner entrance is separately flagged without reproducing its
endpoint. No HIGH/CRITICAL findings are baselined away.

## Reports, history and CLI

Reports have schema version 1, generated time, commit, status, severity counts,
findings, deterministic fingerprints, first/last seen, resolved history, changed
critical files and `review_required`. Fingerprints exclude line numbers and commit
dates. UNKNOWN cannot resolve previous findings. Medium/Low baseline acceptance
requires a reason and remains visible; it cannot manufacture SAFE. HIGH/CRITICAL
acceptance is rejected. History is retained rather than pruned; bounded-output
failure is UNKNOWN and requires operator review, never silent history deletion.

```sh
python -m guardian.cli validate-policy
python -m guardian.cli scan --output-dir /private/guardian-reports
python -m guardian.cli scan --json --output-dir /private/guardian-reports
python -m guardian.cli diff --base <commit> --head <commit> --output-dir /private/guardian-diff
python -m guardian.cli report --json --output-dir /private/guardian-reports
python -m guardian.cli bundle --output-dir /private/guardian-reports
```

No CRITICAL and no findings = SAFE; any non-critical findings = REVIEW; any
CRITICAL = DANGER; failed/incomplete scanner = UNKNOWN. No numeric safety score.
Normal completed scan exits 0 even with findings. `--strict` exits 1 for findings;
UNKNOWN/operation failure exits 2. Exit 0 is not trading authorization.

Outputs are separate private state, never inside the repository or protected
production-data directories. Directory/file modes on Linux are 0700/0600, with
exclusive temporary files and atomic replacements; symlink destinations are
rejected. Defaults: local user state directory, or `GUARDIAN_REPORT_DIR`.

## Owner Admin and notifications

The new **AI 系統健檢** section is inside the authenticated workspace, not the
public homepage. GET `/admin/api/guardian` uses the existing Google Owner session:
401 unauthenticated, 403 non-Owner; POST is not supported. It projects only a
redacted bounded report, never starts scans or modifies controls. It displays
status/time/commit, Critical/High/Medium/Low, findings/evidence/impact/recommendation,
resolved items and advisory blocking. Missing, stale (>26 hours), future-dated or
release-mismatched reports show UNKNOWN. Browser failures clear stale cards;
rendering uses text content, not HTML injection.

`scan --notify` reuses existing LINE/Telegram HTTP clients and existing Owner
summary opt-in switches, reading SQLite with `mode=ro`. Only HIGH/CRITICAL can
notify, using generic counts and a private-Admin direction, never credentials,
accounts, endpoints, paths or stack traces. Receipts live in Guardian's private
state, not the trading DB. Reservation-before-delivery prevents uncertain sends
from triggering repeated notifications. Private-user target validation is reused;
group targets are not introduced. Medium/Low stay in Admin only.

## Production scanner lifecycle

Operator deployment still runs **only** `deploy/update_vm_main.sh`. The updater
validates policy and installs the dedicated architecture-Guardian service/timer.
Guardian never invokes the updater or installer. The old operational Guardian is
unchanged. The new service runs as ubuntu with `ProtectSystem=strict`, read-only
home, no privilege escalation, and writable scope limited to its own report
directory. It runs a scan at deployment and daily at 06:20 Asia/Taipei. Existing
deliberately disabled timer state is preserved. No broker/AI credential environment
file is loaded by this service.

Production report state: `/home/ubuntu/easystock-architecture-guardian`; Admin's
default matches the service. Operator inspection may read these artifacts and
service status; no reset/clean/kill or production-DB "repair" is part of Guardian.

## CI and bounded weekly review

`guardian-daily.yml`: daily/manual main-only existing root/research/rebound/Admin/
runtime/frontend regressions, compile, deterministic secret/safety scan, official
Trivy filesystem vulnerability and Docker configuration checks. Findings do not
prevent report upload; failing tests/scanners still fail CI. Raw Trivy output stays
in the runner temporary directory. Artifacts include only sanitized ID/severity
metadata, test outcomes and Guardian JSON/Markdown. Trusted scheduled-main cache
preserves sanitized report history best-effort across runs; cache expiry/eviction
may reset CI continuity. VM history is persistent and independent.

`guardian-weekly.yml`: bounded last-seven-day commit hashes/dates and changed-path
summary (at most 40 commits/200 paths), redacted ROADMAP/architecture/Guardian docs,
policy rule IDs, findings, critical changes, mirror drift, and sanitized cached
test/security outcomes. Missing outcomes are NOT_PROVIDED, never assumed passing.
No raw source diff, author identity, full repository export or external AI call.

Both workflows have `contents: read`, no deployment credentials, SSH, code writes,
autofix or push. CodeQL scans only Python and JavaScript/TypeScript and adds
`security-events: write` only to its publication job. Dependabot uses actual npm,
GitHub Actions and requirements manifests. No deployment/action write permission.

Trivy is pinned to the official immutable action
`57a97c7e7821a5776cebc9bb87c984fa69cba8f1` (v0.35.0) and unaffected tool v0.69.3.
Do not replace this with a floating historical tag: see the
[official supply-chain incident advisory](https://github.com/aquasecurity/trivy/discussions/10425).
Other actions use official publishers and major pins. Workflow creation and local
validation do not claim a completed hosted CodeQL/Trivy run.

## Optional AI review and limits

Without both `GUARDIAN_AI_PROVIDER` and `GUARDIAN_AI_API_KEY`, AI review is
NOT_CONFIGURED. v1 provides a provider-neutral interface, bounded bundle and fixed
ten-topic review prompt; no paid/provider SDK integration is forced. Configured
without an adapter is PROVIDER_UNAVAILABLE. Responses must be bounded schema-valid
JSON findings; commands, invalid JSON/schema and arbitrary execution are rejected.
AI findings are separate non-enforcing review, never trading or patch instructions.

Static analysis is intentionally conservative: local alias/taint and visible guard
patterns do not prove every control-flow path, dynamic import, generated SQL,
cross-function leakage, reconciliation or promotion semantics. False negatives and
intent-dependent HIGH review items remain possible. Missing evidence is not LIVE
verification. Future enforcement and any provider integration require a separate
explicitly approved design; no automatic code/model/state mutation is present.

## Acceptance evidence

Deployment/test evidence is recorded separately in
`ARCHITECTURE_GUARDIAN_VALIDATION_2026-10-07.md` after verification. Full-session
Market Risk and natural Paper excess-limit acceptance remain pending in the
existing live-validation documents; this project does not close those gates.
