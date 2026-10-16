# A paper allocation, volume contract and B clock repair

This change preserves Gemini's intent (unbounded ordinary-stock observation, ETF exclusion; paper BUY at 30–200 and >=3000 lots) while separating the paper BUY policy from accepted research events. The unrelated source branch and untracked research scripts are untouched. No model, strategy threshold, stop/target, or historical receipt is changed.

A BUY allocation is now capped atomically at daily_buy_limit / max_daily_entries (up to five slots), the remaining daily BUY allowance and visible executable depth. Existing fills are deduplicated before sizing. SELL does not replenish allowance; leftover allowance is not automatically redistributed. No guarantee of five entries is implied.

The paper-only adapter validates the executable ask against price limits and uses explicitly sourced V1 common-stock Tick.total_volume in LOTS, no older than three seconds, current session and not future. Missing, non-finite, odd-lot, simulated or unknown-unit values cannot authorize paper fills. Neither last-trade volume nor yesterday volume is substituted. High-price or low-volume signals can remain research-only. Existing eligibility, depth, fees, timing, rebound position limits and exits remain enforced. B BUY filters are not changed.

Source contract: https://sinotrade.github.io/zh/tutor/market_data/streaming/stocks/ documents total_volume as common-stock lots and odd-lot shares. No extra SDK login, subscription or snapshot polling is added. Publish paper_buy_policy in the live config for verification after next startup.

B lane advancement moves off the scanner/Firebase main loop to a half-second clock, still serialized by the existing LaneSuite lock and recorder order. It uses actual current timestamps, never catch-up timestamps. Genuine gaps are logged and exposed in lane-clock.json; the existing 30-second replay exclusion remains strict. Clock errors stop future B clocks and cause the main loop to fail closed; join occurs before journal finalization. SDK callbacks, I/O or lock contention may still delay clocks and must be measured in the next session. Today's 52.9-second cause was not verified because VM SSH is unavailable; no retrospective performance qualification is changed.

Deployment: source-only narrow manifest, current source hashes must match an allowed reviewed baseline, engine inactive, outside 09:00–13:30. Back up SQLite and sources; compare fills, positions, logs, settings and order requests before/after. No ledger writes or engine restart after close. VM acceptance requires a successful installer receipt, matching source hashes, and next-startup public policy/clock health. A GitHub merge alone is not deployment proof.

Validation uses synthetic wallet fills, policy boundaries and missing-data cases, research-only acceptance, thread independence and real-gap preservation. Full regression results are recorded in the PR. No backtest, model training, real order or historical result rewrite is performed.

Local regression: 1000 passed, 8 skipped, 57 subtests passed; three initial failures were Windows cp950 text decoding in existing tests. Rechecked with Python UTF-8 enabled; see PR for any Windows Bash limitation. Focused repair tests: 74 passed. No production data was used in tests.

UTF-8 recheck: closing cutoff and holiday pipeline tests passed; VM runtime safety suite passed (47 test items total, 26 subtests passed). The history timer shell test alone has two failing subcases because Bash is unavailable on this Windows host. These are not assertions against modified trading code; Linux CI remains the authoritative shell check.
