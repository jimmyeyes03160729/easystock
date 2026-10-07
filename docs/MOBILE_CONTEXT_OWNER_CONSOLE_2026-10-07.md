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

Canonical deployment and runtime evidence will be appended only after the updater succeeds. Natural full-trading-day E.SUN breadth coverage / rolling windows and real live-trade verification remain pending.
