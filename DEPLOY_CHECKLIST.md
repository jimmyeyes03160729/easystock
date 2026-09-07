# v0.63 Fugle History 部署檢查表

- [ ] Repository Secret 已存在：`FIREBASE_DATABASE_URL`
- [ ] Repository Secret 已存在：`FIREBASE_SERVICE_ACCOUNT_JSON`
- [ ] Repository Secret 已新增：`FUGLE_API_KEY`
- [ ] 已覆蓋 `update_market.py`
- [ ] 已覆蓋 `.github/workflows/update.yml`
- [ ] 已新增 `backfill_fugle.py`
- [ ] 已新增 `.github/workflows/backfill-fugle-history.yml`
- [ ] GitHub Actions 執行 `Historical K-line Backfill (Fugle)`
- [ ] Log 最後出現 `Backfill complete`
- [ ] 網站點進個股後，可看到多日 K 線而非只有當日
- [ ] 日後只保留 `Daily Stock Data Update` 自動排程；歷史補檔為手動使用
