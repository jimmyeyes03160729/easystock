# Shared Shioaji quote subscription budget

## Incident and correction

On 2026-10-12 the opening-session journal showed Shioaji rejecting BidAsk
subscriptions with `Max Num Subscriptions Exceeded`. The 170-stock Tick pool
and B lanes' unbounded per-row BidAsk requests shared a 200-subscription limit.
The old code marked a request successful before receiving the broker event.

`market_data/subscriptions.py` now accounts for Tick and BidAsk together:
170 Tick slots, 20 shared BidAsk slots, at most 190 reserved subscriptions.
Pending subscribe and cancellation requests consume slots until their result
is known. Cancellation requested before the subscribe ACK is deferred until
that ACK; these topic-only ACKs must never overlap and release a slot early.
A transport exception retains its reservation. Explicit subscription
rejections release their reservation and have a 30-second retry cooldown;
failed or unacknowledged cancellation is retried with the same cooldown.
An absent-subscription response confirms cancellation. Incoming quote data
can confirm a pending subscription, but cannot undo a cancellation.

The three B lanes share a ranked 20-stock book pool. Open B positions are
pinned first; valid incumbents keep a 60-second minimum lease. Opening-session
ranking favors sector-aligned candidates, then directional volume and traded
amount. Ranking allocates data and is not an alternative strategy-entry gate.
All pool rows still feed the sector context. Existing position, fee, tax,
entry/exit-time and risk rules remain in effect. Restored B positions regain
Tick and BidAsk before scanning. Dropped, previously pinned stocks are cleaned
up after their positions close.

Universe metadata exposes confirmed/pending/cancelling/failed counts and the
shared reservation count. B rejection counters now distinguish unselected
books, broker rejection, confirmation waits, stale book/tape, insufficient
tape/book history, spread, trade classification and missing reference prices.
Per-clock subscription states are captured with replay inputs so diagnostics
remain reproducible. The replay strategy fingerprint changes with this release;
older recordings are preserved and must be evaluated with their matching code.

## Validation

Broker-free tests cover the 170+20 bound, asynchronous and synchronous refusal,
uncertain transport, cancellation failure/absence, cooldown, stable leases and
position pinning. Existing B signal/replay, SDK metadata, A entry diagnostics,
market-risk, VM safety and architecture tests are also run. No live test orders
or test notifications are needed for deployment verification. Next-session
quote coverage and rejection counts still require observation during trading.

Official specification: https://sinotrade.github.io/zh/tutor/limit/
