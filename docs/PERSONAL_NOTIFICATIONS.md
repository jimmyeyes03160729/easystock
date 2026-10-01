# Personal paper-trade notifications

LINE and Telegram are outbound-only personal channels. They deliver only canonical paper-account `ENTRY`, `EXIT`, and the finalized daily paper-ledger result.

- Policy: private SQLite `notification_policy`, four independent switches, safe default OFF.
- Targets: private environment files only. LINE accepts `LINE_USER_ID` or a user-shaped `LINE_TARGET_ID`; Telegram accepts a positive `TELEGRAM_CHAT_ID` or `TELEGRAM_USER_ID`.
- No fallback exists for `LINE_GROUP_ID` or `TELEGRAM_GROUP_ID`.
- LINE callbacks validate the channel signature and return `200` without commands, replies, queries, or cards.
- Telegram polling, stock-query bots, group management, chart-card generation, premarket messaging, and Guardian messaging are retired.
- Old production tables are intentionally retained as inactive data; migration never drops them.
- Delivery receipts deduplicate each channel/event. LINE uses `X-Line-Retry-Key`; ambiguous Telegram timeouts are not retried.
- LINE quota is queried server-side and cached for ten minutes; credentials and target IDs are never returned by admin APIs.
