# Paper execution and live validation review — 2026-10-03

Status: CODE VERIFIED; VM DEPLOYED on 2026-10-03; READY_FOR_LIVE_VALIDATION.
Deployment evidence is in LIVE_DAYTRADE_VALIDATION_2026-10-03.md.
The requested `DAYTRADE_COMPLIANCE_REVIEW_2026-09-30.md` was absent from main
and its Git history. This review records newly checked official sources.

## Official sources checked 2026-10-03

- [TWSE day trading](https://www.twse.com.tw/zh/products/system/day-trading.html): ordinary trading 09:00–13:30; same-account, same-day, matched quantities; designated securities only.
- [TPEx eligibility](https://www.tpex.org.tw/zh-tw/mainboard/trading/day-trading/rules.html): designated instruments; altered-trading/disposition exclusions.
- [TPEx daily securities](https://www.tpex.org.tw/zh-tw/mainboard/trading/day-trading/securities.html): intraday eligibility changes can suspend a previously eligible security.
- [TWSE investment guide](https://www.twse.com.tw/zh/about/company/guide.html): ordinary stock SELL tax 0.3%; qualifying stock day trade 0.15% through 2027-12-31; brokerage fees determined by brokers.
- [Ministry of Finance extension](https://www.dot.gov.tw/singlehtml/ch26?cntId=fde9d7d1546d4df8a4db96bf23e2f57c): statutory reduced-rate extension through 2027-12-31.
- [SDK snapshot fields](https://sinotrade.github.io/tutor/market_data/snapshot/): read-only snapshot contains timestamp, buy/sell prices and volumes. SDK stock snapshot volume is normalized from board lots to shares in the adapter.

No historical outcome is used to establish eligibility or an earlier fill.
ETF/ETN, short-first, odd-lot, delayed-close and overnight execution are outside
this long ordinary-stock simulator's supported execution scope.

## Execution policy

- Existing 09:30 start, 12:30 exclusive entry cutoff, 12:55 force-exit attempt,
  and 13:00 worker end are EasyStock strategy/risk policy. Exchange ordinary
  session ends at 13:30. No strategy thresholds were adjusted.
- BUY requires current-session SDK day_trade Yes/OnlyBuy and ordinary-stock
  category; No is ineligible and missing/unsupported metadata is unknown.
  This broker contract flag is a runtime input, not an independent archival
  certification of the exchange's daily list. If the broker does not reflect
  an intraday suspension, this remains a data-source limitation requiring
  live review. No eligibility is inferred from listing alone.
- Fresh directional snapshot (maximum 15 seconds, Taipei same day), BUY ask
  or SELL bid and positive executable depth are required. Last price is not
  a fill rule. Locked limits with no counterparty skip BUY / leave SELL pending.
- BUY size is capped by both remaining daily notional and best-ask depth in
  whole 1,000-share lots. SELL requires sufficient bid depth for the whole
  position; partial SELL fills are intentionally not fabricated.
- Research persists before the Paper attempt. Eligibility/depth failure only
  affects Paper. Research closes independently; pending Paper settlement retries
  with a fresh bid and the same identity, and stored receipts are idempotent.
- Force exit requires fresh supported SELL evidence. Missing evidence leaves
  Research open; missing executable Paper depth leaves Paper pending. No
  stale entry/current price fallback is used to manufacture a force-exit fill.
- Cross-day positions remain blocked for manual reconciliation. No favorable
  day-trade tax is applied to an overnight simulated settlement.

## Canonical cost assumptions

`paper_execution.py` is the shared cost path for ledger and Research estimates.
Reference rate 0.1425%, simulator discount multiplier 0.28, minimum fee NTD 20,
integer ROUND_HALF_UP per simulated fill. These fee/minimum/rounding settings
are simulator assumptions, not a universal broker tariff or asserted tax-law
rounding mandate. Existing ledger results are preserved; tax is now rounded
once directly from unrounded notional, avoiding double rounding.
Qualifying same-day stock tax is 0.15%; the helper uses 0.3% otherwise. Runtime
Paper BUY rejects ineligible/unknown instruments and SELL rejects overnight
positions rather than inventing a non-daytrade fill. Historical rows are intact.

## Live validation

On 2026-10-03 (Saturday) no new complete live session can be established.
`READY_FOR_LIVE_VALIDATION`, never `LIVE VERIFIED` from fixtures.
Allowlisted market observations now append to private date-scoped JSONL;
`deploy/verify_live_daytrade.py --date YYYY-MM-DD` reads these and durable
Research records without network calls or production mutations. Review session
coverage, source ages, recovery transitions, model readiness and natural
Research/Paper skips; absence of a natural over-limit candidate remains open.

Do not alter daily limits, entry predicates or quotes to force a live event.
No broker Order API, live position, or LIVE AUTO switch is part of this change.
