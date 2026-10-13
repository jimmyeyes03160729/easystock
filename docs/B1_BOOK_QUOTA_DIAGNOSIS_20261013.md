# B1 five-book admission diagnosis and alternate-API probe, 2026-10-13

## Scope

The user requested investigation of B1's 18,798 `未分配五檔額度` evaluation
rejections and a trial of another API if coverage remained constrained. This
change adds a bounded, market-data-only E.SUN probe and mocked tests. No service,
production trading source, lane rule, account, ledger, Firebase node, or strategy
threshold was changed. No Git push is included in this request. Production VM
HEAD remains `666ad08`.

## Confirmed mechanism

- `QuoteSubscriptions` defaults to 190 shared reservations, 170 Tick and 20
  BidAsk. `unselected` means no local BidAsk record, not a provider rejection.
  Reservations include pending and cancelling subscriptions until ACKs confirm
  release. This safety behavior must not be removed to manufacture capacity.
- B's status callback is hardwired to that manager's BidAsk state. An alternate
  provider cannot fix admission merely by inserting books; provider-aware
  subscription status and provenance must also be integrated.
- `_select_b_books` ranks metadata-valid candidates, pins open positions and
  holds selected candidates for 60 seconds, but does not exclude unaffordable
  whole lots before allocating scarce books. LaneSuite later applies its
  unchanged 200,000 TWD per-entry / 1,000-share limit.
- At 09:18:55, the published manager reported 159 active Tick, 18 active BidAsk,
  eight cancelling Tick and three pending Tick: 188 reservations, book cap 20,
  tick cap 170. Its internal `quota_wait` count was 470. That observed snapshot
  contained no subscribe-rejected counter; the inspected morning journal also
  contained no `Max Num Subscriptions` event. This does not establish that every
  provider operation all day succeeded or measure the byte-usage quota.

## Opening-session incident evidence

A bounded read of the active B recording stopped at the first clock >=09:10.
Its manifest is incomplete because collection continues; this is a captured
incident prefix, NOT a sealed replay, backtest or full-day performance claim.

From 09:00:00.074335 to 09:09:59.245736: 316 clock records, 3,528 active-book
symbol/clock observations and 19,324 unselected observations. Among the active
observations, 2,315 (65.62%) had the latest recorded radar trade price >200 TWD.
Examples include 5536 at 914, 2313 at 246, 2327 at 613 and 2317 at 242.
These are repeated observations, not distinct-stock percentages or executable
ask/bid prices. Eighty-six distinct symbols were active at some point; a 20-slot
pool is not the same as only 20 symbols observed for the entire session.

The 19,324 clock-state observations and 18,798 lane rejections have different
eligibility/timing grains, so they are not added or treated as identical counts.
The persisted B1 state had zero entries, one `entry_fill_checks` and one
`entry_limit_checks`: a signal reached the fill stage but whole-lot capacity
prevented admission. That counter alone does not identify its symbol.

## E.SUN isolated trial

Official market-data docs support `books` and `trades`; their published limit is
300 subscriptions and two WebSocket connections. This is not unlimited capacity.
The existing production connection continues to serve seven indices. The probe
uses one separate connection, stops on provider errors or existing-worker health
changes, unsubscribes only its own channel IDs, then disconnects. It never retries
login, generates B entries, or writes live data.

- Initial 60-second observation: 30 symbols / 60 channel ACKs, 29 symbols with
  valid fresh five-level data and 30 with fresh trades; no provider error.
- Instrumented repeat: 09:32:37.939–09:33:14.055 local Taiwan time including
  login/connection and cleanup, with a configured 30-second observation. Again
  60/60 ACKs, 29 valid-book symbols and 30 trade symbols: 15,169 valid live book
  events and 2,232 live trades, all counted as fresh only within three seconds.
  Snapshot events are separate and never count as continuous observations.
- 6488 supplied two bid levels and five ask levels in the captured sample;
  171 book events failed the fixed complete-five-level validator. This is not
  an authentication failure and is not proof of an API defect. No missing levels
  or quantities were fabricated to make the lane pass.
- Existing E.SUN worker stayed PID 1779638, authenticated/subscribed with seven
  index channels and reconnect count 31 before/during/after both probes. At
  09:35:08 it remained active with a fresh 09:35:05 index update. Both probe
  processes had ended; no permanent extra service was installed.

The final instrumented VM probe hash was
`f82593602d2b290a27a6e6a58414b36d2e59cb62cc8ae78ee475d1204bd5ac81`.
A subsequent local null-level defensive check does not change valid-data metrics;
it is covered by mocked tests, not represented as another live trial.
Evidence artifact: `esun-b-books-probe-20261013.json` in the task output directory.

## Decision boundary

The tested replacement candidate is E.SUN five-books, with Shioaji Tick retained.
Before a production switch: make B subscription state provider-aware; prioritize
affordable whole lots (without evicting existing holdings); verify timestamp and
size-unit contracts; reject partial/stale/crossed books; demonstrate stable
cross-provider synchronization, fail-closed reconnect behavior, CPU/queue limits,
and opening-session coverage. A 30-stock daytime sample does not prove 170-stock
capacity, full B1 compatibility, aggressor classification or profitable fills.
Do not lift risk/cost rules or invent observations merely to generate trades.

Verification: six mocked Node probe tests and 64 existing Python subscription,
B-lane and metadata tests passed. Existing lane logic is unchanged.

## Official references

- [E.SUN rate limits](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/rate-limit/)
- [E.SUN five-book channel](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/websocket-api/market-data-channels/books/)
- [Shioaji usage limits](https://sinotrade.github.io/zh/tutor/limit/)
