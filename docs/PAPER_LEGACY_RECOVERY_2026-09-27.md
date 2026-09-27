# Legacy 11-feature paper research recovery

The VM's `easystock-paper-train.service` and `easystock-paper-feedback.service`
refer to `wait_daily_collectors.py` and `paper_learning_cycle.py`. These files
were present in the 2026-09-22 maintenance stage but absent from Git, causing
both units to fail before their work began. The restored sources are now tracked.

The archived research uses `paper_legacy.decisions` and the eleven-feature order
in `paper_legacy.features`. It must not replace the current
`daytrade_learning.model_runtime` gate, which expects five different features
and requires an approved, pinned model. The current intraday engine does not
write new rows into the legacy `decisions.sqlite`. Thus a successful legacy
training run can refresh a historical diagnostic but does not establish a
forward-learning loop or deploy a live entry model. Its status is
`historical_diagnostic_only`; `deployment_allowed` remains false.

Before restoring the timers, verify the complete systemd commands, the
interpreter dependencies, the number of same-day rows in `decisions.sqlite`,
and the resulting journal. Keep `easystock-intraday.timer` disabled until its
separate model-mode and guardian checks pass. The new five-feature
`easystock-research-cycle` must be assessed on its own sample and validation
requirements rather than mixing the two schemas.
