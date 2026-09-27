# EasyStock Roadmap

> 本文件用於記錄已確認的後續規劃。  
> 更新原則：使用者在 EasyStock 相關討論中說「紀錄」時，更新此文件，保留既有內容並整理版本脈絡。

## 目前版本：Chrome Extension 1.01

### 目標
- 先讓 1.01 經歷實際開盤。
- 優先觀察與修正實盤 BUG。
- 暫時不加入大型架構變更，避免在尚未完成開盤驗證前增加變數。

### 優先驗證項目
- 盤中掃描是否正常。
- 當沖 / 隔日沖資料是否正確更新。
- Chrome 通知是否正常觸發。
- 股票資料更新時間與首次出現時間是否正確。
- VM / Firebase / API / Chrome Extension 間資料同步是否穩定。
- 開盤時可能出現的效能、延遲與例外狀況。

---

## Chrome Extension 1.02 規劃

### Google 登入
- 加入 Google 登入。
- 使用 Firebase Authentication。
- 優先沿用現有 EasyStock Firebase Project，不另外建立一套獨立後端。

### 自選股雲端同步
登入後同步以下資料：
- 自選股。
- 當沖監控股。
- 個股提醒條件。
- 股票群組。
- 使用者相關設定。

「最近查看」可保留在 Chrome 本機，不一定需要雲端同步。

### 既有本機資料 Migration
第一次 Google 登入時，必須保護既有使用者已儲存的股票。

核心原則：

**只合併、不覆蓋、不刪除。**

流程：
1. 讀取 Chrome 原有本機儲存資料。
2. Google 登入成功後取得 Firebase UID。
3. 檢查雲端既有資料。
4. 本機與雲端資料做 Union 合併。
5. 合併結果寫回 Firebase。
6. 合併結果同步回本機。
7. 保留本機資料作為離線與故障備援。

若每檔股票包含提醒條件、監控設定等資料，Migration 必須整包同步，不只搬股票代號。

建議保留來源資訊，例如：
- source: local_migration
- createdAt
- updatedAt

### Firebase 建議結構

```text
users/
  {uid}/
    profile/
    watchlist/
    alerts/
    groups/
    settings/
```

Security Rules 必須限制：

```text
auth.uid == {uid}
```

確保每位使用者只能讀寫自己的資料。

### 同步狀態 UI
登入後可顯示：
- Google 帳號狀態。
- 已同步股票數量。
- 最後同步時間。
- 雲端同步成功 / 失敗狀態。

---

## GitHub / 模型核心保護規劃

目前先不動 1.01，下一次較大改版再處理。

### 已確認風險
目前 public repository 中已有相當完整的策略與模型相關程式，例如：
- strategy_engine.py
- strategy_rules.py
- scan_intraday.py
- daytrade_learning/
- learning_eod.py
- premarket_ai.py
- vm_runtime/

這些內容可讓懂 Python / 量化交易的人分析：
- 特徵設計。
- 評分公式。
- 權重與門檻。
- 模型種類。
- 訓練條件。
- 停損 / 停利邏輯。
- 推論流程。

目前未發現 main branch 中有明顯硬編碼的 API Key、Firebase 私鑰、Fugle Key、Shioaji Secret 或 LINE Token；敏感憑證應持續只放在環境變數或 GitHub Secrets。

### 未來目標架構

```text
Public easystock repo
  ├─ Website
  ├─ Chrome Extension
  ├─ UI
  └─ API client
          │
          ▼
Private Core / VM
  ├─ strategy_engine
  ├─ strategy_rules
  ├─ daytrade_learning
  ├─ training
  ├─ model files
  ├─ feature engineering
  ├─ scoring
  ├─ threshold
  ├─ intraday engine
  └─ private backend
```

### Public Repo 保留
- index.html
- privacy.html
- 靜態 assets
- Chrome Extension UI
- API 呼叫程式
- 公開設定

### 應移出 Public Repo
- strategy_engine.py
- strategy_rules.py
- daytrade_learning/
- learning_eod.py
- 訓練程式
- 模型檔
- 特徵工程
- 模型權重
- 門檻
- 進出場核心邏輯
- 私有 Firebase backend
- VM runtime 核心
- Gemini 策略 Prompt
- API / broker 私有整合邏輯

### GitHub 重構原則
不要只做 `git rm`，因為舊 commit 仍可能保留核心程式。

較安全的規劃：
1. 將完整核心建立為 Private repository。
2. 確認 VM 可由 Private Core 正常部署。
3. 重新建立乾淨 Git history 的 Public easystock。
4. Public repo 只保留網站與 Chrome 前端。
5. 驗證 jimmyeyes.com/easystock 正常。
6. 再移除舊 public 架構。

### Chrome Extension 去 GitHub 關聯
未來移除直接指向：

```text
raw.githubusercontent.com/jimmyeyes03160729/easystock/...
```

改成例如：

```text
https://jimmyeyes.com/easystock/config.json
```

或：

```text
https://api.jimmyeyes.com/config
```

降低由 Extension 直接反查 GitHub repository 的線索。

### API 對外原則
對前端只回傳結果，不暴露模型配方。

可公開：

```json
{
  "symbol": "2330",
  "signal": "WATCH",
  "score": 82
}
```

避免公開：
- feature values
- weights
- threshold
- model coefficients
- training metadata
- private scoring breakdown

---

## Roadmap 更新規則

使用者在 EasyStock 相關對話中輸入「紀錄」時：
1. 讀取 `docs/ROADMAP.md`。
2. 把本次已確認的規劃整合進文件。
3. 保留既有內容，不重複堆疊。
4. 依版本與主題整理。
5. 不因「紀錄」而修改正式功能程式碼。
6. 不影響目前正式版本，除非使用者另行要求。
