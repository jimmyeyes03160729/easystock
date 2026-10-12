# Lane A Paper eligibility adapter — 2026-10-12

## Verified issue and scope

The deployed `17e45e4` method `paper_execution_evidence()` read `day_trade` and `category` directly from the SDK contract. SDK 1.7.4 contracts-v2 returns a BaseContract without those optional fields; the corresponding info record supplies them. An isolated execution of the deployed method with a real SDK BaseContract and synthetic valid snapshot reproduced `eligibility=None` and `daytrade_eligibility_unknown`, without creating an API client, logging in or ordering.

This establishes a Paper qualification bug, not the sole cause of today's absence of trades. At the read-only observation around 09:47, today's research ledger and published A positions/closed trades were empty, and strategy logs showed upstream model/strategy/user-limit rejections. Lane A's historical previous-close lookup is separate from B's contract reference and is not changed here.

## Fix and unchanged safety

- Reuse the tested SDK metadata adapter from PR #110: `contracts.info(base)`/`dict()` for v2, legacy Stock fields otherwise. The original base is still used for snapshots and subscriptions.
- Use a fresh adapter instance for each Paper attempt; never borrow B's metadata cache or retain a previous eligible result after a new metadata failure/change.
- Preserve A's long-stock policy: ordinary stock category plus explicit `Yes` or `OnlyBuy` is eligible; `No` is ineligible. Missing category, ETF/ETN (`00`, `ETF`, `ETN`), unknown/malformed flags, wrong identity and lookup failure remain unknown and cannot buy.
- A does not require B's SDK reference for eligibility. `fresh_entry_quote()` still obtains the actual prior completed close from historical Kbars. No A model, threshold, user limit or strategy veto is bypassed.
- Metadata eligibility and snapshot availability remain separate. Snapshot failure keeps known eligibility but blocks a BUY and leaves a SELL pending. Stale/insufficient quotes never fall back to the signal price. Existing directional depth, session/cutoff, costs, tax, wallet limits, research-vs-Paper separation and exact-once behavior remain unchanged.
- Root and VM runtime sources remain byte-identical. Existing legacy compliance assertions are retained, with fixture identities and adapter dependencies made explicit.

## Verification

- Targeted A/B metadata, compliance, replay, diagnostics, risk, costs, Guardian and daily-limit regression: **178 passed / 6 subtests**.
- `pnpm test`: all groups passed, including **72 Node cases**.
- Runtime syntax and `git diff --check` passed.
- Complete Linux regression and CodeQL are required before the authorized automatic merge; local Windows has the previously documented missing-bash limitation. No unrelated platform tests are edited or skipped in CI.

All added executions are synthetic, with no production API login/order or ledger mutation. This request changes Git code only: no VM deployment, service restart, trading switch change, historical data repair or fabricated production fill. Production metadata recovery and next-session behavior require separate deployment/runtime acceptance; this is not LIVE VERIFIED or a promise of fills.
