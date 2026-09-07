# 墨衡量化 Mohren Quant Matrix v0.40

這版保留你的核心架構：

FinLab
→ GitHub Actions（每日一次）
→ Firebase Realtime Database
→ GitHub Pages / `index.html`

前端完全不連 FinLab。

## 這次主要修正

1. Firebase 與 GitHub Actions 的資料流統一。
2. 不再產生任何模擬殖利率、假 PE、假營收成長率。
3. 缺資料一律使用 `null`，前端顯示 N/A。
4. 熱門500改成「最新成交金額排名前500檔」。
5. 加入成交量、成交金額、量比與日內區間位置，重做當沖分數。
6. Sharpe20 改成「20日年化風險調整報酬」口徑。
7. 「觸底反彈」改名為「均線回踩轉強」。
8. 長期核心加入 ROE、EPS、營收YoY、FCF、負債率、股利連續性等資料；高股息只接受真實股利。
9. 加入個股四維模型分數與資料完整度。
10. 加入250日資料的樣本內回測。
11. 當沖回測標示為「日線代理」，避免把日K假裝成盤中真實回測。

## GitHub Secrets

GitHub Repository → Settings → Secrets and variables → Actions → New repository secret

建立三個：

### FINLAB_API_TOKEN
你的 FinLab API Token。

### FIREBASE_DATABASE_URL
```text
https://money-7c81c-default-rtdb.firebaseio.com
```

### FIREBASE_SERVICE_ACCOUNT_JSON
Firebase Console / Google Cloud 建立的 Service Account JSON，**把整份 JSON 原文貼進 Secret**。

不要再把 `serviceAccountKey.json` 提交到 GitHub。

## Firebase Rules

把 `firebase.rules.json` 套用到 Realtime Database。

前端只讀：

- `/stocks`
- `/metadata`
- `/backtests`
- `/updated_at`
- `/universe`
- `/source`

寫入權限只留在 Admin SDK / GitHub Actions。

## 首次切換

1. 從 GitHub repo 刪除 `serviceAccountKey.json`。
2. 如果那個檔案曾經放過真正的私鑰，建議到 Google Cloud / Firebase 將該 Service Account 的舊金鑰撤銷並重新建立。
3. 在 GitHub Secrets 建立三個 secrets。
4. 將新的 `update_market.py`、`index.html`、workflow、requirements、rules 上傳。
5. 手動執行 GitHub Actions。
6. 確認 Firebase `/stocks` 有約500檔。
7. GitHub Pages 開啟網站確認前端讀取成功。

## FinLab 流量說明

這個架構可以避免「網站每一個訪客都直接呼叫 FinLab」。

但是 `data.get()` 本身仍可能下載某個資料表的完整矩陣，再由 Python 取最後一天。因此這版已經把「前端重複打 FinLab」問題解掉，也只載入模型真正需要的資料表；但不能把 FinLab 的 `data.get()` 假定成「只傳一列資料」。

後續若要再壓低 FinLab 流量，可以再把每日更新拆成更細的資料表／日期增量策略。

## 回測限制

目前 Firebase 每檔保留250日K線。

- 均線回踩：訊號日收盤後，下一交易日開盤進場，固定10日出場。
- 強勢波段：訊號日收盤後，下一交易日開盤進場，固定10日出場。
- 當沖代理：前一日收盤訊號，隔日開盤進、隔日收盤出。

回測沒有直接使用未來資料做當日訊號；但仍屬樣本內回測，且未納入完整交易成本、滑價與漲跌停無法成交等市場微結構。

真正的5/15分鐘當沖模型需要盤中級資料。
