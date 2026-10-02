# Paper daily buy limit

`daily-buy-limit-v1` replaces the cash wallet gate. The active period's BUY
fills, selected by their Asia/Taipei `trade_date`, are the source of truth:

```
daily_buy_used = sum(BUY gross)
daily_buy_remaining = max(0, daily_buy_limit - daily_buy_used)
```

BUY uses the maximum whole 1,000-share lots that fit the remaining notional.
The old 80% allocation cap is removed. Fees and taxes do not consume this
limit. SELL does not replenish it. New dates start at zero usage through the
date query; there is no reset job or mutable usage counter. Existing overnight
position guards, entry/exit policies and research episode re-arm rules remain.
Owner changes to the limit retain that day's fills and existing positions.

Both the usage query and BUY insert run in one `BEGIN IMMEDIATE` transaction.
A Research episode supplies an execution ID; successful BUY receipts are
persisted in the same transaction and make retries idempotent even after SELL.
SELL retains its existing position identity and settlement receipt guards.

Performance is independent. `realized_pnl` in daily metrics means the realized
price gain before costs. Daily `net_pnl` subtracts all that day's buy/sell fees
and tax, including BUY fees for still-open positions (the final summary waits
until positions close). The trade return is net PnL / BUY notional used, or null
when usage is zero. Limit utilization is shown separately as used / limit.
Equity is performance base + cumulative realized net PnL - open BUY fees + the
preserved legacy performance adjustment; it does not include unrealized price
changes and never controls future trading limits.

Migration adds columns without rebuilding tables. The first limit and
performance base come from `initial_capital`, never `current_capital`. Old cash
plus original open-position cost is used once to preserve legacy performance
that might not be represented in fills. Migration records this adjustment and
its semantics version; subsequent migrations do not reset configuration or
recalculate it. Old fills, logs, positions, events and Research history are not
rewritten. Existing cash-era period rows are left unchanged. New periods store
their limit, performance base and semantics version explicitly.

Legacy `initial_capital` / `current_capital` remain frozen compatibility data.
New fills have `buy_limit_remaining_after` and `semantics_version`; their
NOT NULL `cash_after` slot duplicates remaining quota only for schema
compatibility. New APIs never expose it as cash. Old log balance columns retain
history; new rows use them for performance equity, and the API labels them
`equity_start` / `equity_end`. Old logs without recorded quota show an explicit
missing-quota marker. Unreconciled legacy positions without matching ledger
metadata require manual reconciliation; migration never fabricates fills.

The authenticated, CSRF-protected `/admin/paper-trade/start` accepts only
`{"daily_buy_limit": 1000000}`. It changes the limit and resumes Paper without
resetting usage, performance base or history. The old cash payload is rejected
with a validation error. Research is created before Paper execution; an
unaffordable 3189 lot remains tracked with
`paper_skip_reason=daily_buy_limit_exceeded`. Historical `insufficient_cash`
reasons remain intact and are counted separately.

## Safe deployment

Use `bash deploy/update_vm_main.sh`. It keeps the existing active-job guards,
backs up the wallet, validates a temporary migrated copy, and invokes the
explicit migration only after offline tests pass. Migration makes another
timestamped SQLite backup and reports integrity checks, row counts and hashes
of original fields before and after. Never kill a running job to bypass guards.

To check migration alone without changing the source:

```bash
.venv/bin/python3 deploy/migrate_paper_daily_limit.py
```

`--apply` is the explicit backed-up mutation. The Research deployment smoke
test uses disposable fixtures only. The existing market-data installer reloads
the active admin web service to load updated API handlers; refresh the browser. No
broker ordering code, model threshold, radar or market gates are changed.
