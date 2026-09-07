# v1.1 部署檢查

1. 覆蓋 `index.html`、`update_market.py`，新增 `scan_intraday.py`。
2. 新增 `.github/workflows/intraday-picks.yml`。
3. 確認 GitHub Actions Secrets：
   - `FIREBASE_DATABASE_URL`
   - `FIREBASE_SERVICE_ACCOUNT_JSON`
   - `FUGLE_API_KEY`
4. 先手動執行 `Daily Stock Data Update`，確認 `/market_data/summary` 正常。
5. 再手動執行 `Intraday & Overnight Picks`，確認 log 最後出現 `wrote /market_data/intraday_picks`。
6. Firebase 應新增 `/market_data/intraday_picks`。
7. GitHub Pages 重新部署後，首頁應出現「當沖 TOP 3」與「隔日衝 TOP 3」，且不再出現「模型可信度」。
8. 盤中如果沒有股票通過門檻，顯示「今日不硬推」屬正常結果。
