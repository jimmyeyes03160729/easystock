# Dual five-book integration: guarded mode configured, opening not yet verified

User requested E.SUN + Shioaji five-books. The proposed allocation is Shioaji
native Tick (unchanged), E.SUN standard-stock books on its EXISTING index socket,
and Shioaji's existing 20-book reservations for calibration and held exits.
No new account, order API, second E.SUN connection, or higher Shioaji quota is
introduced. SDK credentials, index keys and risk/cost parameters are unchanged.

## Correctness contracts

- E.SUN book cap is 160 alongside seven index channels. Pending and cancelling
  books still reserve slots. Subscribe ACK must match symbol/channel; unsubscribe
  ACK must match our ID. Books must match the currently ACKed channel ID.
- Snapshots/trial/delayed/partial/crossed/future/old books are not live evidence.
  Exchange microseconds are preserved, not rounded down to milliseconds.
- B is provider-aware. A source/epoch switch clears book history and is recorded
  as `book_reset`; replay applies it. No five-second OBI continuity is borrowed
  across providers. Missing or stale worker state invalidates E.SUN availability.
- File snapshot age must be <=2 seconds; book exchange and receipt ages <=3
  seconds. Native callbacks accept SDK Decimal vectors without assuming strings
  are numeric. The original market/strategy permission gates still apply.
- E.SUN sizes are NOT globally assumed to be lots. A symbol needs three distinct,
  exact-exchange-time native/E.SUN pairs, all ten prices matching, at least eight
  positive native depth values and all ten quantities consistently matching either
  1x native lots or 1000x native lots. Shares are converted only after that proof.
- A quantity conflict quarantines the symbol for the current socket epoch.
  Disconnect/reconnect revokes calibration. Cached poll copies cannot count as
  new evidence. This is per-symbol operational evidence, not a universal API
  contract inferred from a few stocks.
- Scarce native calibration slots rotate toward unverified/missing E.SUN books;
  open positions remain pinned for backup exits. IPC requests renew even after
  radar cutoff. Unaffordable >200 TWD candidates do not consume new book slots,
  while already-held stocks are never excluded by that candidate filter.

## Recorded historical evidence

`research/audit_b_book_units.py` inspected two saved E.SUN incident captures
(36,301 valid indexed book events) and a bounded native journal prefix. Among
7,162 native book events in the E.SUN window, 745 unique exact-exchange-microsecond
pairs also had identical full price and size vectors, all at native lot scale:
2480 (25), 3231 (201), 3702 (24), 5483 (115), 6116 (77), 6505 (303).
There were no size mismatches among those exact pairs. Six observed stocks do
not establish every stock's quantity unit or a stable current live join.

Evidence: task artifact `dual-books-unit-evidence.json`; upstream E.SUN captures
remain `/tmp/easystock-b-shadow-O3Jb8C/results-final/events.jsonl` and
`results-validated-2/events.jsonl` on VM. The audit records input SHA256 and native
prefix SHA256. It is not a sealed whole-day replay or P&L backtest.

## Activation boundary

`RUNWAY_B_BOOKS_MODE=native` remains the code default. The VM service now explicitly
configures `dual` for its next normal start, enabling the guarded router and its
own IPC request. No global quantity-unit override is wired into production.
Each symbol remains on native books or blocked until actual fresh exact-time
per-symbol comparisons pass; then the original five-second continuity gate still
applies. Configuring this conditional mode is NOT evidence that B1 has already
used E.SUN or that today's 18,798 repeated evaluations have been repaired in a
live opening session. The engine was not started after hours.

Still required to call the deployment live-verified: a corrected live joined-feed
sample with actual provider ACKs, source/receipt ages, per-symbol calibration and
fallback behavior; queue/CPU/resource stability; and opening-session B1 coverage. Do not
manufacture quotes or relax B rules to meet that gate. No Git push is performed
without a current request; staged prior shadow files and research artifacts are
preserved.

## Safe installation

`deploy/install_dual_books.py --source <private-bundle>` verifies allowlisted
production base Git blobs, refuses unexpected local modifications/symlinks,
backs up every overwritten file and records installed SHA256. It refuses an
active intraday engine and only restarts the read-only E.SUN collector. It does
not enable dual mode, start the engine, modify credentials or commit/push Git.

## Deployment and after-hours receipts

At 2026-10-13 19:57 Taiwan time, the allowlisted source bundle was installed on
VM and the read-only E.SUN collector restarted. Production Git HEAD stayed
`666ad08fd6c86ec16f40a22f4315fa025f3e4189`; installed source SHA256 and recoverable
original files are recorded under
`/home/ubuntu/easystock-maintenance/dual-books/20261013T115734861070Z`.
The intraday engine was inactive and was NOT started. Dual mode was NOT enabled.

From 20:01:07 to 20:01:40, `deploy/probe_shared_books.py` requested six standard
stocks via owner-tagged IPC on the existing collector. All six reached active
ACK state; 30 one-second observations had reconnect count zero. All own-channel
unsubscribe ACKs released the reservations. Seven index subscriptions remained
available. Zero live book rows were observed after hours, so this does not pass
quantity calibration, join-latency, capacity or B1 opening coverage gates.
The probe did not log in, open another socket, start intraday or place orders.
Receipt: task artifact `dual-books-shared-probe.json`.

Local focused verification: 119 Python tests (including unchanged native B,
quota, metadata, replay and prior shadow tests); 27 Node tests (shared collector,
index provider and prior probe/bridge tests). Synthetic B1 integration explicitly
tests a verified E.SUN source when native BidAsk status is `unselected`; no real
recommendation or account entry is inferred from that synthetic result.

At 20:13, the IPC-failure fallback repair was synced after checking all installed
SHA256 against the first receipt. A second backup/receipt is at
`/home/ubuntu/easystock-maintenance/dual-books/20261013T121305261382Z`.
The collector did not need another restart. The exact deployed router/lane
combination passed 25 isolated Python tests on VM; the book/index modules passed
20 mocked Node tests on VM.

The task-owned systemd drop-in
`/etc/systemd/system/easystock-intraday.service.d/zz-dual-books.conf` sets only
`RUNWAY_B_BOOKS_MODE=dual`. It was installed only after verifying that filename
did not already exist, and followed by daemon-reload, not an intraday start.
Rollback: restore the dated original allowlisted files and remove/disable ONLY
this newly created mode drop-in. Do not remove any other service override,
credential, paper state, recording, or strategy setting. Existing staged shadow
files and unrelated research files were preserved during deployment. The user's
subsequent Git-update request scopes publication to the B probe/shadow work and
guarded dual-book integration, including its unit audit. One-year backtest
research artifacts remain local; this Git update does not restart the VM engine.

## References

- [E.SUN books](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/websocket-api/market-data-channels/books/)
- [E.SUN limits](https://www.esunsec.com.tw/trading-platforms/api-trading/docs/market-data/rate-limit/)
- [Shioaji limits](https://sinotrade.github.io/zh/tutor/limit/)
