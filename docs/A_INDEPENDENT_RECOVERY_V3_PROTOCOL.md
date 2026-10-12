# Independent recovery v3 — frozen research protocol

Scope: implement the user's 2026-10-13 request to independently study direct
low-open continuation and pullback continuation. This is OFFLINE ONLY. Do not
wire it into intraday_live, accounts, models, Firebase, SDK sessions or services.
The experiment itself authorizes no Git push or production VM deployment.
The user's subsequent 2026-10-13 request explicitly authorizes committing and
pushing the research branch only; it does not authorize production deployment.

## Frozen hypotheses, before running v3 outcomes

Both entries require a below-historical-reference 09:00 open and a causally
completed VWAP reclaim. Evaluate only when a new five-minute bar has completed,
09:30 through 12:25, at second 3. Latest confirmation age <=10 seconds. Require
a bullish confirmation close, above cumulative five-minute typical-price VWAP,
with at least the preceding three-bar average volume. It is an approximation
of VWAP, not an executable quote.

- Direct: latest completed close exceeds the preceding two completed highs,
  and its low does not undercut the previous bar's low. No pullback is required.
- Pullback: reclaim precedes the pullback, the pullback closes above its VWAP,
  its low is within a support zone of max(one tick, 0.5 * preceding three-bar
  mean true range), its volume is <= preceding three-bar average, then the next
  completed close exceeds its high with a non-undercutting low. A red pullback
  is permitted; the confirmation, not the pullback, must be bullish.

These are explicit hypotheses, not optimal parameters. They were motivated by
10/12 and earlier research, so 10/12 cannot be an independent validation day.
Do not tune the thresholds after viewing v3 outcomes or force 3605 to pass.

## Comparable arms and diagnostics

`direct`, `pullback`, `union`, `union_score68_control`. The last arm applies the
legacy eligible rule only as a matched selection control, under declared market
assumptions. It is NOT a reproduction of the actual old trading system. All arms
share the same universe, clock, ranking, capital, fees, slippage and exits.
Independent arms never filter or rank by legacy score or recorded radar.
Rank by completed relative volume, VWAP distance, symbol, then direct before
pullback. One symbol can trade at most once daily even if both patterns occur.
Keep all causal signals, including subsequent losers and blocked executions.

Record legacy rule scores/eligibility and source context. Recorded radar is
diagnostic only: a verified, complete callback snapshot at/before the signal
within 30 seconds may establish presence/qualification; otherwise unknown.
Do not infer tick buy/sell classification or a real radar from minute OHLCV.

## Execution and safety

Next full minute after the two-second decision buffer; minute open is a trade-
price proxy, not an exact callback time. Require a nonzero-volume execution
minute, but never use its high/low/close/total volume to rank, size or choose a
signal. Depth and eligibility remain unverified assumptions. At execution,
observed price must remain above signal VWAP and the paid price including adverse
ticks must be <= confirming high + one tick (Decimal boundary comparison); preserve
price 1–2000 and gain <=8%. Estimated round-trip cost <=0.6%, evaluated separately
for one/two adverse ticks per side. No fixed percentage distance-to-VWAP ceiling
is imposed on the direct continuation hypothesis.

Daily BUY notional one million TWD, per-symbol at most 30%, whole 1000-share lots,
max two symbols before 10:00, four before 11:00, five thereafter. SELL does not
replenish allowance. Signals and fills are separate; expensive lots are skipped.
All arms use the same original hybrid exit, 1.8% hard stop, 4.5% take profit,
cost-aware breakeven and trailing parameters from v2. Liquidate on the first
available trading minute from 12:55; flag delayed liquidation and unresolved
positions rather than inventing fills. Evaluate both O-L-H-C and O-H-L-C minute
paths, plus marked intraminute-phase portfolio drawdown. These are scenarios,
not uncertainty bounds or actual account equity.

## Evidence boundaries

Use all complete ordinary-stock minute packs with historical previous closes,
not just the 100-symbol tick archive. Validate 270 consecutive, same-day,
Taiwan-time minutes, OHLCV and identity. Exclude missing/invalid data with counts.
This remains a retrospectively collected stock universe, not all historical
scanners or the whole market. Use only the latest 16 pack dates before 10/12;
first eight descriptive, later eight REUSED historical evaluation. They have
already been examined in v2 and are not untouched holdout. 10/12 is diagnostic.

Missing market, eligibility, executable depth and callback evidence prevents
deployment regardless of profits. A separate new forward sample including all
those facts, sufficient trades across market types, positive cost-adjusted
results and acceptable drawdown is required. This runner always reports
deployment_allowed=false and never trains, promotes or modifies live data.

## Snapshot and execution location

VM disk contention can require local execution from a private source snapshot.
Copy the same dated minute packs without new SDK/API requests. Large recordings
may be projected to byte-preserved radar-only lines: the producer streams and
verifies the original compressed-file SHA against its complete manifest, records
the original SHA and projection SHA, and the replay verifies the projection SHA.
Projection changes neither radar rows nor their callback timestamps. Keep source
hashes, all signals, per-scenario decision ledgers and trade links for inspection.
Streaming I/O repairs are implementation changes, not tuning of frozen entry or
exit parameters. Partial/aborted outputs must never be used as final results.
Audit the first true-range context bar against its actual preceding close, not
its own open, so historical gaps contribute to the declared volatility measure.

## Current minute-only evaluation disclosure

The large VM radar recording could not be fully hash-validated during this run
because of disk contention. Do not use partial projections. The local source
snapshot has 6,148 ordinary-stock minute packs; radar is `not_loaded`, not false
or absent from the market. Legacy scores/control use minute features and assumed
market conditions, not actual complete legacy execution evidence.

The frozen two-adverse-ticks cost ceiling combined with the 30% whole-lot budget
admits no trades: even the minimum estimated one-lot round-trip cost over the
allowed tick grid exceeds 0.6%. Show no-trade returns as unavailable for strategy
comparison, not as zero-risk success. Do not loosen the ceiling after seeing
results. A different cost-vs-expected-edge hypothesis requires a new protocol and
new evaluation evidence; it must not be sold as the same tested strategy.
