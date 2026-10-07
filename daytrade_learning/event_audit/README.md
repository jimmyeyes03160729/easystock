# event_audit

Shared, tested building blocks for causal entry-event studies on the archived
ticks and 1m kbars. Research only: no orders, no live services, no model fitting.

| module | frozen convention |
| --- | --- |
| `timebase` | archive `ts` = naive Taiwan wall-clock in ns; 42-stock core; five chronological test windows; entry window 09:30-12:30; force exit 12:55; hard cutoff 2026-10-02 |
| `bars` | complete 5m/15m buckets aligned to 09:00 (as `intraday_live._aggregate`); a bucket with a missing minute is dropped; causal rebuild check |
| `episodes` | false->true episodes; a transition < 15 min after the previous accepted episode is excluded |
| `markouts` | entry = latest tick <= decision (age <= 30s, never the next tick); exit = latest trade <= target; 30m/60m past 12:55 -> `HORIZON_AFTER_FORCE_EXIT`; path metrics read only (decision, decision+15m] |
| `costs` | 1000 shares, `paper_execution.fee/tax` rounding; LONG quote stress = entry ask / exit bid |
| `classify` | fixed A-H criteria; rule order: G false, A false, all true, B or H false, otherwise cost-blocked |

## Provenance of the audits these conventions come from

Results below are 15m gross over the five test windows (historical data reused,
no independent confirmation; none is a trading candidate).

| audit | result (15m gross) | bundle sha256 |
| --- | --- | --- |
| H2 tick compression breakout | -6.416 bps | (H2 bundle, 2026-10-05/07) |
| H3 completed-5m compression breakout | -5.559 bps | `79d5583819de4511ddec1dddcad1b1ca684aacd480b4cbe8a0a978e81161dba7` |
| H4 source-native ORB | -5.044 bps | `376d87d361c5b8fbd92e34b2c38874f583218f5c5af3208f1d868a56fa233be6` |
| 8 source entry primitives (registry `e9c22bae...aac2b`) | -0.28 to -5.93 bps | `ac90d8ace244252043cf132380e16ddca9af91d72d6d6924f7d9227155322bde` |
| Knowledge V1 book rules C01/C02/C04 (registry `227c6ed9...9707`) | C01 -7.19, C02 +1.48, C04 +3.06 bps (weak/unstable) | `a6e7c5227e081182907d204c25a58442006dfc77aa90f572bb4ce07353bcef93` |
| base-rate / matched control | unconditional -1.01 bps (all days), -1.37 bps (test windows) | `c99aacdaaaf9145c8627b5405e4246d43f75e21681f8b80ab0f36ef67082bcd8` |

## Known pitfall: nearest-in-time matched controls are biased

A control placed >= 15 min before an event sits in the run-up that triggers it, so
control returns are inflated (+13..+73 bps vs a -1 bps base rate).  Compare events
with the symbol x 30-minute-bucket unconditional mean instead.

## Not in this package

The per-audit runners (parallel per-day workers, bundle writers) still live in the
VM `/tmp/easystock_*` work directories.  New audits should import these modules
rather than copy the old helper files.
