# LINE controls and resumable historical research

## Homepage

The rebound module retains its “experimental / not a win probability” and
fundamental-data warnings. Each card shows identity, price and qualification;
support/resistance, invalidation, reward/risk and provenance are collapsed.
The unqualified technical watchlist is collapsed independently and is never
presented as the recommended TOP 3. No fixed-height clipping hides information.

## LINE delivery and cost

`line_stock_bot.py` validates the webhook HMAC before recording a conversation.
Owner-only management commands retain their existing authorization checks and
remain available for recovery. All other commands, including the paper game,
pass through the conversation reply policy before any chart/API work.
`P大盤` → stock command/cache → `line_bot.reply_messages` → `/message/reply`.
No fallback to paid push is added to command replies.

LINE's [pricing](https://developers.line.biz/en/docs/messaging-api/pricing/)
excludes Reply API messages. VM networking and upstream market-data quotas
are separate. [Group push pricing](https://developers.line.biz/en/faq/) is
per recipient: one request to seven people counts as seven, even if it contains
several message bubbles. Fewer groups does not imply one billable message.
Keeping immediate entry/exit messages therefore cannot guarantee a 200-message
monthly allowance will last the whole month. No plan upgrade is performed.

Private SQLite tables `line_policy` and `line_conversations` hold global reply,
group reply, private reply, trade push, other push and per-conversation switches.
They never contain message bodies or reply tokens. Raw LINE identifiers stay
server-side; the authenticated admin UI receives opaque keys and editable names.
New conversations allow free replies but default to **no paid push**. Repeated
webhooks update last-seen metadata without resetting switches. Firebase group
registration likewise preserves an existing `active: false` flag.

The deployed preference is entry/exit push enabled for the confirmed group,
all other push disabled, command replies enabled. `intraday_live.py` gates both
group and fallback destinations as trade messages; premarket, summary and generic
push paths use the “other” policy. Disabled destinations never fall back to an
unrelated destination. Missing/corrupt policy storage suppresses paid sends.
This changes delivery only, not signal generation or open-position management.

Admin `/admin/line-policy`, `/admin/line-conversations/<opaque-key>` and
`/admin/line-usage` require existing Google-owner sessions. Writes require exact
Origin, CSRF and an optimistic version, with audit entries. Usage is read on
demand (six refreshes per minute maximum), not by a background poll. Owner
identity moves from a source-code constant into private `ADMIN_OWNER_EMAIL`;
the existing pinned Google subject and sessions remain intact.

## History boundaries and scheduling

The former plan was 55 symbols × 120 observed dates = 6,600 **stock-days**, not
6,600 ticks. Its manual background loop stopped after 40 batches. The new
`vm_runtime/history/daily_history.py` reuses the existing archive and partial
responses, then extends the observed 0050 trading calendar backwards in windows
of no more than 30 calendar days. Each extension atomically updates the plan;
the original 55-symbol universe is preserved, not silently expanded to all stocks.

[Shioaji historical coverage](https://sinotrade.github.io/zh/tutor/market_data/historical/)
begins **2020-03-02** for stocks/indexes. The requested 2010 start remains recorded
as a gap; no requests before the documented boundary, fabricated bars, or
“2010 complete” claims are made. A separate licensed source would be needed for
earlier tick/minute data. Current-universe survivorship bias, pre-listing periods,
missing minutes, and indicative quote limitations remain visible.

- `easystock-history-download.timer`: daily 14:00 Asia/Taipei; boot catch-up.
- Download window: 14:00–22:00 every day, including weekends, subject to real
  quota availability. Persistent timer catches a missed schedule after downtime.
- Unexpected process/login failures: systemd retries after 15 minutes within
  that window. Locks exclude the original collector and new training wrapper.
- One logged-in Shioaji session per process; three seconds between historical
  requests; at least 120 MiB remaining quota and 5 GiB free disk before requests.
- Quota or disk shortage stops cleanly and waits for the next daily run. Quota
  does not reset merely at midnight: the [official rule](https://sinotrade.github.io/zh/tutor/limit/)
  is 08:00 on market-opening days. Existing shared usage is checked each time.
- Each valid ticks/kbars response is cached immediately. After interruption,
  completed components are reused. Final archives are validated and atomically
  written before redundant partial files are removed.
- Failed stock-days retry after 1, 2, 4, then at most 7 days. Transient connection
  failures remain retryable; repeated structurally invalid data needs review after
  three attempts. Failure records are retained, not called successful coverage.
- `auto-stop.request` remains an explicit pause and is never silently removed.
- `easystock-history-train.timer`: 22:10; boot catch-up when outside daytime.
  Only changed archives run the existing cached offline pilot; completion does
  **not** deploy a model, create real trades, or inflate daily learning counts.

Training uses the existing `/home/ubuntu/easystock-history-pilot-r1/pilot.py`
and `/home/ubuntu/easystock-learning-venv`. Those previously installed pilot
dependencies are not copied or replaced by this change. The training wrapper
uses file metadata to detect additions/changes; the pilot itself hashes and
validates its frozen sources before training. Historical progress has a moving
target as more calendar dates are discovered. Full availability is not promised.

## Verification and deployment

New tests cover policy defaults, per-source isolation, persistence, CSRF/Origin,
masked identifiers, fail-closed paid delivery, safe DOM labels, quota display,
daily time boundaries, 30-day windows, source boundary, quota gates, retry
backoff, and reuse of a ticks response after a simulated disconnect.

`deploy/install_line_history.py` is a one-time VM migration, not CI deployment.
It verifies each affected production file against the original
`vm_runtime/source-manifest.json`, takes source/config/SQLite/plan backups,
preserves owner identity, installs reviewed sources and enables the timers.
The original manifest remains an original capture record, not a claim that
modified sources still match those hashes. The selected group is supplied as
a non-public environment parameter after webhook confirmation.

Rollback: stop/disable the two new timers and their services, restore affected
source files and `reviewed_engine.json` from the recorded backup, remove the
history-status override, reload systemd and restart the LINE service. Do not
delete downloaded data or restore an old archive plan blindly: newer raw
stock-days may already exist. The added SQLite tables are backward compatible;
do not overwrite newer admin settings/sessions with an old database snapshot.
