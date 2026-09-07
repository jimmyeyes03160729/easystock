# v0.60 FinLab Free 部署檢查表

## 1. 覆蓋檔案

- `index.html`
- `update_market.py`
- `requirements.txt`
- `.github/workflows/update.yml`
- `.gitignore`
- `README.md`

## 2. 刪除舊檔（若還存在）

- `serviceAccountKey.json`
- `market_data.json`

## 3. GitHub Secrets

必須保留：

- `FIREBASE_DATABASE_URL`
- `FIREBASE_SERVICE_ACCOUNT_JSON`

選配：

- `FUGLE_API_KEY`

可以刪除：

- `FINLAB_API_TOKEN`

## 4. Commit / Push

```bash
git add .
git commit -m "Upgrade Mohren Quant Matrix to v0.60 FinLab Free"
git push
```

## 5. 第一次執行

GitHub → **Actions → Daily Stock Data Update → Run workflow**。

檢查 log：

- `Validate Required Secrets`：Success
- `Check Optional Fugle Secret`：有／無 Key 都可以 Success
- `Verify Dependencies and Syntax`：Success
- `Update TWSE TPEx Data to Firebase`：Success

## 6. Firebase

確認：

```text
/market_data/meta/version = 0.60
/market_data/meta/source = TWSE + TPEx
/market_data/summary
/market_data/kline
```

若從 v0.50 升級，既有 K 線應被保留並只追加最新交易日，不應整批消失。

## 7. 網站

重新整理 GitHub Pages 後確認：

- 頁首顯示 `v0.60`
- 狀態列顯示 `TWSE + TPEx`
- 上市、上櫃股票皆可出現
- 點上櫃股票時 Yahoo 連結使用 `.TWO`
- 點個股可正常載入 K 線
- 缺少 FCF 等欄位時顯示 `N/A`，不是 `0`

## 8. 若沒有 Fugle Key

這不是錯誤。

- 舊 K 線直接沿用。
- 新進股票從官方日資料開始累積。
- 歷史不足的股票暫時沒有完整 MA60 / 回測。

若想讓新進股票立即擁有歷史 K 線，再新增 `FUGLE_API_KEY`。

## v0.61 Fast 部署後檢查

- `.github/workflows/update.yml` 的 `timeout-minutes` 應為 `8`。
- env 應包含 `HTTP_TIMEOUT: "12"`、`HTTP_WORKERS: "6"`、`FUGLE_BOOTSTRAP_MAX_PER_RUN: "20"`。
- Action log 的財報階段應看到多個 `[HTTP]` 幾乎同時開始，而不是逐一等待。
- 正常情況建議目標約 1–3 分鐘；若官方 API 異常，最晚 8 分鐘由 GitHub 自動中止。
