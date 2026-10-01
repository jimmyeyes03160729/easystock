# Accepted research episodes and paper execution

An accepted entry must pass the existing entry window, completed-bar strategy,
radar, market, approved-model (in model mode), fresh-price and user-price/gain
gates. The model threshold, radar and market thresholds are unchanged.

`PositionManager(research_mode=True)` persists an independent research identity
before calling the paper adapter. `research_trade_id` and `episode_id` identify
the strategy episode; `paper_trade_id`/legacy `trade_id` identify an actual cash
fill. A wallet rejection creates `paper_execution=SKIPPED` with a structured
reason, including `insufficient_cash`, and never removes the research position.
No position size, capital or ledger entry is invented for research-only trades.
Each open episode attempts paper execution at most once. Successful paper fills
remain subject to the existing same-symbol no-reentry policy and daily limit.
The daily paper limit does not cap valid research opportunities.

Research OPEN episodes receive real tick prices and the same stop, target,
trailing, breakeven, completed-bar technical and force-exit rules. CLOSE records
include PnL, MFE, MAE and exit reasons. Research-only closes never invoke paper
settlement. Paper-filled closes record research CLOSE independently, then settle
the separate wallet. A failed settlement remains pending with the same frozen
exit price and paper identity; retries use the ledger's idempotent receipt.
No false paper EXIT notification is emitted while settlement remains pending.
Research-only tracking is not sent as a paper-fill notification.

## Evidence and restart

`LEARNING_DATA_DIR/research.sqlite` is the research source of truth. Writes and
re-arm states are synchronous, private, and protected by SQLite transactions and
a unique OPEN-symbol index. `journal-YYYY-MM-DD.jsonl` is a derived entry/exit
audit and sample stream, not a second authoritative research ledger. This
database persists accepted episodes even when optional journal sampling is
disabled or its bounded queue drops an event. The paper SQLite ledger remains
the cash source of truth. Firebase open/closed records are derived mirrors.

Restart restores research-only positions, extremes, model evidence, pending
paper settlements and re-arm state from the research database. Existing actual
pre-upgrade paper positions can migrate into tracked episodes with an explicit
legacy-paper identity. No missing historical research trade is invented.
Pre-upgrade paper CLOSED mirrors are imported only when their exact paper
identity has an existing sold receipt in the cash ledger, keeping legitimate
same-day trades in the summary. This migration reads the wallet without editing
history; unfunded signals and unverified mirrors are never manufactured as trades.
Conflicting or unconfirmed wallet identities fail reconciliation instead of
silently attaching an unrelated fill. A cross-database interrupted execution
is not retried blindly. The engine rebuilds mirrors from durable evidence;
late publish retries cannot reopen CLOSED episodes or erase newer episodes.

After CLOSE the symbol is DISARMED. A later observed strategy veto, radar
exclusion, rejected evaluated model or failed user-price/gain condition re-arms
it; an accepted observation after that can open the next episode. True setup
continuation, cooldown expiry, missing model data, and delayed pre-close
observations do not re-arm. Research reentry does not enable paper reentry.

## Public summary

The daily summary and offline research report read the research database first.
They count all accepted episodes, open/closed research trades, paper fills and
paper skips, with insufficient cash counted separately. PnL/MFE/MAE and exit
reasons include research-only trades. Dates are selected from durable evidence
even if the corresponding asynchronous journal event was not written.

Research gross return remains `pnl_pct`. `research_net_pnl_pct` assumes one lot,
the existing discounted fee schedule and day-trade tax with the ledger's decimal
rounding. Summary wins/losses and averages use these net returns where available;
legacy records without cost evidence retain their gross basis. Summing episode
return percentages is explicitly not a wallet/portfolio return. No cash balance,
position size, settlement detail, feature inputs or gate-setting payload is
published. Historical days without a research database retain a clearly marked
legacy mirror/journal basis rather than fabricated research history.

## Synthetic 3189 validation and actual October 1 evidence

Fixtures use price 1015/1020 and cash 199652. Twenty repeated accepted
observations while OPEN produce one research episode and one insufficient-cash
event. A 12:07 accepted observation remains episode #1 if the first position is
OPEN; it becomes episode #2 only after CLOSE and an observed false setup.
These are synthetic regression scenarios, not reconstructed October 1 trades.

On the VM, run the read-only audit:

```bash
cd /home/ubuntu/easystock
.venv/bin/python3 deploy/audit_research_replay.py --day 2026-10-01 --symbol 3189
```

Exit code 2 and `cannot_reconstruct_without_lookahead` mean necessary evidence
is missing. Sparse five-minute samples, minute-bar extremes and accepted-model
logs cannot establish exact tick exit order, technical exit timing or setup
re-arm. The default audit reports persisted identities or safely counted
symbol-matched journal/log markers; it prints no raw secret-bearing logs.

`--evidence <file.json>` supports an explicitly complete, chronologically ordered
captured timeline. Required coverage flags are `complete_ticks`,
`complete_predicates`, `complete_technical_decisions`. Events use `kind`,
`symbol`, and timezone-aware `at`: ticks contain `price`; strategy events contain
`bar_completed_at` and `result`; predicates contain all seven formal gate
booleans, fresh `quote_at`, entry `price`, and formal rule/model acceptance.
Model events require the original approved decision and threshold. The replayer
requires a completed exit, rejects future bars/out-of-order evidence, reports
input coverage as caller-attested, and never inserts history or touches cash.

## Deployment

Use `bash deploy/update_vm_main.sh`, after running jobs complete naturally.
Keep its service guards and timer restoration; do not stop/kill training or
intraday jobs to bypass them. The script backs up Git, the actual paper database,
and an existing research database, then runs the offline research/cash probe.
The probe writes exclusively to disposable fixture databases. Local credentials,
runtime data, old paper history, wallet capital and LIVE ordering flags are not
changed by this feature. No GitHub Actions workflow deploys this feature.

After deployment compare HEAD, origin/main and release-info, inspect failed
units and intraday/premarket/learning/research-cycle timers, run
`deploy/verify_research_episodes.py`, and inspect `[RESEARCH_ENTRY]`,
`[MODEL_DECISION]` and real paper events on the next trading session.
