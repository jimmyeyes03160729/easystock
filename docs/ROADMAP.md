# EasyStock Roadmap

> 本文件用於記錄已確認的後續規劃。  
> 更新原則：使用者在 EasyStock 相關討論中說「紀錄」時，更新此文件，保留既有內容並整理版本脈絡。

## 待新增 / 待執行主題總覽

> 這一區固定放在 Roadmap 最前面，用來快速確認「還有哪些功能尚未執行」。  
> 完成後改成 `[x]`；尚未開始或尚未完成維持 `[ ]`。細節保留在下方對應章節。

- [ ] **手機版底部導覽列改版**
  - 手機版底部改成固定式 5 個主入口。
  - 主入口：盤中摸魚、底部反彈、牛馬 AI、Chrome 小工具、社畜後台。
  - 上方原有主題頁籤仍可保留完整名稱；手機底部採精簡名稱。
  - 桌機版不強制套用同一底部導覽樣式。
  - iPhone 需支援 `safe-area-inset-bottom`，避免 Home Indicator 擠壓。

- [ ] **Chrome Extension 1.01 實盤驗證**
  - 等待完整台股交易時段驗證盤中掃描、通知、刷新、API / Firebase / VM 穩定性。
  - 目前原則：先累積實盤 BUG，確認後再一次性修改，避免頻繁變更正式版本。
  - 已記錄 BUG：
    1. 加權指數目前共用 5 分鐘快取，盤中更新太慢；改為約 10～30 秒並顯示實際資料時間。
    2. 個股日 K 盤中仍停在昨日；改為歷史日 K + 今日即時 OHLC，盤中形成「今日未完成 K 棒」。
    3. 分時走勢圖 X 軸目前會依已有資料拉滿；改為固定 09:00～13:30，未到時間區段保持空白。
    4. 個股列表右側時間疑似時區處理錯誤，需檢查 `q.time` / `updated_at` 與 UTC、Asia/Taipei 是否重複 +8。
    5. 右下角重新整理並非真正強制刷新；`refresh:true` 仍可能直接命中 5 分鐘 `feedCache`，且已有有效 price 的舊報價不會被補抓。
    6. Chrome Popup 開啟時會先出現白色縮小畫面；目前初始載入先 `await SNAPSHOT`，且 Popup 沒有固定 / 最低高度，應先渲染 Skeleton / Shell 再背景載入資料。
    7. 首頁有觸底反彈標的，但 Chrome 小工具未顯示；目前兩邊使用不同 rebound 資料來源 / 判定邏輯，需統一由同一正式 Rebound 結果供應。

- [ ] **Chrome Extension 1.02：Google 登入 + Firebase 使用者同步**
  - Google Authentication。
  - 自選股、當沖監控、提醒條件、群組與設定同步。
  - 第一次登入執行本機資料 Migration。
  - 核心原則：只合併、不覆蓋、不刪除。

- [ ] **觸底反彈 AI 學習**
  - 統一正式 Rebound 定義。
  - 建立 `rebound_learning/`。
  - 收集候選 Dataset。
  - 10 個交易日後自動 Label。
  - Baseline / Logistic Regression / HistGradientBoosting 比較。
  - 先 Shadow，再決定是否 Applied。

- [ ] **永豐實盤當沖後台（Owner-only）**
  - 永豐 API / CA 憑證安全持久化。
  - AUTO ON / OFF、Auto Resume、KILL SWITCH。
  - 真實委託 / 成交 / 持倉 Reconcile。
  - 獨立 `live_trade_*` 帳本。
  - 今日交易、損益、手續費、稅與歷史報表。
  - 今日 PnL、單筆交易、Equity Curve 圖表。
  - PAPER vs LIVE 執行差異比較。

- [ ] **首頁 AI 復盤改版：淘汰舊 OpenAI 每日文字復盤**
  - 現況：首頁仍讀取 `market_data/dual_review_status`，該資料目前停留在 2026-09-22；現行 repo / 排程已沒有明確 producer 持續發布此節點。
  - 不優先修復舊的每日 OpenAI 文字復盤流程。
  - 首頁改為「每日盤後研究摘要」，以可驗證的量化資料為主。
  - 每日顯示：模擬交易筆數、勝負、淨損益、平均單筆、MFE / MAE、樣本數、Label 數、模型版本、驗證狀態、Brier / Drawdown 等。
  - AI 改為每週 Architecture Review 或異常觸發分析，不再每天固定產生文字復盤。
  - 清理舊 `dual_review_status` / OpenAI daily review / legacy paper feedback 顯示與相關技術債；若保留歷史資料，只作歷史展示，不得冒充當日結果。

- [ ] **AI Architecture Guardian 系統健檢**
  - 每日 Tests / CodeQL / Secret Scan / Dependabot / Trivy / 自訂安全規則。
  - 每週 AI Architecture Review。
  - 首頁顯示 SAFE / REVIEW / DANGER / UNKNOWN 摘要。
  - Private Admin 顯示 Critical / High / Medium / Low 詳細報告。
  - 第一階段只掃描、分析、報告、通知，不直接修改交易系統。

- [ ] **GitHub / 模型核心保護與 Public / Private Core 拆分**
  - Public repo 只保留網站、Chrome UI 與必要 API Client。
  - 策略、模型、訓練、交易、Shioaji、風控移入 Private Core。
  - 移除 `raw.githubusercontent.com` 等直接 GitHub 關聯。
  - Public repo 採乾淨 Git history，避免舊 commit 持續暴露核心程式。



---

## 手機版底部導覽列規劃

### 目標
手機版首頁改為固定式底部導覽列，參考使用者提供的深色底部 Tab Bar 風格，讓主要功能更容易單手切換。

### 5 個主入口
完整名稱：
1. 盤中摸魚
2. 底部反彈
3. 牛馬 AI
4. Chrome 小工具
5. 社畜後台

手機底部可採精簡顯示：
- 摸魚
- 反彈
- 牛馬 AI
- 小工具
- 後台

### 顯示原則
- 手機版固定於畫面底部。
- 深色底板，Active 項目使用目前網站主色高亮。
- Icon 在上、文字在下。
- 桌機版維持原有上方 / 主要導覽，不強制使用手機底部列。
- iPhone 必須支援 `env(safe-area-inset-bottom)`。
- 不因新增底部列而遮住頁面內容，正文底部需預留導覽列高度。

### 路由 / 功能對應
- 盤中摸魚 → 目前盤中當沖 / 即時雷達首頁。
- 底部反彈 → Rebound 模組。
- 牛馬 AI → AI 學習 / 模型 / 系統健檢相關內容。
- Chrome 小工具 → Chrome Extension 介紹、功能與安裝入口。
- 社畜後台 → Owner / Admin 後台入口。

### 安全原則
「社畜後台」即使在前端顯示，也不可因此放寬任何 Admin 驗證；後台仍必須維持原本的 Owner-only / Google 驗證與 Private Admin 權限。

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

### 已累積的 1.01 Chrome 小工具 BUG
目前先記錄，不立即修改；累積一批後再一次性處理與測試。

1. **加權指數更新時間**
   - 目前 `fetchTaiexIndex()` 雖直接抓 TWSE MIS，但 `feedCache` 共用 `TTL = 5 分鐘`。
   - 盤中加權指數不應使用 5 分鐘快取。
   - 修正方向：盤中獨立成約 10～30 秒更新頻率。
   - UI 顯示實際來源時間，例如 `資料時間 09:08:25`，避免只顯示畫面刷新時間。

2. **個股日 K 盤中仍顯示昨日**
   - 目前歷史日 K 優先使用 Yahoo `interval=1d`，盤中不保證提供今日尚未完成的日 K。
   - 修正方向：歷史日 K + 今日即時 / 分時 OHLC 合併。
   - 09:00～13:30 顯示「今日未完成 K 棒」；收盤後再轉成正式日 K。
   - 不可用假資料補今日 K。

3. **分時走勢圖 X 軸跟著目前資料長度拉伸**
   - 現在 `drawIntraday()` 依 `visibleCount` 計算 X 軸，所以早盤幾分鐘資料會撐滿整張圖。
   - 修正方向：台股日盤 X 軸固定 `09:00～13:30`。
   - 09:30 永遠落在固定時間位置，不因目前只有 30 分鐘資料而跑到最右端。
   - 現在時間之後的區段保持空白，直到新資料逐步填入。
   - 建議固定主要刻度：`09:00 / 10:00 / 11:00 / 12:00 / 13:00 / 13:30`。

4. **個股列表右側時間疑似 +8 時區錯誤**
   - 現象：個股右側時間與台灣實際時間不一致，疑似多加 8 小時。
   - 前端目前優先使用 `q.time`，否則才解析 `updated_at`。
   - 後端 `public_feed.py` 的 `updated_at` 已使用 `datetime.now(TPE).isoformat()`，本身已帶 `+08:00`。
   - 檢查方向：確認 `q.time` 來源、UTC / TPE 是否被重複轉換，以及前端是否對已帶 `+08:00` 的時間再次手動加時區。
   - 修正原則：後端輸出明確含 offset 的 ISO 8601；前端統一只轉一次 `Asia/Taipei`，禁止手動再 +8。

5. **右下角重新整理不是實際強制刷新**
   - 現象：例如 00878 可能有更新，但 2330 台積電按重新整理沒有反應。
   - `btn-refresh` 會送 `SNAPSHOT refresh:true`，但 `feeds(now, true)` 進入後仍先檢查 5 分鐘 `feedCache`，所以可能直接回舊資料。
   - `enrichMissingQuotes()` 目前只補缺報價 / 缺漲跌幅；若舊報價的 `price` 與 `change_pct` 仍是有效數字，即使已過期也不會重新抓。
   - 修正方向：使用者手動按重新整理時必須真正 bypass cache，重新抓 public feed / 大盤，並依每檔股票 freshness 判斷是否需要重抓即時行情。
   - 不可只判斷欄位「有值」，還必須判斷 `updated_at / quote_at` 是否新鮮。

6. **Chrome Popup 初次開啟白屏並縮到最小**
   - 現象：點擊 Chrome 小工具後，資料讀取期間整個介面先呈現白色、很小的 Popup，等資料回來後才恢復完整尺寸。
   - 目前 `popup.js` 初始化最後直接 `await act({ type: 'SNAPSHOT', refresh: true })`，完整畫面要等待遠端資料後才 render。
   - Popup CSS 目前固定寬度約 440px，但沒有固定 / 最低高度，因此資料尚未渲染時 Chrome 會依當下少量內容縮小 Popup。
   - 修正方向：
     - HTML 初始即提供完整 Shell / Skeleton 畫面。
     - 設定合理 `min-height` 或固定初始高度，避免 Popup 尺寸跳動。
     - 開啟時先立即 render 快取 / placeholder，不阻塞 UI。
     - `SNAPSHOT` 改背景非阻塞更新，資料回來後再局部更新。
     - Loading 階段延續目前深色 / 淺色主題，不應出現突兀純白閃屏。

7. **首頁有觸底反彈但 Chrome 小工具沒有顯示**
   - 現象：EasyStock 首頁已顯示觸底反彈標的，但 Chrome Extension 的「觸底反彈」頁籤為空或缺少相同標的。
   - 目前首頁使用 `assets/rebound-engine.js` / `assets/rebound-ui.js` 執行較完整的 range-rebound 邏輯。
   - Chrome Extension 的 `view.bounce` 則由 `background.js` 合併：
     - remote config 的 `bounce_strategy_signals`
     - `fetchSummaryRebound()` 從 `summary.selection.strategies.REBOUND` 產生的標的
   - 兩邊不是同一資料來源，也不是同一套正式 Rebound 定義，因此首頁有標的時，小工具不一定有。
   - 修正方向：先依既定 Roadmap 統一正式 Rebound 定義，再由後端發布單一正式 Rebound feed，首頁與 Chrome Extension 都讀同一份結果。
   - 不應由 Chrome Extension 自己再做另一套反彈判定，也不應靠 hard-coded featured symbols 補資料。
   - 最終要求：首頁、Chrome Extension、LINE / Telegram（若顯示反彈）必須共享同一 signal id / generated_at / quote_at / strategy_version，避免跨平台結果不一致。


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

## 首頁 AI 復盤改版規劃

### 問題現況
- 首頁 `assets/learning-status.js` 目前每 60 秒讀取 Firebase `market_data/dual_review_status`。
- 前端使用 `cache: 'no-store'`，因此畫面停在 2026-09-22 並非瀏覽器快取造成。
- 目前 main branch 找不到持續寫入 `dual_review_status` 的正式 producer；Firebase Rules 僅保留公開讀取。
- 舊 OpenAI-only 每日復盤與 legacy paper feedback 流程屬於 2026-09-21～22 階段的架構，後續現行盤後研究流程已改為 `learning_cycle.py` / `learning_eod.py`。
- 現行 `deploy/install_research_schedule.sh` 會停用舊 `easystock-paper-train.timer` 與 `easystock-paper-feedback.timer`，改用新的 research-cycle。
- 舊復盤區沒有像其他狀態面板一樣嚴格檢查 stale `updated_at`，因此可能把舊資料繼續顯示成「OpenAI 復盤完成」。

### 決策
不優先把舊「OpenAI 每日文字復盤」修回來。

原因：
- 文字復盤不直接決定 ENTRY / EXIT。
- 不等於模型已更新或正式套用。
- 不代表模型績效或勝率提升。
- 現行五特徵 / 盤後候選模型流程不需要依賴每日文字摘要。
- 每天固定呼叫 AI 產生文字內容，價值低於可驗證的量化研究指標。

### 首頁替代方案：每日盤後研究摘要
將原「OpenAI 每日復盤」區塊改成「每日盤後研究摘要」。

建議至少顯示：
- 當日模擬交易筆數。
- 獲利 / 虧損筆數。
- 當日淨損益與報酬率。
- 平均單筆損益。
- MFE / MAE。
- 主要 Exit Reason 分布。
- 今日新增研究樣本。
- 今日完成 Label 數。
- 資料收集完整度 / stale 狀態。
- 目前載入模型版本。
- 今日 Candidate / Approved / Shadow / Blocked 狀態。
- Walk-forward / Holdout 摘要。
- Brier、Profit Factor、Drawdown 等可驗證研究指標。

### AI 使用方式
AI 改為「需要時才使用」：
- 每週：交由 AI Architecture Guardian 做架構 / 模型 / 資料流程 Review。
- 異常觸發：例如連續虧損、Drawdown 突增、模型表現惡化、資料缺漏、策略漂移或模型 / schema 異常時，再呼叫 AI 深度分析。
- 每日固定工作以 deterministic / quantitative 計算為主，不讓 AI 文字摘要成為模型狀態或交易狀態的證據。

### 舊功能清理原則
- 停止把 `dual_review_status` 當成目前每日流程的正式狀態來源。
- 若保留 2026-09-22 等舊復盤資料，只能標示為歷史紀錄。
- 移除或停用已無正式 producer 的 OpenAI daily review UI。
- 清理 legacy paper feedback 在首頁造成的重複 / 誤導顯示，但不得因此刪除真正仍被研究流程使用的資料或模型 artifact。
- 所有首頁模型狀態必須以實際 runtime / training / validation evidence 為準，不能以文字復盤是否完成推定模型已更新。

---

## AI Architecture Guardian 系統健檢規劃

### 功能定位
新增一套獨立的「AI Architecture Guardian」，用來檢查 EasyStock 最近的程式與架構是否逐漸變得不合理、不安全或容易失控。

與現有 Guardian 的職責分開：

```text
EasyStock Guardian
→ 檢查 VM / 服務現在是否正常運作

AI Architecture Guardian
→ 檢查最近程式、交易邏輯、AI 模型與資料流程是否越改越危險
```

### 整體架構

```text
GitHub Repository
      ↓
GitHub Actions
      ├─ Unit Tests
      ├─ CodeQL
      ├─ Secret Scan
      ├─ Dependabot
      ├─ Trivy
      ├─ Python / JS Static Checks
      └─ EasyStock Custom Safety Rules
                    ↓
             health-report.json
                    ↓
        Weekly AI Architecture Review
                    ↓
          Firebase / Private Admin
                    ↓
             EasyStock 首頁摘要
```

### 每日健檢
每日執行確定性高、可重複驗證的自動檢查，不依賴 AI 判斷。

建議至少包含：
- Python syntax / import 檢查
- Python tests
- JavaScript / Chrome Extension tests
- Firebase Rules 檢查
- Secret Scan
- CodeQL
- Trivy
- Dependency vulnerability 檢查
- GitHub Actions 狀態
- 關鍵檔案 hash / drift 檢查
- VM Guardian 狀態摘要
- EasyStock 自訂交易安全規則

每日結果產生固定格式的 `health-report.json`。

### EasyStock 自訂安全規則
一般 CodeQL 不知道交易系統的商業與風控規則，因此必須建立 EasyStock 自己的檢查器。

建議：

```text
health_rules/
├── trading_safety.py
├── model_safety.py
├── firebase_safety.py
├── data_integrity.py
└── architecture_rules.py
```

交易安全至少檢查：
- 只有 Approved strategy / model 才能進 LIVE AUTO
- AUTO OFF 是否真的阻止新單
- KILL SWITCH 是否覆蓋所有下單路徑
- Owner account_id / broker_id / person_id 是否強制驗證
- Shioaji API / CA Secret 是否只存在後端
- 真實成交是否以 Deal Callback 為準
- VM 重啟是否先做 position / order reconcile
- Ledger 與券商持倉不一致時是否 AUTO PAUSED
- PAPER / LIVE 是否可能共用錯誤路徑
- Candidate / Shadow 模型是否可能誤進實盤

### AI 模型健檢
每日 / 每週檢查：
- Candidate 是否可能被自動 Promote
- Training / Inference Features 是否一致
- Feature schema version 是否一致
- Model threshold 是否被意外改動
- Holdout 是否誤拿去 Training
- 是否可能 Future Leakage
- 不同策略版本資料是否混用
- Shadow Model 是否可能進 LIVE
- Rebound 的 10D Label / SUCCESS / FAIL 定義是否一致
- 舊 Rebound 與 range-rebound 是否混用

### 資料品質健檢
至少檢查：
- Firebase active_release 是否正常
- K 線日期 / release 是否一致
- 即時行情是否過期
- Shioaji / Fugle 資料更新是否正常
- AI Dataset 是否有缺失 Feature
- Label 是否已成熟
- History 是否出現 Future Leakage
- Public Firebase Write 是否保持 DENY
- Public / Private 資料邊界是否被破壞

### 每週 AI Architecture Review
每週不重新把整個 Repository 無差別丟給 AI。

只提供：
- 最近 7 天 commits
- Git diff
- docs/ROADMAP.md
- docs/ARCHITECTURE.md
- health-report.json
- 測試失敗紀錄
- 關鍵模組摘要
- 已知 Guardian incidents

AI 每週主要回答：
- 是否出現重複邏輯
- 是否有不合理 fallback
- 是否破壞安全邊界
- 是否讓模型進入錯誤執行階段
- LIVE / PAPER 是否可能混用
- Public / Private boundary 是否外洩
- Dataset / Label 是否可能污染
- 交易風控是否可能被繞過
- 最近修改是否與 ROADMAP / ARCHITECTURE 衝突

### AI Provider
目前 Public Repository 階段，可優先使用 Gemini Developer API Free Tier 作為每週架構審查工具。

原則：
- 不讓 Gemini 直接取得 GitHub write 權限
- GitHub Action 先產生有限範圍的 audit bundle
- AI 只讀 audit bundle
- AI 不可直接部署或修改正式交易系統
- AI 的判斷只能形成 Review / 建議，不可直接解除交易安全限制

未來 Private Core 建立後，Private Trading Core、模型與券商邏輯不應整份送到免費外部 AI API。

未來改採：
- VM / NAS 本機 Ollama
- 開源 Coding Model
- 本機 Architecture Review

讓 Private Core 程式碼不離開自己的 VM / NAS。

### 首頁顯示
首頁只顯示摘要，不公開詳細漏洞或內部攻擊資訊。

建議卡片：

```text
🩺 EasyStock AI 系統健檢

整體狀態       🟢 SAFE
最後健檢       今日 06:20

程式穩定性     🟢 正常
交易安全       🟢 正常
AI 模型        🟡 2 項注意
資料品質       🟢 正常
資安           🟢 無高風險
相依套件       🟡 1 項需更新

[查看詳細報告]
```

狀態只使用：
- SAFE
- REVIEW
- DANGER
- UNKNOWN

避免使用「87 / 100」之類容易製造錯誤安全感的總分。

### Admin 詳細報告
完整報告只在 Private Admin 顯示。

固定分級：
- Critical
- High
- Medium
- Low

每一項包含：
- 問題
- 影響
- 證據來源
- 建議處理方式
- 是否阻擋 LIVE AUTO
- 狀態
- 首次發現時間
- 最近確認時間

例如：

```text
問題：
Rebound 存在兩套策略定義

風險：
AI Dataset 標籤可能污染

等級：
High

建議：
統一 range-rebound

LIVE AUTO：
不直接阻擋，但禁止 Rebound AI Applied
```

### 自動化安全邊界
AI Architecture Guardian 第一階段只做：
- 掃描
- 分析
- 報告
- 通知

不得自動：
- 修改交易策略
- 修改模型門檻
- Promote Candidate Model
- 開啟 LIVE AUTO
- 變更券商帳戶
- 修改 KILL SWITCH
- 修改 Firebase 安全規則
- 將 AI 建議直接部署到正式交易環境

若未來要加入自動修復，只能針對已明確 allowlist 的非交易性問題，並沿用現有 Guardian 的隔離、備份、測試與人工核准機制。

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
3. 同步更新文件最前面的「待新增 / 待執行主題總覽」。
4. 新增但尚未完成的主題一律加入最前面總覽並維持 `[ ]`。
5. 已完成並確認上線的主題改成 `[x]`，避免仍被誤認為待辦。
6. 保留既有內容，不重複堆疊。
7. 依版本與主題整理。
8. 不因「紀錄」而修改正式功能程式碼。
9. 不影響目前正式版本，除非使用者另行要求。
