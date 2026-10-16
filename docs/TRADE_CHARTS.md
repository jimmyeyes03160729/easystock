# Readable trade rows and same-day charts

Approved follow-up: stock name/code stack vertically, followed by exit reason and research/simulation status. Larger typography and compact columns apply to A and B1/B2/B3.

All trade dialogs default to a minute-close intraday line, with an optional five-minute candlestick view and recorded entry/exit markers. The dated public feed is `market_data/intraday_charts/YYYY-MM-DD/SYMBOL`; the old chart location is a compatibility fallback only. Wrong dates, missing or invalid bars never become invented prices. Missing minute intervals remain gaps. The chart continues through the session even when the selected trade is already closed.

`trade_chart_feed.py` projects only whitelisted OHLCV bars. During the intraday engine's next normal start, a daemon reads the existing in-memory minute book and publishes A/B traded stocks every 15 seconds, outside the bar-book lock. It performs no broker requests, orders, ledger changes, model operations, or LINE sends. Quotes older than three minutes are marked delayed. Publication timestamps are distinct from the last source minute.

`easystock-trade-charts.timer` reuses already-collected post-close bars every five minutes; it does not log in to a broker. Unchanged payloads are skipped. The one-time deployment runs this cache projection so existing closed records receive their full same-day series now. Private account/strategy fields are never included in the chart payload.

The separate chart deployment requires the intraday engine to be inactive, verifies the engine diff is exactly the display worker start/stop hook, backs up previous source, runs offline chart tests, and enables only the new cache publisher. Existing trading/learning timers and services are not restarted or reconfigured. The streaming path requires next-session live acceptance; cached real data and both front-end A/B chart views can be verified immediately.
