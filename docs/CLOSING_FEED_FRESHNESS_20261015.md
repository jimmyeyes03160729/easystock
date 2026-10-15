# Closing-eight feed freshness repair — 2026-10-15

The saved 13:24:30 observation contains 328 rows with insufficient inputs and diagnostic 缺當日有效尾盤行情快照. Observer jobs took 7–24 seconds during the final minutes. The decision timestamp was captured before journal and Firebase reads; the continuously rewritten equity snapshot could therefore appear future-dated. Stale journal quotes were then used. There is no retained raw pre-cutoff REST snapshot to retrospectively establish which stocks would have passed.

Read fixed context/equity/share metadata before assigning their cutoff. Evaluate quote age and session phase again after daily enrichment. Future receipts and the 30-second exchange quote limit remain strict. Current index context supplies closing benchmark strength without adding opening boundary history.

Reuse existing snapshot.quotes polling at 15-second intervals during 13:00–13:25, with unchanged WebSocket subscriptions and normal polling outside that window. HTTP latency can extend the interval; stale individual quotes remain insufficient.

Publish and display historical pre-cutoff coverage: insufficient, fully evaluated, all-pass, evaluated failures. New empty receipts distinguish insufficient data from fully evaluated no-match. Existing immutable receipts and observations are never rewritten or filled with post-close data.

Validation: 32 focused Python tests, including delayed-input/cutoff crossing, snapshot replacement, future receipts, immutable receipts and distinct empty reasons. Full pnpm test passes (76 Node subtests plus existing script suites). Deployment uses a four-file hash allowlist, backup, inactive-engine guard and before/after evidence hashes; only the read-only market-data service restarts. No real order calls.
