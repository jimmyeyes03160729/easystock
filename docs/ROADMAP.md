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

## 觸底反彈 AI 學習規劃

### 目前先決問題：統一正式策略定義
現況存在兩套不同的「觸底反彈」邏輯：
- `scan_rebound.py`：以 MA20 大幅乖離、突破昨高、紅 K、5 日反彈等條件為主。
- `assets/rebound-engine.js`：以重複支撐 / 壓力區、近期回測支撐、突破或止跌確認、ATR、風報比、失效價與目標價為主。

AI 上線前必須先統一正式定義，避免同一個「rebound」標籤混用兩套不同策略造成學習污染。

目前規劃優先以較完整的 `range-rebound` 邏輯作為正式基準，之後將核心演算法搬到 VM / Python，前端 JS 只負責顯示。

### AI 定位
第一階段不讓 AI 直接取代既有反彈規則。

採用：

```text
固定 Rebound Rule
        ↓
產生候選池
        ↓
Rebound AI 排序 / 評分
        ↓
Shadow Mode
        ↓
Web / Chrome / LINE
```

AI 的角色是第二層排序器與品質評估器，而不是一開始就自行決定哪些股票叫做「觸底反彈」。

### Dataset 收集原則
不要只保存最後有被選中的股票。

每天應保存：
- 已符合反彈規則的股票。
- 差一點符合的候選。
- 被規則淘汰但接近門檻的股票。
- 當時的完整 feature snapshot。
- 原規則是否選中。
- 原規則分數與淘汰原因。
- 訊號時間與資料版本。

目的：讓模型同時看到成功反彈與失敗 / 假反彈案例。

### 建議第一版特徵
價格與趨勢：
- distance_to_support
- distance_to_resistance
- range_position
- bias_ma20
- bias_ma60
- ma20_slope
- ma60_slope
- rebound_3d
- rebound_5d

支撐 / 壓力：
- support_touches
- resistance_touches
- support_span_days
- support_age
- net_rr
- atr_pct

K 線：
- daily_change
- candle_body
- upper_shadow
- lower_shadow
- close_position

成交與市場：
- volume_ratio
- amount_rank
- market_5d_return
- market_regime
- breadth
- institution_flow_ratio

第一版控制在約 15～25 個穩定特徵，不一開始堆過多欄位。

### Label / 成功定義
以訊號日 D0 為基準，預設 D1 開盤模擬進場，主要追蹤 10 個交易日。

結果分類：
- Target 先碰到 → `SUCCESS`
- Invalid / Stop 先碰到 → `FAIL`
- 10 日內都沒碰到 → `TIMEOUT`
- 同一根日 K 同時碰到 Target 與 Stop、無法確認先後 → `AMBIGUOUS`，第一版建議排除訓練

同時保存：
- return_5d
- return_10d
- return_20d
- MFE_10d
- MAE_10d
- days_to_target

目前 `update_market.py` 已有 1 / 5 / 10 / 20 日驗證框架，且 rebound 的主要 horizon 已是 10 日，後續應盡量沿用，不重複建立另一套口徑。

### Rebound Learning 模組
沿用現有 `daytrade_learning` 的研究架構，不重新發明一套完全不同的系統。

建議新增：

```text
rebound_learning/
├── features.py
├── collector.py
├── labels.py
├── research.py
├── model_runtime.py
├── settings.json
└── status.py
```

共用原則：
- point-in-time feature
- candidate only
- walk-forward validation
- holdout
- shadow comparison
- 不自動 promote 未驗證模型

### 模型方案
第一版同時比較：

```text
Baseline：原 Rebound Rule
Challenger A：Logistic Regression
Challenger B：HistGradientBoosting
```

比較指標至少包含：
- 訊號數
- Target 命中率
- 平均 10 日報酬
- Profit Factor
- 最大不利走勢 / Drawdown
- Calibration / Brier（若輸出機率）

AI 沒有穩定優於 Baseline，就維持 Shadow，不套用正式選股。

### 訓練與升版原則
不允許「每日新增資料 → 當日重新訓練 → 立即上線」。

建議流程：

```text
每日收集 Snapshot
      ↓
成熟後自動 Label
      ↓
定期產生 Candidate
      ↓
Walk-forward / Holdout
      ↓
Shadow
      ↓
達標後人工 / 明確規則 Approved
      ↓
Applied Model
```

資料成熟度初步規劃：
- < 60 個交易日：收集研究資料
- 60～120 個交易日：允許 Candidate
- >= 120 個交易日：正式 Walk-forward 評估
- 通過 forward shadow 才能 Applied

若歷史 K 線資料足夠，可做 Historical Bootstrap，但必須避免 future leakage、current-universe bias 與不同策略版本混用。

### UI / 對外顯示
第一階段顯示：

```text
原策略分數
AI Score
AI 狀態
支撐 / 壓力
失效價
目標價
RR
AI 觀察摘要
```

在模型尚未完成 probability calibration 前，只稱為 `AI Score`，不得直接標示成「勝率」或「成功機率」。

### Gemini 定位
Gemini 不作為主要 K 線學習模型。

Gemini 適合：
- 盤後解釋
- 市場環境摘要
- 新聞 / 事件風險
- 候選標的文字說明

核心量化學習仍以可驗證的 sklearn / Gradient Boosting 類模型為主。

### 實作順序
1. 先統一正式 Rebound 定義。
2. 建立 `rebound_learning`。
3. 儘早開始收集 Rebound snapshot，即使 AI 尚未上線。
4. 10 個交易日後自動 Label。
5. 自動產生研究 / 回測報告。
6. AI 先 Shadow，不影響目前正式結果。
7. 數據與驗證成熟後，再考慮「AI 強化反彈」正式功能。


---

## 永豐實盤當沖後台規劃

### 功能定位
新增一個完全獨立的「永豐實盤當沖」後台模組，只供 Owner 使用，不對外開放。

此模組與以下功能分離：
- 公開網站
- Chrome Extension
- 模擬當沖
- AI 學習面板

公開端不得取得任何可下單能力、券商憑證或實盤控制權。

### 後台主要區塊
建議後台導覽：

```text
EasyStock Admin

📊 系統總覽
🤖 AI 學習
🧪 模擬當沖
💰 永豐實盤當沖
   ├─ 帳戶設定
   ├─ AUTO ON / OFF
   ├─ 今日持倉
   ├─ 委託 / 成交
   ├─ 今日損益
   ├─ 歷史報表
   ├─ 損益圖表
   └─ KILL SWITCH
⚙️ 系統設定
```

### 永豐帳戶憑證持久化
第一次在後台完成：
- Shioaji API Key
- Secret Key
- CA 憑證
- CA Password
- 指定證券帳戶

驗證成功後，必須保存於 VM 私有加密儲存區。

需求：
- VM 重啟後不用重新輸入 Key。
- 程式重啟後不用重新輸入 Key。
- 關閉 Auto Trading 不刪除憑證。
- 再次開啟 Auto Trading 時，自動重新登入 Shioaji、啟用 CA 並驗證指定帳戶。
- Firebase 不保存券商 Secret。
- GitHub 不保存券商 Secret。
- Chrome Extension 永遠拿不到券商 Secret。

建議私有儲存：

```text
/home/ubuntu/easystock-private/
├── broker.enc
├── broker.key
└── cert/
    └── Sinopac.pfx
```

檔案權限至少限制為 Owner / service account 可讀。

SQLite 僅保存非敏感狀態，例如：
- broker_connected
- masked_account
- auto_trade_enabled
- auto_resume_enabled
- updated_at

### 自動交易控制
至少提供三個獨立控制：

```text
自動交易
[ ON / OFF ]

重新啟動後自動恢復
[ ON / OFF ]

緊急停止
[ KILL SWITCH ]
```

AUTO OFF：
- 禁止新的自動實盤訂單。
- 不刪除帳號、Key 或 CA 設定。
- 既有持倉仍需持續監控與明確處理。

Auto Resume ON：
VM / 服務重新啟動後：
1. 載入加密憑證。
2. 登入 Shioaji。
3. 啟用 CA。
4. 驗證 person / broker / account 是否為指定 Owner 帳戶。
5. 同步真實持倉與未完成委託。
6. 確認帳務一致。
7. 才允許恢復 AUTO READY。

KILL SWITCH：
- 立即停止新增自動委託。
- 保留操作紀錄。
- 是否同時啟動平倉流程要做成獨立且明確的安全動作，避免誤觸。

### Owner-only 與帳戶綁定
實盤模組只能使用指定的 Owner 永豐帳戶。

每次啟動必須檢查：
- person_id
- broker_id
- account_id

與後台已綁定的帳戶不一致時：
- 不允許 AUTO READY。
- 不允許送出實盤委託。
- 後台顯示明確錯誤。

### 實盤交易流程

```text
EasyStock Daytrade Signal
        ↓
Trade Gate
        ↓
風控檢查
        ↓
確認當沖資格 / 帳戶 / 可用資金
        ↓
Shioaji 下單
        ↓
Order Callback
        ↓
Deal Callback
        ↓
建立真實 Position
        ↓
即時監控
  ├─ Stop Loss
  ├─ Take Profit
  ├─ Trailing Stop
  ├─ Strategy Exit
  └─ 收盤前強制出場
        ↓
真實賣出成交
        ↓
寫入 Live Trade Ledger
```

實盤成交價必須以券商實際 Deal Callback 為準，不能以策略訊號價或原始委託價取代。

部分成交時必須累積實際成交數量與加權平均成交價。

### 真實持倉為最高權威
VM 啟動 / Shioaji 重連後必須執行 Reconcile：

```text
永豐實際委託 / 成交 / 持倉
             ↓
       本機 Live Ledger
             ↓
          比對
```

若不一致：
- AUTO PAUSED
- 禁止新增交易
- 後台顯示帳務不一致原因
- 等待人工確認或自動安全修復

不可只相信 SQLite / Firebase 的本機狀態。

### 獨立資料庫
實盤不可與 `paper_trade_*` 共用。

建議新增：
- live_trade_settings
- live_trade_orders
- live_trade_deals
- live_trade_positions
- live_trade_daily
- live_trade_events

單筆完整交易建議保存：
- trade_id
- strategy_version
- model_version
- symbol
- name
- entry_time
- entry_order_price
- entry_fill_price
- entry_shares
- exit_time
- exit_order_price
- exit_fill_price
- gross_pnl
- broker_fee
- tax
- net_pnl
- net_pnl_pct
- entry_reason
- exit_reason
- mfe
- mae
- status

### 今日交易報表
後台需有獨立實盤報表，至少顯示：

```text
時間
股票
動作
委託價
實際成交價
數量
成交金額
策略 / 模型版本
進出場原因
手續費
證交稅
毛損益
淨損益
```

今日摘要：
- 今日實現損益
- 今日報酬率
- 今日投入金額
- 交易次數
- 勝 / 負筆數
- 勝率
- 未實現損益
- 手續費
- 證交稅
- 淨損益

### 圖表
實盤報表至少提供：

1. 今日累積損益曲線
   - X 軸：時間
   - Y 軸：累積淨損益

2. 每筆交易損益圖
   - 每筆已完成交易的淨損益
   - 可快速辨識主要獲利 / 虧損來源

3. 帳戶 Equity Curve
   - 本日
   - 本週
   - 本月
   - 全部

後續可再增加：
- 勝率趨勢
- Profit Factor
- 最大回撤
- 策略別損益
- 模型版本別損益
- 時段別績效

### PAPER vs LIVE 對照
同一個正式策略訊號，保留：
- 模擬成交結果
- 真實成交結果

可比較：
- entry slippage
- exit slippage
- 手續費
- 稅
- 部分成交
- 未成交
- 延遲
- 最終 PnL 差異

用於量化「理論模型績效 vs 真實券商執行績效」。

### 實盤模式層級
交易功能至少保留：

```text
OFF
SHADOW
PAPER
LIVE AUTO
```

只有明確 Approved 的 strategy / model version 才能進入 LIVE AUTO。

AI Candidate、Shadow Model、未通過驗證的新 Rebound AI 不得自動取得實盤權限。

### 與 Private Core 整合
未來 Public / Private GitHub 拆分時，以下全部屬於 Private Core：
- Shioaji session
- broker credential store
- trade gate
- risk manager
- execution engine
- live position manager
- live trade ledger
- live reporting backend
- account reconciliation

公開 repo 只能顯示經過授權後的必要狀態，不包含任何可直接下單的秘密或核心交易邏輯。

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
