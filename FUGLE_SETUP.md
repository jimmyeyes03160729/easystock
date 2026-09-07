# EasyStock v0.63 — Fugle 歷史 K 線補檔

## 1. GitHub Secret

到 Repository → Settings → Secrets and variables → Actions → New repository secret：

- Name: `FUGLE_API_KEY`
- Secret: 貼上你的 Fugle API Key

不要把 Key 放進 `index.html`、Python 程式、README 或 commit。

## 2. 上傳檔案

把本包完整覆蓋到 repository；最重要的新檔案：

- `backfill_fugle.py`
- `.github/workflows/backfill-fugle-history.yml`

平常每日更新仍使用：

- `.github/workflows/update.yml`

## 3. 先跑一次歷史補檔

GitHub → Actions → **Historical K-line Backfill (Fugle)** → Run workflow

行為：

- 從 Firebase `/market_data/summary` 取得最多 500 檔熱門股票。
- 已有至少 220 根 K 線的股票直接跳過。
- 其餘使用 Fugle `historical/candles/{symbol}` 抓近一年日 K，最多保存 250 根。
- 每補完一檔立即寫 Firebase，所以中途停止後可安全重跑。
- 補檔後自動再跑一次 `update_market.py`，重新計算技術指標與分數。

## 4. 日後每天

`Daily Stock Data Update` 仍由 TWSE + TPEx 提供每天的新資料，只追加一根 K 線。
Fugle 只會在新進股票歷史不足時做少量 bootstrap；v0.63 每次最多 5 檔，避免拖慢每日 workflow。

## 5. 為什麼使用 adjusted=false

歷史補檔使用未還原股價，因為每日 TWSE/TPEx append 的也是實際未還原 OHLC。
兩者一致可避免除權息前後把「還原價」與「實際價」混在同一條曲線。
