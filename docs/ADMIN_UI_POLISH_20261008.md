# Admin UI polish — 2026-10-08

## Scope

- Remove Gemini/OpenAI cards from the authenticated provider-health renderer. Backend provider collection, credentials and Guardian AI review remain unchanged. Shioaji, E.SUN, Fugle, Firebase and the market-gate diagnostics remain available.
- Present E.SUN market diagnostics as four summary tiles and five sector cards. Display signed percentage/percentage-point values with two decimal places, source ranks without reordering, Chinese state labels and Taipei-local timestamps.
- Move manual Shioaji quick-quantity buttons below the quantity input. Both desktop label rows have the same height; both inputs are 48 px high. At mobile widths the form stacks without horizontal overflow. Existing IDs, quantity limits, order handlers and verification are unchanged.

Missing, invalid or stale market values remain `—`/待確認; valid numeric zero is still zero. Snapshot coverage is the ratio of valid API-returned snapshots, not certified whole-market coverage. Price rotation is a read-only proxy, not real capital flow or a production entry/exit signal.

## Verification

- `pnpm install --frozen-lockfile --ignore-scripts`: passed without a lockfile change.
- `pnpm test`: all script groups passed, including 63 Node test cases (six new UI/mirror cases).
- `python -m pytest tests/test_market_context_diagnostics.py tests/test_admin_order_safety.py tests/test_owner_live_console.py tests/test_architecture_guardian.py -q`: 65 passed, 11 subtests passed.
- Four modified static assets are byte-identical between root Admin and `vm_runtime` mirrors. No mirror allowlist/baseline change.
- Synthetic browser QA at 1280 × 900 and 360 × 900: desktop price and quantity inputs have equal top coordinates and height; mobile inputs stack, with no horizontal overflow. Market summary uses four desktop columns/two mobile columns; sector cards use three desktop columns/one mobile column. Dark and light market themes visually inspected; desktop input alignment also verified in light mode.
- `git diff --check`: passed.

The reproducible local fixture is `node tests/preview_admin.cjs`, bound only to `127.0.0.1:8767`. Use `/?panel=market`, `/?panel=manual`, or append `&theme=light`. It uses synthetic market data, removes production scripts except the market renderer, disables action buttons, and denies all API calls except the mocked market-context read. No production session is created. Preview process and temporary browser tab are closed after QA.

## Safety and remaining acceptance

No Python backend, API route, order execution code, Owner authentication/CSRF, LIVE AUTO/KILL setting, risk gate, model, strategy, research data, Firebase, credential, ledger, timer or VM service is modified. Tests use temporary/synthetic fixtures. The existing dirty primary checkout and research archives are preserved; changes are isolated on `codex/admin-ui-polish-20261008`.

These results are local UI acceptance only. Hosted CI, merge and production VM deployment/visual acceptance are not claimed here. A production updater run and runtime verification are separate from this UI change; nothing is marked LIVE VERIFIED.
