# B-lane metadata adapter fix — 2026-10-12

## Verified incident

VM `17e45e4364328fdaa358d9cece064a99beeee75e` ran the intraday service, but B1's 09:00–09:10 PAPER session had zero entries, positions and closed trades. Read-only SQLite and the published Firebase B1 snapshot agreed: 3,939 evaluation rejections for insufficient/stale book/tape and 246 for invalid price/reference. These are repeated evaluations, not distinct securities.

The captured time window contained 40 nonempty radar updates, 4,179 candidate-row observations across 177 symbols, all missing a positive reference and sector. Those observations are not the same grain as 4,185 rejection evaluations. Quotes were present; this was not a complete feed outage. The recording was still active, so these facts are scoped incident evidence, not a sealed full-day backtest.

The installed SDK 1.7.4 exposes a contracts-v2 namespace. Its `contracts.get(code)` returns a `BaseContract` with identity fields only. `contracts.info(base)` supplies an info record whose optional stock fields are exposed through `dict()`. Direct attribute reads of `reference`, `category` and `day_trade` on the base therefore miss the needed inputs.

## Change

- Keep the original base contract for subscriptions and broker interfaces. Only the B radar metadata projection reads the corresponding info record.
- Normalize v2 info dictionaries/records and legacy Stock attributes through a read-only adapter. Require both contract and info identities to match the requested stock.
- Use SDK `reference` and canonical `category` for the registered B-lane inputs. `reference` is the existing contract-reference source, not a newly inferred previous completed-bar close. Lane A's separate historical-close lookup is unchanged and is no longer silently borrowed by B when metadata is missing.
- Only explicit `day_trade=Yes` allows a B short; `OnlyBuy`, `No`, missing and malformed flags do not.
- Cache complete metadata for 60 seconds, retry unavailable/partial data after 15 seconds, clear on day change and bound the cache to 512 symbols. Errors never reuse expired good data or invent scanner-price/category/eligibility fallbacks.
- Lookup runs in radar processing, not quote callbacks. Existing 3-second quote validity, five-book/tape confirmation, B1 peer/pullback rules, lane times, price/depth sizing, limits, stop/target, fees, replay and execution logic are unchanged.
- Recorded candidate rows include metadata source/status and explicit eligibility. A rate-limited aggregate `[B_LANES_METADATA]` log reports actual reference/sector/known-eligibility counts, without credentials or raw SDK payloads.
- Root and VM `intraday_live.py` remain byte-identical. `market_data` is the existing shared root package; no new mirror exemption is added.

## Tests and safety

- Targeted metadata, B1/B2/B3, replay, diagnostic, risk, cost and Guardian tests: **124 passed / 6 subtests**.
- `pnpm test`: all groups passed, including **72 Node cases**.
- Full Windows root regression with UTF-8: **842 passed / 57 subtests / 4 skipped** before the last eight metadata cases were added; those eight are included in the targeted run above. Two subtests of the existing Linux timer-installation test fail because Windows has no `bash`. No unrelated tests or production behavior were changed to hide this platform limitation. Linux CI runs the complete suite, including the final additions, before merge.
- SDK smoke test on the VM: real SDK 1.7.4 BaseContract, legacy Stock and DayTrade with **synthetic** info, no API client, login, credentials or orders. This confirms type adaptation, not live metadata recovery or future trade profitability.
- Syntax and `git diff --check` passed.

No deployed checkout, service, timer, switch, strategy threshold, live account, ledger, recording, research archive or credential was changed. Test trades use only temporary synthetic databases. Today's missing metadata is not retroactively filled from future SDK data and no production trades are fabricated. Deployment and next-session observation remain separate acceptance; this document does not claim LIVE VERIFIED or guaranteed fills.
