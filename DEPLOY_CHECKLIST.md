# easystock v0.62 History Fix

這個修補只處理「個股圖表只有當日」問題，不改每日快速更新流程。

## 上傳 2 個新檔案

- `backfill_history.py` → repo 根目錄
- `.github/workflows/backfill-history.yml` → 對應路徑

`requirements.txt` 沿用 v0.61（requests / numpy / firebase-admin）即可。

## 執行一次歷史補檔

GitHub → Actions → **Historical K-line Backfill** → Run workflow

工作會拆成 5 個 shard，每個 shard 約處理 100 檔，使用 TWSE / TPEx 官方歷史月資料，把最近約 14 個月壓縮成最多 250 根日 K。

- 每檔寫完就立即存 Firebase，因此中途失敗可重跑。
- 已有至少 220 根 K 線的股票會直接跳過。
- 不需要 FinLab。
- 不需要 Fugle API key。
- 這是一次性修復；平常的 `Daily Stock Data Update` 仍維持 v0.61 快速版。

## 完成後

重新整理 GitHub Pages，點進個股後應可看到數月到約 250 個交易日的 K 線，而不是只有當日。

若某個 shard 有少數 `[WARN]`，直接再次 Run workflow；已成功股票會被跳過，只補剩下的。
