# B cross-provider shadow integration — signal-only

Authorized on 2026-10-13: isolate an E.SUN five-book + Shioaji native-tick
comparison from the production B recommendations, accounts, notifications,
Firebase and trading source. No production-source replacement or Git push is
included in this shadow trial.

## Components

- `market_data/b_shadow.py`: bounded CRC-checked live-journal follower, strict
  E.SUN normalization, affordable ordinary-stock pool and signal-only comparator.
- `deploy/esun_b_shadow_bridge.cjs`: one bounded E.SUN stock-books connection;
  initializes the installed SDK socket AFTER login, preserves source timestamps
  and sizes, emits only approved quote fields, excludes snapshots from live data,
  and disconnects/unsubscribes only its own channels.
- `deploy/run_b_books_shadow.py`: runs up to 90 seconds with explicit warmup,
  at most 40 symbols, 10,000 queued bridge events and private new output only.
- The original `LaneSuite._signal()` is unchanged. The comparator never calls
  `advance()` or an execution method. Both suites use `offline=True`, private
  SQLite paths, no publisher, no recorder and a no-op sender. No positions,
  fills, capital consumption or portfolio performance are generated.

## Input and state contracts

Native Tick price, timestamp, direction classification and volume come from the
existing live journal. No additional Shioaji login/subscription or inferred
aggressor classification is introduced. The active journal is NOT a sealed
replay or training dataset. A sequence gap, CRC failure, overflow or rotation
fails closed. Partial gzip members are retained until complete.

The initial pool uses fresh actual radar metadata, ordinary four-digit symbols,
valid reference/sector and a 1,000-share notional <=200,000 TWD. This allocates
research data rather than loosening signal rules. At each native signal, actual
directional entry-price affordability and explicit short eligibility are checked
again. The pool is frozen for this bounded trial; no shadow holdings exist.

E.SUN books require an actual ACK on our own socket. The native manager's
`unselected` status is never reused for E.SUN. Disconnect/error makes the shadow
status failed, including when previously good books remain cached. Full five
positive ordered prices, nonnegative finite quantities and an uncrossed spread
are required; missing levels are NOT invented. Source and receipt times must be
timezone-aware, same day and within three seconds. UTC `Z` is explicitly parsed
as `+00:00`, including on VM Python 3.10, without rewriting recorded evidence.

Raw journal-receipt freshness and production decision-clock freshness are
different facts. Raw input >3 seconds is rejected. A native subscription-state
clock >5 seconds is labeled unavailable for the native control; it is not a
proxy for the freshness of current Tick callbacks. Native status-stale clocks
cannot support a paired eligibility comparison. Market validity/BLOCK and
30-second candidate/market ages retain the original rules.

## Measurement boundaries

After warmup, clocks sample the same stock pool at the shadow's actual current
time. Record fresh Tick, fresh five-book and joined symbols independently of
market/strategy permission. A fresh join requires both sources <=3 seconds old
and their exchange-time skew <=3 seconds. This is availability, not an entry.

Signals are repeated candidate/time events, not distinct recommendations or
fills. B1 is only evaluated before 09:10; a later test explicitly reports B1
outside its entry window. B2/B3 samples are not opening-session equivalence.
Native control warm history, recorder lag and E.SUN startup differ; disclose
them instead of claiming a win from a zero-control or unavailable snapshot.

Quantities remain provider-native. OBI is a within-provider ratio, so this
signal-only experiment does not multiply sizes or assume lots/shares. Exact
near-synchronous full-vector comparisons are retained as bounded, distinct
samples, not proof of the universal quantity-unit contract. Unit verification,
depth execution and financial simulation remain blocked. Always export
`execution_allowed=false`, `deployment_allowed=false`, `training_eligible=false`.

## Reproduction

Place the four implementation files in a private bundle with their relative
paths, retain production repo as a READ-ONLY import source, and run:

```sh
/home/ubuntu/easystock/.venv/bin/python -u <bundle>/deploy/run_b_books_shadow.py \
  --repo /home/ubuntu/easystock \
  --module-file <bundle>/market_data/b_shadow.py \
  --journal <existing-live-B-journal.jsonl.gz> \
  --bridge <bundle>/deploy/esun_b_shadow_bridge.cjs \
  --output <new-private-results-directory> --seconds 60 --warmup 15
```

Outputs: `protocol.json` with source hashes, `events.jsonl` with original E.SUN
source/receipt fields and shadow clocks, and `results.json` with both arms,
coverage, rejects, sample unit comparisons and the deployment blockers.
Finished helpers do not remain resident. No service/timer is installed or
scheduled; next-session B1 validation is still required before production use.

## Checks and repairs during authoring

81 scoped Python tests passed locally (17 shadow and 64 subscription/B/metadata
cases); seven mocked Node probe/bridge tests passed. Guards cover partial gzip,
sequence/CRC faults, source identity, future/stale times, incomplete/crossed
books, unaffordable lots, provider-aware status, disconnection, market BLOCK,
unchanged production positions, private outputs and SDK-token timing.

The first trial exposed SDK socket-before-login construction and was discarded.
An instrumented trial then exposed Python 3.10's lack of direct UTC-Z parsing:
ACKs and book reception were healthy but the shadow adapter rejected all those
books. That run is NOT evidence of live integration success. Both defects were
repaired with regression tests; retain earlier outputs only as debugging evidence.

VM integration receipts and final outcome are recorded separately in
`B_BOOKS_SHADOW_RESULTS_20261013.md`; do not treat implementation tests as an
opening-session or profitability validation.
