# easystock / 墨衡量化 Mohren Quant Matrix

台股量化觀察儀表板。後端使用 FinLab 取得價格、基本面、股利與法人資料，GitHub Actions 每個交易日更新 Firebase Realtime Database；前端為純 `index.html`，可部署於 GitHub Pages。

> 本專案為資料整理與量化研究用途，不構成投資建議。

## v0.50 主要修正

- Firebase 不再覆寫資料庫根目錄，只寫入 `/market_data`。
- Firebase 結構拆為 `summary` 與 `kline`；首頁只讀摘要，點個股時才下載 250 日 K 線。
- 前端保留舊版 Firebase root fallback，方便不中斷升級。
- 修正 `longTermScore` 未建立、長期專區未真正篩選、排序下拉選單未生效。
- 修正 `momo20` 顯示但未計算。
- 現金股利改為「近 365 日正現金股利紀錄加總」，殖利率使用 TTM 股利 / 最新收盤價。
- 配息連續性改為按「日曆年度」計算，最多 5 年，不再把季配/半年配每筆當成一年。
- 「盤中當沖」改名為「日線短線動能」，避免把日線代理模型誤認為即時 5/15 分 K 策略。
- 回測標示改為 `SAMPLE-IN TEST`，明確說明目前股票池選擇偏誤。
- GitHub Action 增加 Secrets 格式檢查、concurrency、timeout 與 dependency check。
- GitHub Actions 更新到 Node 24 系列的 `actions/checkout@v6`、`actions/setup-python@v6`。

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

使用者點進個股後才下載：

```text
/market_data/kline/2330.json
```

## GitHub Secrets

Repository → **Settings → Secrets and variables → Actions → New repository secret**，建立：

1. `FINLAB_API_TOKEN`
2. `FIREBASE_DATABASE_URL`
3. `FIREBASE_SERVICE_ACCOUNT_JSON`

### FIREBASE_DATABASE_URL

格式例如：

```text
https://YOUR-PROJECT-default-rtdb.firebaseio.com
```

### FIREBASE_SERVICE_ACCOUNT_JSON

請把 Firebase / Google Cloud service account JSON **整份 JSON 文字**放進 Secret，不要把私鑰檔案 commit 到 repository。

## Firebase Rules

若這是公開 GitHub Pages 儀表板，可只開放市場資料讀取；Admin SDK 使用 service account 寫入時不依賴一般 client rules：

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

如果資料不希望公開，請不要使用上述 public read 規則，需改成有登入驗證的前端架構。

## 第一次升級 v0.50

把新版檔案覆蓋回 repository 後，**另外刪除舊檔**：

```bash
git rm serviceAccountKey.json
git rm market_data.json
```

`serviceAccountKey.json` 在舊 repo 中雖不是實際金鑰 JSON，但檔名與用途錯誤，而且與新版流程重複，建議刪除。

接著：

```bash
git add .
git commit -m "Upgrade Mohren Quant Matrix to v0.50"
git push
```

然後到 GitHub → **Actions → Daily Stock Data Update → Run workflow** 手動跑一次。

第一次成功後，Firebase 會產生 `/market_data`；新版前端之後會自動使用分離式資料。第一次 Action 尚未成功前，前端會嘗試讀取舊版 root 格式。

## GitHub Pages

Repository → **Settings → Pages**：

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/ (root)`

`index.html` 放在 repository root 即可。

## 排程

`.github/workflows/update.yml`：

```yaml
- cron: "30 7 * * 1-5"
```

GitHub Actions cron 使用 UTC，因此為台灣時間週一至週五 15:30。

## 模型說明

### 均線回踩轉強

- 收盤價位於 MA20、MA60 上方
- 近 3 日低點靠近 MA20 或 MA60
- 當日紅 K
- 營收年增若有資料則要求為正
- 成交金額與法人資料參與排名

### 日線短線動能

使用日線資料：

- 開收漲幅
- 20 日量比
- 成交金額百分位
- 收盤在當日高低區間的位置

這不是即時當沖訊號，也沒有 5/15 分 K、委買委賣或逐筆成交資料。

### 強勢波段

- 接近 250 日高點
- 20 日年化 Sharpe
- MA20 / MA60 趨勢

### 穩健長期核心

目前前端預設 eligibility：

- TTM 殖利率 ≥ 4%
- ROE 若有資料需 > 0
- FCF 若有資料需 ≥ 0
- 負債率若有資料需 < 70%

排序分數另外綜合基本面、股利、穩定度與估值。門檻可在 `index.html` 的 `LONG_MIN_YIELD` 調整。

## 回測限制

目前回測是「今天熱門股票池」的近 250 日樣本內測試，因此：

- 不是完整 point-in-time universe。
- 存在股票池選擇偏誤 / survivorship-like selection bias。
- 未納入所有手續費、交易稅、滑價、漲跌停無法成交等情境。
- 日線短線策略只是一個 daily-data proxy。

如需做真正 walk-forward，必須保存每個歷史交易日當時的 universe 與當時可得的基本面資料。

## 本機檢查

```bash
python -m pip install -r requirements.txt
python -m py_compile update_market.py
```

真正執行 `update_market.py` 需要三個環境變數 Secrets。
