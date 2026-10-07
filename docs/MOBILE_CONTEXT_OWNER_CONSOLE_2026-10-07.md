# Mobile / E.SUN context / Owner console — 2026-10-07

This release extends existing main, not a second provider, authentication or execution stack.

## Mobile

Five labels map to existing intraday, rebound, learning, Chrome extension and `/admin` entrances. Fixed only at <=768px; safe-area and 68px body padding; existing desktop navigation unchanged. No login bypass. DOM tests cover M1–M7.

## Read-only E.SUN

Existing seven verified index identifiers are unchanged. Official [`stock.snapshot.quotes({market: 'TSE' | 'OTC'})`](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/http-api/snapshot/quotes/) supplies snapshot rows. The EQUITY ticker scope may include ETFs; it is **not certified all ordinary stocks**. Advance/decline/unchanged, ratio (null for zero denominator), percentages and score use only same-day, <=90-second, non-future, valid rows. Returned/valid counts and coverage expose omissions; API failure clears old evidence.

Sector scores are day return minus TAIEX in percentage points. Ties sort by verified symbol. 1/5/15-minute returns require preceding exchange observations within 90 seconds of the requested horizon; missing history is null. Rotation is explicitly a price-only proxy, not capital flow. No historical backfill; canonical `context.json` and dated dataset append-only snapshots retain quote/receipt time. Fresh calendar-publisher OPEN decision, worker connection and same-day freshness are required. Python diagnostics rechecks calendar/expiry even if the worker stops. Market Risk / production ENTRY / EXIT remain unchanged.

## Owner / Live safety

Existing Google owner sessions gain a private owner binding; legacy sessions must re-login for live endpoints. Server-side 401 unauthenticated / 403 non-owner, CSRF and Origin remain mandatory for writes. Broker execution stays at the existing protected `order/place` endpoint.

Read adapter follows official [backend order refresh](https://sinotrade.github.io/tutor/order/UpdateStatus/), [share-unit positions](https://sinotrade.github.io/tutor/accounting/position/) and [realized PnL](https://sinotrade.github.io/tutor/accounting/profit_loss/) APIs. Broker identifiers are fingerprints, account is masked, credentials/CA paths/exceptions are excluded. PnL unavailable is null. Missing strategy/entry time is unknown, not invented. Account fingerprint is pinned locally; changes fail closed.

Manual SELL is initially limited to prior-day Cash Buy holdings minus pending SELLs; unsupported same-day daytrade/credit/ambiguous holdings cannot submit. Existing tick/quantity/notional validation, <=30s quote, broker re-auth, refreshed positions, session/account/order-bound 60s verification and typed SELL + masked-account confirmation are enforced. Reservations serialize across workers using the existing SQLite transaction/idempotency path; uncertain/submitted sell allowances are conservatively retained for reconciliation. Broker submission errors are **never automatically retried**, including NotReady. Final broker/guard checks precede the existing broker submit call. No real submission is used for verification.

`live_trade_*` is private and separate from Paper/Research. The local expected ledger is not silently overwritten from broker observations: any mismatch, unknown outcome or stale read means AUTO PAUSED / RECONCILIATION REQUIRED. Automatic ledger reconstruction and reconciliation repair are future work. KILL SWITCH blocks new AUTO authorization only, never flattens. OFF/SHADOW/PAPER/LIVE AUTO are control states; no auto execution engine or Research-to-Live wiring exists. Two environment guards are required even for the activation skeleton. Production defaults remain OFF; this change does not enable either guard.

## Verification

M1–M7, E1–E9 and A1–A16 have offline DOM / fake-broker / temporary-DB coverage. Model-governance test fixtures now isolate host environment variables; inference/model thresholds are unchanged. No LIVE VERIFIED claim is made.

Final code was exported from main plus the exact staged patch to an isolated Linux maintenance directory (not the production checkout). Broker/API keys and both ordering guards were blank in regression processes; broker tests use fake adapters and temporary databases.

- Linux root: **497 passed / 59 subtests**, 2026-10-07.
- Linux `vm_runtime/tests`: **79 passed / 36 subtests**; root/runtime parity checks passed.
- Linux `daytrade_learning` plus full root admin suite: **75 passed**. Research requirements pin scikit-learn 1.8.0, which requires Python >=3.11; this suite used an isolated Python 3.11 environment. Production Python 3.10 and its dependencies were not changed.
- Full mirrored `vm_runtime/easystock_admin/test_admin.py`: **30 passed** in the same isolated environment.
- Owner security / existing order safety / market-context diagnostics targeted suite: **30 passed / 11 subtests**, fake broker only.
- `pnpm test`: passed, including mobile DOM, Owner console DOM, asset-version and existing UI regressions.
- E.SUN provider Node suite: **10 passed**; requested Python compilation and staged diff checks passed.

Natural full-trading-day E.SUN breadth coverage / rolling windows and real live-trade verification remain pending.

## Canonical VM verification — 2026-10-07 21:15 Taipei

Feature commit: `494fc41043ae27e8b66c56bea133c08b34f20008` on main. All guarded jobs were checked read-only and allowed to finish naturally. Deployment used **only** `bash deploy/update_vm_main.sh`; the confirmed run returned **UPDATER_EXIT=0** and restored the previous intraday timer mode. The first SSH stream did not return its tail/exit status and was not counted as proof of success; the same canonical updater was rerun with a bounded SSH keepalive and explicit exit marker. Confirmed backup: `/home/ubuntu/easystock-maintenance/main-update-20261007-211305`. HEAD, origin/main and release-info source_commit all matched the feature commit. A documentation-only follow-up is synchronized with the same updater; its final SHA is reported in the handoff.

- Existing VM untracked vendor / bridge / local SDK files and local user archives were preserved; no reset/clean. Credentials, learning/market data and logs were retained. Production Python 3.10 was not upgraded. Updater's existing model-path/environment settings were already identical before deployment; no strategy/threshold or ordering guard was changed by this feature.
- E.SUN and existing Admin services active/running; provider-health service completed with exit 0. Premarket, intraday, research-cycle and provider-health timers enabled/active/waiting.
- Loopback Admin smoke: `/healthz`, `/admin`, new live-console JS **200**; both new Owner read APIs unauthenticated **401**. Non-owner **403** and CSRF/Origin/guard behavior are tested with mocks, not forged production sessions.
- E.SUN connected/authenticated/subscribed/parser OK; all **7** verified index symbols present and **5** sector rows. Real snapshot API status available for TSE and OTC; observed returned counts **1538 / 1418**. This confirms API availability, not ordinary-stock universe coverage or live freshness. After close, diagnostics correctly report `current=false`, breadth/sectors `UNKNOWN`, rotation `UNKNOWN`, basis `price_only`. No previous close masquerades as a current signal; rolling windows still require a natural trading day.
- Read-only Shioaji smoke: login connected/authenticated and account masked. **Account sync not verified**: backend order refresh raised `TokenError`, share-position read raised `ShioajiConnectionError`; the adapter returns `complete=false`, unavailable PnL and `broker_sync_unavailable`. Empty returned arrays are unknown, **not proof of no real holdings/orders**. No CA activation or broker submission was performed, and no credentials/permissions were changed. Real broker data/reconciliation readiness requires a valid authorized account read.
- Private live state **OFF**, all four `live_trade_*` tables **0 rows**, order_requests **0 rows**. Effective Admin process environment: ordering enabled false, confirmation absent. KILL control does not flatten; no production AUTO engine exists.
- Read-only Firebase/preflight: Paper **fills 30 / logs 7 / positions 0**, SQLite integrity **ok**; premarket date 2026-10-07, YELLOW / score 43, valid. Existing rows unchanged through canonical migration.

**Not an all-healthy / LIVE VERIFIED claim:** at 21:15:48, `systemctl --failed` showed **2 pre-existing failed units**: `easystock-market-update.service` (today's 15:30 daily update exited 1 after an upstream request timeout) and intermittent `easystock-learning-status.service` (`Result=timeout`, status 15; it also completed successfully between failures). Both were observed before this feature deployment. Failed markers were not cleared. Retrying daily publication would write Firebase/perform its existing retention behavior, and is not a read-only smoke check; no such retry or credential/production guard change was performed.
