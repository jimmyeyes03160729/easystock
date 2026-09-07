# v0.50 部署檢查表

1. 覆蓋：`index.html`
2. 覆蓋：`update_market.py`
3. 覆蓋：`.github/workflows/update.yml`
4. 覆蓋：`.gitignore`
5. 覆蓋：`README.md`
6. 保留/覆蓋：`requirements.txt`
7. 刪除：`serviceAccountKey.json`
8. 刪除：`market_data.json`
9. GitHub Secrets 確認三個值均存在：
   - `FINLAB_API_TOKEN`
   - `FIREBASE_DATABASE_URL`
   - `FIREBASE_SERVICE_ACCOUNT_JSON`
10. GitHub Actions 手動 `Run workflow`
11. 確認 Firebase 出現 `/market_data/meta`、`summary`、`kline`
12. 開啟 GitHub Pages，確認頁首顯示「摘要/K線分離」
13. 點任一股票，確認 K 線可正常載入

如果 Action 失敗，先看 `Validate Secrets`；它會指出缺哪個 Secret 或 JSON 格式錯誤，但不會輸出 Secret 內容。
