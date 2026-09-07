# easystock / 墨衡量化 Mohren Quant Matrix

台股量化觀察儀表板。v0.60 起 **完全移除 FinLab API 與 `finlab` Python 套件**，資料核心改為 TWSE（臺灣證券交易所）與 TPEx（證券櫃檯買賣中心）官方公開 API；Fugle 只作為選配的歷史 K 線初始化／缺口補齊來源。

> 本專案為資料整理與量化研究用途，不構成投資建議。

## v0.60：FinLab Free

主要變更：

- 移除 `FINLAB_API_TOKEN`、`finlab` 套件與所有 `data.get()`。
- TWSE + TPEx 官方資料負責：
  - 當日 OHLCV / 成交金額
  - PE / PB / 官方殖利率
  - 月營收 YoY
  - 股利分派
  - 財務報表
  - 外資 + 投信每日買賣超
- 既有 Firebase K 線會沿用，每天只追加最新官方日 K。
- `FUGLE_API_KEY` 改為 **選配**：只有某檔股票歷史 K 線不足時才查 Fugle。
- 15 日法人資料改為「每日官方資料持續累積」，不再每天下載整段歷史矩陣。
- 基本面官方欄位缺失時，不再硬補 `0`；前端依「實際可得因子」重新加權。
- 為不中斷 v0.50 → v0.60 遷移，近期舊基本面可暫時 fallback，預設最多 120 天，之後自動失效。
- 修正上櫃股票 Yahoo 連結：TPEx 使用 `.TWO`。
- 股票池預設排除 `0` 開頭 ETF / ETN，聚焦四位數普通股。

## 資料來源

### TWSE 官方 OpenAPI

Base URL：

```text
https://openapi.twse.com.tw/v1
```

核心 endpoints：

```text
/exchangeReport/STOCK_DAY_ALL
/exchangeReport/BWIBBU_ALL
/opendata/t187ap03_L
/opendata/t187ap05_L
/opendata/t187ap45_L
/opendata/t187ap06_L_*
/opendata/t187ap07_L_*
```

上市法人：

```text
https://www.twse.com.tw/rwd/zh/fund/T86
```

### TPEx 官方 OpenAPI

Base URL：

```text
https://www.tpex.org.tw/openapi/v1
```

核心 endpoints：

```text
/tpex_mainboard_daily_close_quotes
/tpex_mainboard_peratio_analysis
/tpex_3insti_daily_trading
/mopsfin_t187ap03_O
/mopsfin_t187ap05_O
/mopsfin_t187ap39_O
/mopsfin_t187ap06_O_*
/mopsfin_t187ap07_O_*
```

### Fugle（選配）

只有歷史 K 線不足時才使用：

```text
https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}
```

如果不設定 `FUGLE_API_KEY`：

- v0.50 已存在的 Firebase K 線照常沿用。
- 新進熱門股票從當天開始累積官方日 K。
- 在累積滿足技術指標所需天數前，部分 MA / Sharpe / 回測會顯示 N/A。

## Firebase 資料結構

```text
market_data/
  meta/
  backtests/
  summary/
    2330/
    2317/
    ...
  kline/
    2330/
    2317/
    ...
```

首頁只下載：

```text
/market_data/meta.json
/market_data/backtests.json
/market_data/summary.json
```

點進個股才下載：

```text
/market_data/kline/2330.json
```

## GitHub Secrets

Repository → **Settings → Secrets and variables → Actions**。

### 必要

1. `FIREBASE_DATABASE_URL`
2. `FIREBASE_SERVICE_ACCOUNT_JSON`

### 選配

3. `FUGLE_API_KEY`

### v0.60 可以刪除

```text
FINLAB_API_TOKEN
```

`FIREBASE_DATABASE_URL` 格式例如：

```text
https://YOUR-PROJECT-default-rtdb.firebaseio.com
```

`FIREBASE_SERVICE_ACCOUNT_JSON` 請放「整份 service account JSON 文字」進 Secret；不要把私鑰 JSON commit 到 repo。

## Firebase Rules

若 GitHub Pages 是公開儀表板，可只允許市場資料公開讀取：

```json
{
  "rules": {
    "market_data": {
      ".read": true,
      ".write": false
    }
  }
}
```

Admin SDK 使用 service account 寫入，不依賴一般前端 client write rules。

## v0.50 → v0.60 升級

把新版檔案覆蓋 repository：

```text
index.html
update_market.py
requirements.txt
.github/workflows/update.yml
.gitignore
README.md
```

如果舊 repo 還有以下檔案，刪除：

```bash
git rm serviceAccountKey.json
git rm market_data.json
```

接著：

```bash
git add .
git commit -m "Upgrade Mohren Quant Matrix to v0.60 FinLab Free"
git push
```

到 GitHub → **Actions → Daily Stock Data Update → Run workflow** 手動跑一次。

### 第一次 v0.60 Action 的預期行為

1. 先讀取現有 `/market_data`。
2. 抓 TWSE / TPEx 最新官方資料。
3. 沿用既有 K 線，對同一天資料去重後追加最新日 K。
4. 若某檔歷史少於 60 日且有 `FUGLE_API_KEY`，才向 Fugle補歷史。
5. 重新寫回 `/market_data`。

因此從 v0.50 升級時，不需要重新下載 500 × 250 根 K 線。

## GitHub Pages

Repository → **Settings → Pages**：

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/ (root)`

## 排程

```yaml
- cron: "30 7 * * 1-5"
```

GitHub Actions cron 使用 UTC，等於台灣時間週一至週五 15:30。

## 指標與資料限制

### 法人 15 日

v0.60 不再向第三方一次抓 15 日歷史，而是每天將 TWSE / TPEx 當日外資 + 投信買賣超追加到 Firebase。

- v0.50 升級：會沿用既有 `institution_history`。
- 全新安裝：從第一天開始累積，最多保留 15 筆交易日資料。

### ROE

官方 OpenAPI 財報為累計申報資料，本專案以：

```text
最新累計歸屬母公司淨利 × 年化係數 / 期末權益
```

作為近似 ROE。它不是使用平均股東權益的完整會計版 ROE，因此頁面應視為量化篩選指標，不應當成財報網站的精確 ROE 定義。

### FCF

TWSE / TPEx OpenAPI 在目前使用的端點中沒有與 FinLab `自由現金流量` 一模一樣、可穩定跨產業直接取得的欄位。因此：

- 遷移初期可沿用 v0.50 近期值，最多 120 天。
- 過期後沒有可靠官方值就顯示 N/A。
- 前端 v0.60 會按可得基本面重新加權，不會把缺 FCF 當成 0 分。

### 股利

- 現金股利從官方股利分派資料中的「元/股」現金項目加總。
- 近 365 日有董事會分派日期時，依日期計算 TTM。
- 沒有可用日期時，以最近股利年度加總作 fallback。
- 官方每日估值 endpoint 的殖利率保留為 `exchange_yield_pct`，當自行計算 TTM 缺失時可作 fallback。

### 回測 / v0.70 Research Validation

v0.70 將舊的 250D SAMPLE-IN TEST 升級為研究用途的 rolling-forward 驗證。

主要變更：

- Fugle 一次性補 3 年或 5 年日 K，研究資料保存在 `/market_data/history/{symbol}`。
- 瀏覽器個股圖仍只讀最近 250 根 `/market_data/kline/{symbol}`，不會一次下載 3–5 年。
- 主要驗證窗預設為最後 252 個交易日；每個訊號只使用訊號日以前的價格與成交量資料。
- 同一檔股票在持有期間不重複建立新交易，降低重疊樣本膨脹。
- 預設每筆交易扣除 70 bps（0.70%）研究用總交易摩擦成本，可由 `BACKTEST_TOTAL_COST_BPS` 調整。
- 同時統計 1D / 5D / 10D / 20D 報酬、勝率、平均/中位數、Profit Factor、盈虧比、最大回撤、Sharpe、等權基準與超額報酬。
- 回測依市場模式拆分為多頭 / 盤整 / 空頭，並做歷史代理分數分層。

仍有一項重要限制：歷史股票池仍由「目前熱門股」回推，尚未建立每個歷史日期各自的 point-in-time Top 500，因此仍存在 current-universe 選擇偏誤。網站會明確標示這項限制。

#### 四個區塊建議怎麼看

| 區塊 | 建議觀察模式 | 主要持有期 | 最重要欄位 | 不適合怎麼用 |
|---|---|---:|---|---|
| 均線回踩轉強 | 多頭 / 震盪回升 | 10D | 10D 成本後報酬、中位數、Profit Factor、多頭/盤整結果 | 空頭環境硬接反彈 |
| 日線短線動能 | 研究模式 | 1D | 1D 成本後報酬、勝率、樣本數、交易成本後是否仍為正 | 當成真正 5/15 分鐘當沖訊號 |
| 強勢波段主升 | 多頭趨勢 | 10–20D | 10D/20D 超額報酬、Profit Factor、最大回撤、90+ 分層 | 只看勝率，不看盈虧比與回撤 |
| 穩健長期核心 | 基本面 / 季頻 | 3–12M | ROE、營收、估值、股利、負債、穩定度 | 用 1D/10D 日線回測判斷長期投資品質 |

判讀優先順序建議：

1. 樣本數是否足夠。
2. 成本後平均報酬與中位數是否同時為正。
3. Profit Factor 是否大於 1，盈虧比是否合理。
4. 最大回撤是否可接受。
5. 超額報酬是否優於等權基準。
6. 80–89、90+ 分層是否真的優於低分組。
7. 多頭、盤整、空頭哪一種市場模式最適合該策略。

## 本機檢查

安裝套件：

```bash
python -m pip install -r requirements.txt
```

語法與 parser 測試：

```bash
python -m py_compile update_market.py
python tests/test_parsers.py
```

真正執行：

```bash
export FIREBASE_DATABASE_URL="..."
export FIREBASE_SERVICE_ACCOUNT_JSON='...'
# optional
export FUGLE_API_KEY="..."
python update_market.py
```

## v0.61 Fast 更新

為避免單次 Daily Stock Data Update 因官方 API 延遲而拖太久：

- GitHub Actions job 最長 8 分鐘，超時自動停止。
- 單一 HTTP request timeout 由 30 秒降為 12 秒。
- TWSE / TPEx 可獨立取得的資料改為最多 6 個 worker 並行下載。
- Fugle 歷史補洞每次最多 20 檔，剩餘缺口留待下一次執行補齊。
- `concurrency.cancel-in-progress: true` 保留，新一次更新會取消同群組尚未完成的舊執行。

可透過 workflow 環境變數調整：`HTTP_TIMEOUT`、`HTTP_WORKERS`、`FUGLE_BOOTSTRAP_MAX_PER_RUN`。

## v0.63 — Fugle History Backfill

新增一次性、可續跑的 Fugle 歷史 K 線補檔：

- Secret：`FUGLE_API_KEY`
- Workflow：`Historical K-line Backfill (Fugle)`
- 最多補 500 檔，每檔保存最近 250 根日 K。
- 已有 220 根以上直接跳過，因此可安全重跑。
- 每補完一檔立即寫 Firebase；中途停止不會前功盡棄。
- 補檔完成後自動刷新一次量化分數。
- Daily workflow 的 Fugle bootstrap 限制為每次最多 5 檔，維持快速日常更新。

詳細步驟見 `FUGLE_SETUP.md`。


## v0.70 — Research Validation

- Fugle 歷史回填改為可選 3Y / 5Y 研究資料。
- 新增 `/history` 長歷史與 `/kline` 250 根顯示資料分離。
- 新增 rolling-forward 驗證、交易成本、持有期比較、市場模式、分數分層、benchmark / excess return。
- 前端每個策略區塊直接標示建議觀察模式與持有期。
