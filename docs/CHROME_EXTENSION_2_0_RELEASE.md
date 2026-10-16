# Chrome Extension 2.0 — Release Candidate 技術說明

- 版本：`1.0.5 / 1.05` → `2.0.0 / 2.0`
- Base：`origin/main` @ `c2eabac`（2026-10-16），分支 `feat/chrome-extension-2.0`
- 狀態定義：`IMPLEMENTED`（程式完成）／`CODE_VERIFIED`（自動化測試通過）／`MOCK_VERIFIED`（以模擬 Google / Firebase 驗證）／`LIVE_VERIFIED`（真實環境驗證）／`BLOCKED`／`NOT_STARTED`

## 1. 自選股與行情 BUG 根因（Stage A）

以 2026-10-16 17:51（台北）唯讀實測正式資料來源佐證：

| 現象 | 根因（已在程式碼與實測中確認） | 修正 |
| --- | --- | --- |
| 點加入有時沒進自選 | popup `act()` 在任何請求進行中（開啟時的強制刷新會跑 public_feed、Yahoo、spark 等多個 4–8 秒請求）**直接丟棄**新的點擊；背景 `serial` 佇列也讓 ADD 排在整個刷新之後 | 狀態寫入與行情快取分成兩個佇列，網路 I/O 不佔佇列；唯讀訊息不進狀態佇列；popup 不再丟棄請求，相同唯讀請求合併 |
| 加入成功但列表沒更新／重開才看到 | 開啟時的刷新 snapshot 在**網路請求前**讀 state，晚回來時用舊清單覆蓋畫面；`act()` 吞錯誤，失敗也顯示「新增成功」 | snapshot 改在網路後讀 state；state 帶 `rev`，較舊的回應只更新行情不覆蓋清單；新增先樂觀顯示、背景確認，失敗才移除並顯示原因 |
| `00878` 顯示 `--` | 正式 `public_feed`（1,269 檔）**沒有 00878**；補價只在 popup 記憶體做，關掉就消失，且失敗沒有狀態 | 背景在新增後立即抓 Yahoo 報價＋分時並寫入 `feedCache`，以 `QUOTES_UPDATED` 推送；顯示「載入中／暫無行情」 |
| `1102` 顯示 09:00、無分時 | `public_feed` 的 1102 是**前一日 09:00:54** 的快照、無昨收；舊合併邏輯在收盤後保留舊價、只覆蓋漲跌幅，造成「昨日價格＋今日漲跌」混搭，時間只顯示 HH:MM 看不出是昨天；分時只附加在已存在的報價上 | `mergeQuote()` 以來源時間新者整筆勝出，不跨日混用欄位（昨收僅同日可補）；`quoteStatus()` 標示「資料過期」；跨日顯示 MM/DD |
| 無真實分時卻畫出折線 | Sparkline 無資料時用 OHLC 捏造 5 點折線；線圖頁取不到資料時用 `generateMock*` 產生假分時／假日 K；分時開盤前以昨收回填 | 只畫同一台北交易日的真實點，否則顯示「—」；線圖頁顯示「暫無真實分時資料」；開盤前空白分鐘不回填 |
| 報價缺來源時間時被當成「現在」 | `normalizeQuoteTimestamp()` 無法解析時回傳 `now`、Yahoo 缺時間時硬填 `13:30` | 改回傳 `null`，狀態為「資料過期」 |
| 上櫃／上市猜錯導致永遠無價 | 未知 4 碼代號以 5/6/8 開頭猜上櫃（如 6505 台塑化實為上市） | 報價查不到時自動改查另一市場，成功則校正自選股市場別與名稱 |

### 指數 10:16 → 10:48 延遲

| 疑點 | 驗證結果 |
| --- | --- |
| `feeds()` 指數 TTL 到期分支仍返回舊 cache | **確認**：兩個分支都 `return cache`，指數只能跟著 5 分鐘的整批行情更新 |
| 背景 alarm 只有在「當沖提醒」開啟時才刷新 | **確認**：`poll()` 在 `daytrade` 關閉時直接 return，背景完全不更新指數 |
| 遠端設定讀取失敗阻擋刷新 | **確認**：`poll()` 先 `remoteConfig()`，失敗（含 5 分鐘節流）就中止，指數也不刷新 |
| `public_feed` 失敗連帶丟掉指數 | **確認**：指數與 `public_feed`、`intraday_live` 同一個 `Promise.all`，任一失敗整批丟棄，之後 5 分鐘 `feedAttempt` 節流 |
| popup 30 秒指數刷新被擋 | **確認**：`!pending` 條件下，只要有其他請求進行中就跳過 |
| MIS API 本身延遲 | 實測 `tlong` / `t` 與查詢時間一致（`userDelay 5000`），非主因 |

修正：指數有獨立 TTL（30 秒）與獨立快取欄位（`taiexAttemptAt`），不受整批行情 TTL、提醒開關、遠端設定或 public_feed 失敗影響；指數資料帶 `source / quote_at（MIS tlong）/ received_at`，快照計算 `age_seconds / fresh / market_status / status`（`LIVE / CLOSE / STALE / UNAVAILABLE`）。抓取失敗保留最後有效值並標示「資料過期」與錯誤原因，盤中超過 3 分鐘未更新即為 STALE。

> 無法重現當時的實際網路狀態，以上為程式碼與測試證實的「足以造成延遲的原因」，不宣稱為唯一原因。

## 2. Google 登入（Stage B）

- 實作：`chrome.identity.getAuthToken`（Chrome 快取與更新 Google token）→ Firebase Auth REST `accounts:signInWithIdp` → Firebase UID / ID Token → RTDB REST `?auth=`。
- 為何不用 Firebase SDK：官方文件說明 Google 等彈出式登入需要 Offscreen Document + 外部託管頁面，並把 `apis.google.com`、`gstatic.com` 等加入 CSP。REST 方式不需要遠端程式碼、不放寬 CSP、不需新增主機權限（Identity Toolkit 支援 CORS），升級時使用者不會被要求重新授權。
- 權限：只新增 `identity`；`oauth2` 只在設定了真正的 Chrome 擴充功能 Client ID 時由 build 注入，原始碼不放佔位字串。
- Token：Firebase ID Token 只存 `chrome.storage.session`；不存 Refresh Token、Client Secret；不記錄到 console。ID Token 過期用 Chrome 快取的 Google token 靜默換新；Firebase 拒絕過期的 Google token 時先從 Chrome 快取移除再重試一次；Chrome 帳號被換掉時拒用並要求重新登入。
- 缺設定時：狀態 `BLOCKED_BY_OAUTH_CONFIGURATION`，按鈕停用，本機功能不受影響。

## 3. Firebase 同步（Stage C）

資料結構（`users/{uid}`，Firebase UID 為唯一隔離鍵，不以 Email 當 key）：

```text
users/{uid}/
  profile:   { schema: 1, client: "chrome-extension", updatedAt }
  watchlist: { "2330": { symbol, market, name, groups: { watchlist: true, daytrade: true }, updatedAt, addedAt, source } ,
               "1102": { symbol, deleted: true, updatedAt } }        ← 刪除標記（90 天後清除）
  alerts:    { daytrade|allDaytradeAlerts|filterMode|minPrice|maxPrice|minChangePct: { v, t } }
  settings:  { darkMode|colorMode|fontSize|pageSize|cardDensity|windowHeight|showSparkline|preferredBroker: { v, t } }
  groups:    （保留給未來自訂群組；目前群組是每檔股票的固定成員旗標，嵌在 watchlist 裡）
```

不上傳：行情／K 線快取、VIP 雜湊、通知 ledger、任何 token、券商資料。現有本機資料沒有「個股提醒」欄位，因此沒有另建；提醒條件即 `alerts`。

合併規則（`sync.js`）：

- 第一次登入（本機尚未屬於任何 UID）：**Union**，只合併不覆蓋不刪除；相同股票只一筆、群組聯集、取較好的名稱；雲端刪除標記不會刪掉本機資料。
- 之後：每檔股票、每個設定欄位以時間戳「新者勝」；刪除是刻意動作，以刪除標記同步，較晚的重新加入會勝過舊刪除。
- 設定：從未設定過的預設值（例如 2.0 新安裝的白色主題）一律輸給雲端值；1.05 既有值視為使用者選擇（時間戳 1），不會被 2.0 預設覆蓋。
- 超過 100 檔：本機絕不刪除，放不下的保留在雲端並提示。
- 帳號切換：上一個 UID 的本機副本暫存在這台電腦（`syncMeta.stash`，不上傳），新帳號從自己的資料開始；A 再登入時取回。
- 登出：清除 session token 與記憶體中的登入狀態，停止同步，不刪雲端資料；本機清單保留供離線使用並記住擁有者 UID。

傳輸策略：Local-first + Event-driven，REST 短連線，**不建立長時間 listener**。

- 寫入 debounce 3 秒；同時呼叫合併成一次（dedup）；GET 帶 ETag，PUT 用 `if-match` 條件寫入，412 時重讀重合併（最多 3 次）。
- 沒有變更時只 GET、不 PUT；PUT 使用 `print=silent`，不下載回應內容。
- 離線：`dirty` 旗標即離線佇列；失敗時指數退避 30 秒→最長 30 分鐘；Alarm 每分鐘檢查，6 小時拉一次；開 popup 最多每 10 分鐘拉一次。
- 同步狀態可見：已同步／同步中／離線／同步失敗（含原因）／需要重新登入／待設定，以及最後同步時間與「有待上傳變更」。

## 4. Spark 免費額度評估（官方定價頁 2026-10-16：100 同時連線、1 GB 儲存、10 GB/月下載）

使用者同步文件大小（以 `mergeAll()` 實際輸出量測）：10 檔 ≈ 2.2 KB、20 檔 ≈ 3.9 KB、30 檔 ≈ 5.6 KB、100 檔 ≈ 17.5 KB。
每次同步只有 GET 會計入下載（PUT 用 `print=silent`）；無變更時不 PUT。

| 活躍使用者 | 典型（20 檔，約 15 次 GET/日 ≈ 59 KB/人/日） | 每月下載（30 日） | 重度（100 檔，約 40 次 GET/日 ≈ 700 KB/人/日） | 每月下載 |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 5.9 MB/日 | ≈ 0.18 GB | 70 MB/日 | ≈ 2.1 GB |
| 500 | 29 MB/日 | ≈ 0.88 GB | 350 MB/日 | ≈ 10.5 GB（**超過**） |
| 1,000 | 59 MB/日 | ≈ 1.8 GB | 700 MB/日 | ≈ 21 GB（**超過**） |

- 典型用量下，同步本身在 1,000 位活躍使用者內可留在 Spark；重度用量約 500 人就會超過。若接近上限，可調高 popup 拉取間隔（目前 10 分鐘）或改為「只在有變更或手動時同步」。
- 儲存：1,000 人 × 最多 17.5 KB ≈ 18 MB，遠低於 1 GB。
- 同時連線：同步只用短 REST 請求（每次約 0.1–0.3 秒）。官方文件未說明 REST 請求是否計入同時連線；即使計入，1,000 人在 09:00 同一分鐘各開一次 popup，估計同時約 5 個，遠低於 100。2.0 沒有新增任何長連線。
- **既有（1.05 起）主要風險，2.0 未改變**：公開行情 `market_data/public_feed.json` 實測 890,878 bytes。開 popup 的強制刷新與「當沖提醒」開啟時每 5 分鐘的背景刷新都會下載整份；單一使用者盤中約 54 次 ≈ 48 MB/日，Spark 10 GB/月約在 **9–10 位全天開啟提醒的使用者**就會用完。建議另案把公開行情改由 GitHub Pages／CDN 提供，或改為依自選股的精簡 feed。2.0 只有在「當沖提醒關閉」時改為抓 TWSE 指數與 Yahoo 自選報價（不經 Firebase），沒有增加 Firebase 下載。

## 5. Security Rules 變更、測試與回滾

- 線上現況（未登入實測）：根目錄、`/users`、`/market_data` 淺層讀取皆 401；`market_data/public_feed` 可讀。根目錄沒有公開讀取，不會讓 `users/{uid}` 透過繼承外洩。
- 建議變更：`firebase.rules.json` 新增 `users/$uid`（owner-only 讀寫＋結構驗證＋未知節點拒絕），其餘不變。
- 測試：`tests/test_rules.cjs` 依 RTDB 權限繼承語意模擬（非官方 emulator）：未登入不可讀寫使用者、A 不可讀寫 B、A 可讀寫自己、不可列出 `/users`、公開行情仍可讀、一般使用者不可寫 `market_data`／admin／broker 等任何路徑、根目錄必須維持 false。`tests/test_chrome2_rules_merge.py` 驗證合併工具只加入 `users`、拒絕根目錄公開或非 owner-only 的規則。
- 未執行：Firebase Emulator 的 rules-unit-testing（需 Java + firebase-tools，本機未安裝）；正式 Rules **未發布**。
- 發布與回滾：`tools/firebase_rules.py --merge-users`（乾跑 → `--apply --expected-sha256`），先備份、套用後驗證公開節點與 `/users` 匿名拒絕，失敗自動回滾；手動回滾＝套用備份檔。詳見 `docs/CHROME_EXTENSION_2_0_GOOGLE_SETUP.md` 第 8 步。

## 6. 測試矩陣

| ID | 項目 | 狀態 | 證據 |
| --- | --- | --- | --- |
| T01 | 2330 新增立即顯示 | CODE_VERIFIED | stage-a.test：先存 storage、回應含股票、pendingQuotes |
| T02 | 1102 不因行情延遲消失 | CODE_VERIFIED | stage-a.test |
| T03 | 00878 ETF 辨識／加入／查價 | CODE_VERIFIED（Yahoo 正式 API 2026-10-16 唯讀實測有資料） | stage-a.test |
| T04 | 查不到價仍留在自選 | CODE_VERIFIED | stage-a.test |
| T05 | Service Worker 重啟不遺失 | CODE_VERIFIED | 重新 import background 讀同一 storage |
| T06 | 重複加入不重複 | CODE_VERIFIED | stage-a.test、popup jsdom |
| T07 | 關閉再開仍存在 | CODE_VERIFIED | BOOTSTRAP 讀 storage |
| T08 | 不跳確認窗 | CODE_VERIFIED | popup jsdom：confirm/alert 未被呼叫 |
| T09 | 1.05 自選升級無遺失 | CODE_VERIFIED | upgrade.test、sync.test |
| T10–T11 | 指數 TTL 到期即更新、個股快取不阻擋 | CODE_VERIFIED | stage-a.test |
| T12 | 指數 timeout 標 stale | CODE_VERIFIED | stage-a.test |
| T13 | 不以過期價冒充即時 | CODE_VERIFIED | 1102 正式案例重現 |
| T14 | 台北盤中時間 | CODE_VERIFIED | stage-a.test、core.test |
| T15 | 休市不誤報 | CODE_VERIFIED | 週末／國定假日 |
| T16 | 不受電腦時區影響 | CODE_VERIFIED | 測試以 `TZ=America/New_York` 執行 |
| T17 | 無真實分時不畫線 | CODE_VERIFIED | sparkForQuote、fetchIntradayData、popup |
| T18 | Google 登入取得 UID | MOCK_VERIFIED／**LIVE BLOCKED_BY_OAUTH_CONFIGURATION** | sync.test |
| T19 | 拒絕授權不影響本機 | MOCK_VERIFIED | sync.test |
| T20 | 登出後不可存取 | MOCK_VERIFIED | sync.test |
| T21 | 切換帳號不混用 | MOCK_VERIFIED | sync.test |
| T22 | token 過期恢復／重新登入 | MOCK_VERIFIED | sync.test |
| T23 | 缺設定顯示待設定 | CODE_VERIFIED | sync.test、upgrade.test、UI 預覽 |
| T24–T29 | 首登同步、union、不重複、離線、補同步、失敗不清空 | MOCK_VERIFIED | sync.test（模擬 RTDB REST＋ETag） |
| T30–T31 | 帳號隔離、不可寫公開行情／Admin | CODE_VERIFIED（規則模擬）／LIVE NOT_STARTED（規則未發布） | test_rules.cjs |
| T32 | 舊深色不被白色預設覆蓋 | CODE_VERIFIED | upgrade.test、sync.test |
| T33 | 重複同步不多寫 | MOCK_VERIFIED | sync.test：只 GET、不 PUT |
| T34 | ICON 16/48/128 | CODE_VERIFIED | icons.test（RGBA、尺寸、單色） |
| T35–T38 | 白色預設、黑白／紅綠、深色＋黑白 | CODE_VERIFIED＋UI 預覽截圖 | upgrade.test、preview fixture |
| T39–T40 | 「架構」、量多進攻／量減退守 | CODE_VERIFIED | core.test 文案掃描 |
| T41 | 既有提醒與設定 | CODE_VERIFIED | background.test（原有 18 項）＋upgrade.test |
| T42 | Popup 版面 | UI 預覽（四種組合、登入狀態）未見溢出；**未在真實 Chrome 安裝驗證** | — |

## 7. Chrome Web Store 準備

- ZIP：`pnpm --dir chrome-extension package` → `easystock-chrome-extension-v2.0.0.zip`（可重現建置，SHA-256 寫入 `dist/`），自動檢查必要檔案、無測試／金鑰／`key` 欄位、CSP 只允許 `'self'`。
- 未設定 OAuth 時的 ZIP 可安裝，但登入顯示「待設定」——**不應以此版上架宣稱支援 Google 同步**。
- 上架阻擋項目：OAuth Client ID 與 Web API Key、Google 供應商啟用、同意畫面、`users/{uid}` Rules 發布、真實登入與跨帳號 LIVE 驗收、隱私權政策公開網址與 Privacy practices 更新、Owner 自行提交審核。
- 名稱與說明：已改為「台股行情觀察」，移除「AI 量化雷達」「突破點火推播」；品牌「當沖吧！牛馬仔」保留。文案調整不等於已通過證券投資顧問相關法規審查；未來收費訊號、個人化建議或自動交易需另行法遵評估。
- 已知未改：後端送來的出場原因文字（例如「當沖強制出場」）屬於資料內容，原樣顯示；「架構」頁內文仍是既有模型說明（僅修改標題與風控措辭）。
