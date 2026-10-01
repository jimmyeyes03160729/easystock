# Model gate and Shioaji timestamp correction

The current engine already uses rule eligibility only in `rules` mode. In
`model` mode, low rule scores can reach an approved model, while strategy vetoes,
quote freshness, market risk, account limits and the model threshold still apply.
`eligible=False` in a strategy log is therefore not evidence of a blocked model.

`[MODEL_DECISION]` now records evaluation before rejection, including rule
eligibility, model readiness, feature evaluation, score, threshold and reason.
`[ENTRY_DECISION]` remains evidence of an actual filled paper entry.

Numeric Shioaji snapshot timestamps use the exchange-local clock convention
already used by the repository's Shioaji Kbar adapter: decode the numeric clock
and attach Taipei once. Other providers retain Unix epoch semantics. ISO and
datetime values retain their explicit timezone, or attach Taipei when naive.
No freshness allowance is relaxed and no eight-hour correction is guessed from
the current time. Production acceptance must compare a real Shioaji snapshot
with the exchange clock; offline fixtures cannot establish an SDK's live output.

## Offline checks

From the checkout with its virtual environment active:

```bash
PYTHONPATH=. python tests/test_market_risk_gate.py
python vm_runtime/tests/test_runtime_safety.py
PYTHONPATH=. python -m pytest -q tests/test_provider_health.py
pnpm test
```

Run root provider tests and VM tests in separate processes: the VM suite inserts
its own source directory on `sys.path`, and collecting both together can resolve
the root admin tests against the VM admin implementation.

## VM acceptance

This change does not prove the Oracle VM has been updated. Before deploying,
check the running service's working directory and entrypoint, record its current
commit and active state, and preserve local changes and runtime data. Use the
existing deployment process with backups; do not overwrite `.env`, SQLite,
approved models, credentials or service configuration to install this fix.

After updating the selected runtime source, run the offline checks above and
`deploy/verify_intraday_runtime.py`, then restart only the previously active
intraday service. Compare its deployed source commit to GitHub main.
Verify a real Shioaji snapshot reports Taipei exchange time without an eight-hour
shift and is rejected if stale or future-dated. During the entry window, confirm
`mode=model` and inspect `[MODEL_DECISION]` for candidates with low rule scores
and no veto. A rejected model or zero entries is not a failed deployment by itself.
