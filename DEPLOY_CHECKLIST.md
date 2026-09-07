# v1.0 正式版部署檢查

1. 覆蓋整包檔案到 repository。
2. 確認 GitHub Secrets：`FIREBASE_DATABASE_URL`、`FIREBASE_SERVICE_ACCOUNT_JSON`、`FUGLE_API_KEY`。
3. 先執行 `Historical Research Backfill (Fugle)`：建議 `years=3`、`max_symbols=500`。
4. Backfill 成功後執行 `Daily Stock Data Update`。
5. 確認 log 最後有 Firebase 分批寫入完成訊息，沒有單次 request size error。
6. 開 GitHub Pages 後確認：市場燈號、今日 TOP 3、短波段、長期核心、模型可信度皆有資料。
7. 若短線回測成本後為負或 Profit Factor <= 1，首頁顯示「研究中」是預期行為。
8. 測試 50 / 100 / 200 以下、自訂價格與單張預算是否能同步重新排序。
