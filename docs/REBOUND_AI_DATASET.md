# 觸底反彈 AI Phase 1 Dataset

## Baseline and boundary

Production remains `range_rebound.py` / `range-rebound-0.3`. The website and
Chrome continue to consume the existing `rebound_feed`; this package does not
alter ranking, Top 3, entry/exit decisions, or approved intraday models.
Historical `scan_rebound.py` is **not** this dataset's strategy.

## Source and storage

Private source is the VM's audited Shioaji daily minute-K archive at
`/home/ubuntu/easystock-history-expanded-data/raw/<day>/<symbol>.json.gz`.
Minute timestamps use the archive's documented *naive Taiwan wall-clock*
encoding; only 09:01–13:30 regular-session bars are aggregated. The frozen
100-symbol archive is not whole-market coverage. The `plan.json` market dates
define the trading calendar. Source archives are never changed by this code.

Research SQLite, JSON audit and Markdown audit live under
`/home/ubuntu/easystock-learning-data/rebound/`, not Firebase or Git. SQLite
uses a unique `(strategy_version, feature_schema_version, signal_date,
symbol)` constraint; the stable row ID also includes `candidate_kind`.
Replaying unchanged history is idempotent; changed source bars or changed
candidate definitions stop with an explicit error instead of silently
rewriting already-labelled research history.

## Dataset schema and candidate kinds

`dataset_schema_version=1`, `feature_schema_version=1`.

- `PASSED`: technical rule eligible and all required financial values have
  documented publication timestamps at/before the D0 22:30 research cutoff and pass the existing
  financial gate.
- `PENDING`: technical eligible; historical financial PIT evidence unavailable
  or incomplete. This is the expected historical bootstrap category.
- `NEAR_MISS`: exactly one of three numeric technical gates misses by the
  configured tolerance: distance above support ≤1 percentage point beyond
  the 10% gate; range position ≤3 points beyond the 35% gate; or net RR ≤0.10
  below 1.5. All support, resistance, retest, confirmation, and bracket
  checks must pass. Malformed K, insufficient bars, broken support and other
  rejected stocks are never reclassified as near miss.
- `REJECTED_CONTROL`: deterministic SHA-256 sample (1 in 50) of remaining
  liquid rejects. It has no fabricated target/stop and is not trainable.

Research-only diagnostics independently inspect thresholds; the production
`evaluate_technical()` return value and `build_rebound_feed()` are unchanged.

## Features

D0 close-of-session snapshot: support/resistance distances, range position,
support/resistance touches, support span/age (nullable where the production
rule does not expose them), raw/net RR, ATR percentage, MA20/MA60 biases and
five-day slopes, 3/5/20-day returns, candle body/shadows/close position,
5/20-day volume ratios, amount and frozen-pool amount rank. Exactly 26
numeric features are versioned in v1. Missing values are `null`, never zero.
Financial values without a verified `published_at` are not stored as AI
features. Historical E.SUN, sector, breadth and today's sector mapping are
not retroactively filled. D0 feature extraction rejects any D1+ bar.

## Label and outcomes

Signal date is D0; the backfill uses a conservative 22:30 Asia/Taipei
research cutoff, after the observed 15:30 market-update schedule and after
the history collector window. It is an assumed replay cutoff, **not** a claim
that historical production feed publication logs exist at that timestamp.
The simulated entry is D1 **open**, not D0 close. The main horizon is 10
market trading sessions. The first target touch is `SUCCESS`, the first
invalid/stop touch `FAIL`, neither by D10 `TIMEOUT`. If target and invalid
both touch within one daily bar, `AMBIGUOUS` is retained but not trainable.
Overnight D1 opens outside the original bracket are retained as untrainable
`entry_outside_bracket`; no fictitious trade is recorded. Missing stock bars
within the market-calendar horizon likewise remain unlabelled, not shifted
to a later bar.

Return after 1/3/5/10/20 market sessions uses that day's close versus D1 open.
MFE/MAE over 5/10 sessions uses the high/low envelope. Unmatured horizons
remain `null`; no forward fill. Label data live separately from candidate
snapshots, preserving point-in-time replay.

## Operations and audit

```bash
python3 -m rebound_learning.backfill --limit-days 20 --dry-run
python3 -m rebound_learning.backfill --from 2023-09-04 --to 2026-09-30
python3 -m rebound_learning.labels
python3 -m rebound_learning.audit
```

`--limit-days 5` supports daily refresh. The independent after-hours timer
runs collector, then labeler, then audit. No module import starts a run.
Audit outputs include version counts, coverage, candidate/label distribution,
null rates, near-miss reasons, duplicate ID and future-leakage checks,
non-monotonic dates, OHLC defects, impossible price brackets and warnings.
Critical findings make the CLI exit nonzero.

## Limitations and Phase 2

The archive covers only its frozen stock pool, begins when the plan has
reliable archived bars, and may have per-stock gaps/corporate-action breaks.
Historical current-summary financials cannot be backdated without explicit
filing publication timestamps. E.SUN live sector data started later and is
not usable as a historical feature. Phase 2 must first review audit coverage,
class balance and out-of-sample splits before comparing rule baseline,
Logistic Regression and HistGradientBoosting in shadow only.

## Dataset v2: official whole-market daily (Phase 1.5)

v1 above stays frozen. v2 lives in separate private files under the same
directory: `market-daily.sqlite` (source archive) and `dataset-v2.sqlite`
(`dataset_schema_version=2`, `feature_schema_version=2`).

**Source.** One TWSE `MI_INDEX` and one TPEx `dailyQuotes` request per session
return every listed/OTC four-digit stock (ETFs, warrants and no-trade rows are
excluded; no flat bar is fabricated). Stocks that later delisted stay in the
archive, so the universe has no survivorship selection. TAIEX
(`發行量加權股價指數`) and TPEx composite (`櫃買指數`) closes are stored per
session. Past weekdays without data are recorded `closed`; the current day is
never recorded closed before publication.

**Corporate actions.** Prices are stored raw. `adj_factor` on day *t* is the
exchange-published reference price divided by the previous close: TWSE
`TWT49U` for TWSE ex-rights/dividends, the previous session's `次日參考價` for
TPEx. A reader standing on D0 multiplies only by factors of sessions ≤ D0;
label bars after D0 are rescaled by factors as each event occurs. TWSE "X"
sessions without a published TWT49U event are marked `unknown` and counted per
candidate (`adj_unknown_events_252d`); the rule's 12% gap guard still applies.

**Candidates.** Same frozen `range-rebound-0.3` rule. Without historical filing
timestamps every eligible row is `PENDING` (never `PASSED`). Kinds:
`PENDING`, `NEAR_MISS` (unchanged v1 definition), `BOTTOM_ZONE` and
`REJECTED_CONTROL`. `BOTTOM_ZONE` keeps every structural gate (repeated
support, resistance, retest within 8 sessions, unbroken support, breakout or
two-day stabilisation) and allows up to three numeric misses within: distance
above support ≤5 points beyond 10%, range position ≤15 points beyond 35%, net
RR ≥1.0. It widens the training pool; evaluation must still compare models on
rule candidates only.

**Features.** The 26 v1 features plus 11 point-in-time context features:
TAIEX/TPEx 1/5/20-session returns, TAIEX bias to its 60-session mean,
whole-market breadth (share of stocks closing up among up+down), stock minus
own-exchange index 5/20-session return, and `is_otc`. Sector context is not
included: only today's sector mapping exists, which is not point-in-time.

```bash
python3 -m rebound_learning.market_daily --from 2022-01-03   # resumable
python3 -m rebound_learning.market_daily --status
python3 -m rebound_learning.official backfill --from 2023-01-03
python3 -m rebound_learning.official labels
python3 -m rebound_learning.official audit
```

The nightly `rebound_learning.daily` job refreshes v2 after v1 commits:
recent sessions, the last five replays, label maturity and the
`rebound-dataset-v2-audit.{json,md}` report.
