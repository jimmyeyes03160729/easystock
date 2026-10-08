# Dashboard usability — 2026-10-08

Base: origin/main `02e542544f388ffd55bb845ac0cbaad7c29aa64d`.

## Scope

- Truthful Research / Paper labels, independent daily/live validity, source timestamps and measured browser fetch + JSON parsing duration. No exchange-latency claim or fabricated Live switch state. Failed daily reads retain the prior snapshot with an explicit warning. Invalid/future closed timestamps are rejected.
- Desktop and mobile have the same per-share price and 1000-share budget inputs. Budget is only a display filter, excluding fees/taxes; it is not Paper capital. Inverted ranges are explained; a single clear button resets price and budget.
- Empty intraday records distinguish invalid/offline snapshots, session stages, display filters, fresh backend Market Gate blocking and an explicitly unavailable model. Missing evidence remains unknown rather than inventing a reason. Previous-day records cannot overwrite an offline warning.
- Rebound empty messages distinguish published candidates hidden by the visible pool, unavailable K-lines, and no evaluable candidates. Publication/display counts are separate. Eligibility, ordering and thresholds are unchanged.
- Search is code/name matching on the loaded daily pool only. It is independent of recommendation filters, never qualifies a stock, and opens the existing detail view. A versioned local-only watchlist stores at most 100 symbols, not prices or outcomes; removed-pool symbols remain removable with no invented quote. Blocked, corrupt or quota-exceeded storage falls back to memory without overwriting corrupt data. DOM construction uses textContent; periodic live updates preserve search button focus.
- Advanced source/model metrics are collapsible; the status overview remains visible. Existing five-item mobile navigation and public/private routes are unchanged.

## Validation

- `pnpm test`: all frontend groups passed; Node runner 57 passed, including seven new dashboard UX cases. Existing rebound UI regression additionally covers published candidates hidden by filters.
- Asset JS/CSS content digests and `git diff --check` passed.
- Browser checks used `node tests/preview_dashboard.cjs`, which replaces all data fetches with synthetic responses and binds only to 127.0.0.1. No production Firebase/VM/holdout data was read.
- 360px: price/budget inputs and search available; add-to-watchlist worked and survived reload; document width 354px at viewport 360px (no horizontal overflow). 1280px: overview uses four equal columns. A legacy overview-grid class collision found during visual QA was resolved by using a separate ux-overview-grid class.
- Browser/device testing is a local synthetic preview, not live-site deployment acceptance or real phone hardware verification.

## Safety and release boundary

No strategy, backend, trading switch, account, order, risk threshold, model, training, fee calculation, research outcome or holdout changes. No DB/Firebase writes or production orders. The existing dirty primary checkout and research archives were preserved. This change is an isolated review branch; merge, GitHub Pages release and VM deployment remain separate authorization steps.
