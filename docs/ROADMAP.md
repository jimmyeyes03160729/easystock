# EasyStock Roadmap

## 2026-10-03 live validation preflight

- [ ] Market Risk Gate full-session live evidence: READY_FOR_LIVE_VALIDATION.
  Existing stale-premarket, dual-provider fallback, UNKNOWN block, true RED
  block and multi-quote recovery rules remain unchanged. Private point-in-time
  market-gate JSONL and a read-only validation command were added.
- [ ] Research/Paper natural over-limit event: inspect durable events after a
  complete trading session. Synthetic 3189 scenarios do not close live validation.
- [x] Paper daytrade execution alignment: CODE VERIFIED and VM DEPLOYED
  on 2026-10-03 after canonical updater exit 0 and release/ledger verification.
  Fresh bid/ask depth,
  explicit eligibility, pending unfilled exits and canonical cost assumptions
  are described in DAYTRADE_COMPLIANCE_REVIEW_2026-10-03.md.

> 本文件用於記錄已確認的後續規劃。  
> 更新原則：使用者在 EasyStock 相關討論中說「紀錄」時，更新此文件，保留既有內容並整理版本脈絡。

## 目前主要進行中三主線（2026-10-05）

- [ ] **正式當沖系統：完整交易日 LIVE Validation**
  - 程式核心與 Paper execution alignment 已完成並部署；現在不是重寫策略，而是收完整交易日證據。
  - Market Risk：驗證 stale premarket 不等同 RED、Shioaji / 玉山 fallback、雙來源失效時 UNKNOWN + BLOCK、真 RED 正常 BLOCK、盤前 RED 可由連續盤中 fresh evidence 依 hysteresis 恢復。
  - Research / Paper：等待自然發生的 `daily_buy_limit_exceeded` 案例，確認 Research 仍 TRACKED、Paper SKIPPED，並完整保留 ENTRY / EXIT / MFE / MAE / PnL。
  - Synthetic fixture 只證明程式邏輯，不等同 LIVE VERIFIED；不得為了驗證刻意降低每日額度、放寬 ENTRY 或注入假行情。

- [ ] **當沖學習 / 研究系統：持續執行**
  - Phase 2A / 2B / 2C 歷史研究與研究治理基礎已建立；目前正式狀態仍是研究階段，不代表 production-ready。
  - 已有 Research Trial Ledger、Objective Governance、OOS Consumption Ledger、Central Dataset Registry、Pristine Holdout Policy。
  - `PHASE2C_FUTURE_60D` 保留自 2026-10-05 起的前 60 個符合條件交易日作未曝光確認；在正式解封前不得讀取 performance / outcome。
  - 目前研究狀態維持 `PRODUCTION_READY=false`、`INDEPENDENT_CONFIRMATION=false`；未曝光未來樣本用來做後續 one-shot confirmation，不可反覆微調後重測。
  - 研究 / 學習流程與正式 ENTRY / EXIT 保持治理隔離；任何研究結論不得自動晉升正式模型或修改正式策略。

- [ ] **AI NAS 串聯：Antigravity + Codex 自動開發鏈持續建置**
  - NAS 已有獨立 ARM64 Antigravity 開發容器與獨立 Codex development node；兩者使用隔離的 Compose / network / home / workspace。
  - 已具備 Git pull、修改、測試、commit / push main 的開發節點能力，並已有 NAS pull-backup / Docker backup scheduler。
  - 安全邊界：NAS AI 容器不掛 Oracle VM SSH key / SSH agent、不直接部署正式 VM、不自動 push；正式 VM deployment 仍走既有受保護流程。
  - 下一階段重點是把「任務入口 → AI 分工 → 測試 → Git main → 安全部署 / 回報」流程穩定串起來，並避免 Antigravity / Codex 同時跑大型 pytest / build 造成 NAS OOM。
  - GitHub 目前能證明架構與開發節點已存在；NAS 容器此刻是否 running 仍需以 NAS runtime / Docker 狀態實際確認。

## 待新增 / 待執行主題總覽

> 這一區固定放在 Roadmap 最前面，用來快速確認「還有哪些功能尚未執行」。  
> 完成後改成 `[x]`；尚未開始或尚未完成維持 `[ ]`。細節保留在下方對應章節。

- [ ] **正式當沖完整交易日 LIVE Validation**
  - Market Risk 全日證據 + Research/Paper 自然超額案例；程式已 CODE VERIFIED / VM DEPLOYED，現在等待 live evidence。
- [ ] **當沖學習 / 研究系統持續執行**
  - Research Governance 已進入 Pristine Holdout；`PHASE2C_FUTURE_60D` 自 2026-10-05 起保留 60 個符合條件交易日，尚未 production-ready。
- [ ] **AI NAS 串聯持續建置**
  - Antigravity + Codex NAS 節點、備份與隔離架構已建立；下一步完成穩定的自動分工、測試、Git 與受保護部署鏈。


- [x] Paper UI 移除模擬累積權益
- [x] 盤後通知移除模擬累積權益
- [x] 長期績效改為 `cumulative_net_pnl`
- [x] legacy equity 僅保留 DB migration compatibility
- [x] 首頁移除 Gemini / OpenAI AI 燈號
- [x] Provider Health 公開只留 4 個核心來源
- [x] 首頁 LOGO 壓縮 / 尺寸 / cache 優化
- [x] 相關 UI / tests / docs references 清理

- [ ] **【最高優先】Market Risk Gate：程式修正已完成，待完整交易日 LIVE VERIFIED**
  - 2026-09-30 實盤確認：0 ENTRY 並非 AI 模型判錯，而是市場風控層先將候選全部 veto。
  - 盤前 brief 停留在 2026-09-25，9/30 判定 `premarket_missing_or_stale`；盤中即時大盤風控同時出現 `index_quote_missing_or_stale` / `valid=False`。
  - 雷達本身正常，盤中持續有 2～9 檔候選；模型 `research-2026-09-24`、`mode=model`、`ready=True`、threshold 0.6 皆正常。
  - 已確認大量 veto 來自「市場紅燈」，代表目前把資料 stale / API snapshot 無效 / 真實市場風險三種不同情況壓成同一個 RED。
  - 今晚修正方向：盤前資料只做初始風險；09:00 後改由即時市場風控重新判定。
  - Shioaji 與玉山行情需互為 fallback：任一正常就不能因另一個失效而鎖盤；兩者都失效才進 fail-safe RED。
  - 盤前 RED 若盤中連續即時資料證實轉強，可重新校正為 YELLOW / GREEN。
  - 必須將「資料異常」與「市場真的危險」拆成不同狀態，不得共用 RED。
  - 不調整模型 threshold 0.6、不放寬雷達條件；今天資料完整保留作研究樣本，修正後自下一交易日重新驗證。
  - 同步追查 `easystock-premarket.timer/service` 為何 9/29、9/30 未更新盤前 brief。

- [ ] **【高優先】Research / Paper：解耦與 Episode 去重已完成，待自然超額案例 LIVE VERIFIED**
  - 2026-10-01 實盤確認：3189 景碩已通過策略 / 模型 / Market Gate，但因模擬資金不足，Paper Wallet 回傳 `insufficient_cash` 後整筆 position 被丟棄，導致首頁「每日盤後研究摘要」也沒有景碩。
  - 正確原則：`Signal acceptance != Paper execution`。只要策略 / 模型 / Market Gate / 使用者條件 / fresh quote 都通過，就必須建立 Research / Shadow Trade；Paper Wallet 是否有足夠資金只能影響 `paper_execution`，不能決定研究樣本是否存在。
  - Research Trade 必須持續使用真實盤中行情追蹤 entry / exit / highest / lowest / MFE / MAE / stop / take-profit / trailing / force-exit / pnl，供 AI 訓練與盤後摘要使用。
  - Paper 帳戶仍維持真實資金限制，不可改成無限資金；需保留 `paper_execution=SKIPPED`、`paper_skip_reason=insufficient_cash` 等證據。
  - 同一股票允許一天出現多個獨立 Research Trade Episode，但只有在上一筆 Research Position 已 CLOSED，且之後完整 ENTRY 條件重新成立時才能建立下一筆。
  - 同一筆 OPEN Research Position 期間，連續 Tick 再次符合 ENTRY 不得重複建立新 Trade，也不得每 3～7 秒重複寫一筆相同 `insufficient_cash` 略過事件。
  - 2026-10-01 景碩觀察到約 10:33 與 12:07 兩個明顯訊號時段；盤後應以保存的 point-in-time 資料檢查第一筆是否已依策略出場，若已 CLOSED，第二段才可視為新的 Trade Episode。
  - 若要回補 2026-10-01 景碩研究交易，只能使用當時已保存的 Tick / K 線 / ENTRY evidence 重播，不得使用收盤後資訊反推進場，避免 look-ahead leakage。
  - 每日盤後研究摘要需分開顯示：策略有效訊號 / Research Trades / Paper 成交 / Paper 因資金限制未成交，避免資金約束污染模型研究統計。

- [x] **Paper UI 移除模擬累積權益、改用累積淨損益**
  - 本次只記錄，不立即改程式；等下一次 Paper / 後台改版時一次完成。
  - EasyStock Paper 定位改為「每日當沖買進額度」，不是現金本金帳戶。
  - 例如設定 `daily_buy_limit=1,000,000`，代表當日所有 BUY gross 累計最多 100 萬；SELL 不回補當日額度，隔一交易日後自然重新從 0 使用。
  - 後台移除「模擬起始本金 / 目前資金 / 模擬累積權益」等概念，不再顯示類似「模擬累積權益 199,809 元」。
  - 新版只顯示：每日當沖買進額度、今日已使用、今日剩餘、額度使用率、今日淨損益、累積淨損益等績效統計。
  - `initial_capital` / `current_capital` / `starting_cash` / `start_balance` / `end_balance` 等舊欄位可為歷史 migration 相容保留，但不得再控制 Paper BUY，也不得作為新版 UI 的「本金 / 權益」呈現。
  - 不建立 `performance_base` / `paper_equity`；長期績效若需圖表，改用「累積淨損益曲線」，從 0 元起算。
  - 額度只計 BUY 成交本金，不計買進手續費、賣出手續費與證交稅；損益不影響隔日額度。
  - Research Trade 仍與 Paper execution 解耦；超過每日額度只標記 `paper_skip_reason=daily_buy_limit_exceeded`，Research 仍完整追蹤。

- [x] **首頁 LOGO 圖片效能優化**
  - 2026-09-30 發現首頁 LOGO 圖片檔案偏大，首次載入時讀圖時間明顯。
  - 下一輪修正需先確認目前 LOGO 實際檔案尺寸、像素尺寸、格式與瀏覽器解碼成本。
  - 優先在不改變品牌外觀的前提下縮小檔案：重新輸出較小 PNG / WebP / AVIF，或依瀏覽器支援採 `picture/srcset`。
  - 圖片顯示尺寸與實際資源尺寸需匹配，避免首頁載入遠大於實際顯示尺寸的原圖。
  - 保留透明背景與目前「沖」字 / EasyStock 品牌視覺，不因壓縮造成邊緣毛邊或失真。
  - 視需要補 `width` / `height`、preload / fetchpriority 或 cache-busting 調整，但避免過度 preload 阻塞其他首屏資源。
  - 驗收以首頁首屏載入時間、LOGO transfer size、decode/render 正常為準。

- [ ] **手機版底部導覽列改版**
  - 手機版底部改成固定式 5 個主入口。
  - 主入口：盤中摸魚、底部反彈、牛馬 AI、Chrome 小工具、社畜後台。
  - 上方原有主題頁籤仍可保留完整名稱；手機底部採精簡名稱。
  - 桌機版不強制套用同一底部導覽樣式。
  - iPhone 需支援 `safe-area-inset-bottom`，避免 Home Indicator 擠壓。

- [x] **Chrome Extension 1.02：1.01 實盤 BUG 一次性修正**
  - 版本規則確認：1.0X 系列只做 BUG 修正、穩定性與相容性改善；大型新功能不塞入 1.0X。
  - 1.02 已完成程式修正並更新 GitHub main：加權指數高頻刷新、盤中今日未完成日 K、固定分時 X 軸、台北時區、強制刷新、Popup Shell / Skeleton；Chrome 端觸底反彈功能已移除。
  - Chrome 內部版本為 `1.0.2`，對外 `version_name = 1.02`。
  - 尚需：VM 同步後於完整台股交易時段做 1.02 實盤驗證；若仍發現 BUG，下一版依序使用 1.03、1.04…。
  - 不在 1.02 加入 Google 登入、Firebase 使用者同步或 Migration。

- [x] **Chrome Extension 1.03：Google 上架包重整**
  - 以目前正式 Chrome 小工具功能重新打包並升版為 1.03。
  - Chrome 小工具不含觸底反彈；目前主入口為自選、當沖、當沖 AI 架構。
  - 觸底反彈保留在 EasyStock Web 首頁，避免把已移除功能誤加回 Chrome。
  - 使用目前已更新的品牌 ICON，並延續 1.02 既有 Bugfix。
  - Chrome 內部版本為 `1.0.3`，對外 `version_name = 1.03`。
  - Google 登入、Firebase 自選股／設定同步、本機 Migration 仍維持 2.0。

- [x] **Chrome Extension 1.04：恢復觸底反彈同步顯示**
  - 修正 1.03 中 Chrome 觸底反彈功能被移除，導致 Web 首頁已有 3 檔正式候選時，小工具仍無法顯示。
  - 恢復 Chrome 觸底反彈 Tab、卡片列表、策略標的一鍵加入自選。
  - Chrome 優先讀正式 `market_data/rebound_feed`；若正式 feed 尚未可讀，改用與 Web 相同的 `range-rebound-0.3` 引擎，以同 release summary + K 線計算最多 3 檔。
  - Chrome 內部版本 `1.0.4`，對外 `version_name = 1.04`。
  - Google 登入、Firebase 使用者同步、本機 Migration 仍維持 2.0。

- [x] **Chrome Extension 1.05：列表迷你走勢圖時間刻度與盤中日 K 修正**
  - 2026-09-30 實盤確認：自選股列表「走勢」迷你圖仍會把目前已取得的分時資料平均拉滿整個 56px 寬度，沒有依台股交易時段 09:00～13:30 的實際時間位置繪製。
  - 現況程式 `createSparklineSvg()` 使用 `x = 2 + (idx / (count - 1)) * (w - 4)`，因此例如 09:17 只有十幾分鐘資料時，最後一點仍會畫到最右端，看起來像已經走完整天。
  - 修正方向：Sparkline 必須保留每筆分時資料的 timestamp，以固定 09:00～13:30（270 分鐘）換算 X 座標；09:17 的最後一點只能落在整條時間軸前段，未到時段保持空白。
  - X 軸位置以交易分鐘為準，不可再用資料筆數平均分配；中午沒有休市，不需切段。
  - 休市／歷史資料顯示時，需明確定義使用完整交易日比例或最後交易日完整資料，避免盤中與收盤後顯示邏輯混淆。
  - 此項順延為 1.05 Bugfix 候選，不併入 2.0 功能開發。
  - 2026-09-30 追加實盤問題：點進個股 K 線頁後，日 K 最後一根仍停在昨天，盤中沒有顯示今天尚未完成的日 K。
  - 現況雖已有 `mergeTodayPartialDailyBar()` / `FETCH_DAILY` 嘗試用 1 分 K 組今日 OHLC，但實盤仍未成功；需檢查 Yahoo 1m 回傳是否真為今日、marketOpen / holiday gate、Service Worker 回傳格式，以及 fallback 時是否因拿不到今日分時而直接保留昨日最後一根。
  - 修正要求：交易日 09:00 後，只要已有今日有效成交 / 1 分 K，就必須在日 K 模式追加「今日未完成 K 棒」；OHLC / volume 由今日真實分時彙整，不得用昨日資料或假資料補值。
  - 今日 partial K 必須隨盤中刷新更新；收盤後再由正式日 K 取代，且 UI 可標示 partial / 盤中未完成。
  - 需保留每筆 intraday 的交易日期或完整 timestamp，不能只留下 HH:mm，避免把前一交易日的 1 分 K 誤當今日資料。
  - 1.05 完成：Sparkline 改以 09:00～13:30 固定交易時間軸；Yahoo spark / 1 分 K 保留 timestamp、date、time。
  - 1.05 完成：修正 Chrome runtime `{ ok, value }` 的 `FETCH_DAILY` 解包，今日 partial K 僅聚合台北今日有效分時資料。
  - Chrome 內部版本 `1.0.5`，對外 `version_name = 1.05`；重新產生透明紅色「沖」字 16/48/128 PNG，並加入 PNG CRC / zlib 完整性測試。

- [ ] **Chrome Extension 2.0：Google 登入 + Firebase 使用者同步**
  - Google Authentication。
  - 自選股、當沖監控、提醒條件、群組與設定同步。
  - 第一次登入執行本機資料 Migration。
  - 核心原則：只合併、不覆蓋、不刪除。
  - 2.0 才進行登入 / 雲端同步等大型架構變更；1.0X 維持 Bugfix 線。

- [ ] **玉山 API 行情資料源整合（只讀，不交易）**
  - [x] 玉山 API 已完成登入 / WebSocket 連線驗證，可成功訂閱並收到市場資料事件。
  - 玉山 API 僅作為行情 / 市場資料來源，不做自動交易、不送單、不管理持倉。
  - 第一階段補強 AI 當沖即時市場 context：加權指數、櫃買、電子、半導體、金融、電子零組件、航運等市場 / 類股指數。
  - 後續延伸市場廣度、類股強弱、領漲 / 領跌、資金輪動與市場 regime 特徵。
  - 與既有 Shioaji / Fugle / Firebase 資料分層，保留 source / quote_at / received_at / freshness，禁止來源混淆。
  - 新增資料先進 Dataset / Shadow 驗證，不可因接上玉山 API 就直接改變正式 ENTRY / EXIT。
  - 不保存或建立任何玉山交易憑證 / 下單能力；權限以行情唯讀最小化為原則。
  - 尚待完成：正式 provider 模組、資料標準化 / 落地、freshness、API Health 燈號、Dataset / Shadow 整合。

- [x] **當沖制度 / 費稅模擬對齊：CODE VERIFIED / VM DEPLOYED**
  - [x] 2026-09-30 已完成當沖合規 / 制度檢視，文件：`docs/DAYTRADE_COMPLIANCE_REVIEW_2026-09-30.md`。
  - 總體結論：目前屬偏保守的「現股先買後賣」當沖模擬，帳務 / 風控邏輯未發現 bug。
  - 已符合：當沖證交稅 0.15%、手續費、整張交易、當日平倉、內外盤等核心模擬原則。
  - 尚待評估 / 修正偏差：強制平倉時間、允許進場時間、雙稅率處理、當沖資格過濾、漲跌停鎖死、證交稅進位規則。
  - 2026-10-03 已完成正式 execution alignment、regression tests 與 VM canonical deploy；Fresh bid/ask depth、當沖資格、pending unfilled exit、canonical fee/tax path 與 rounding 已落地。
  - 完整規格與官方來源查核見 `docs/DAYTRADE_COMPLIANCE_REVIEW_2026-10-03.md`；此項程式 / 部署已完成，僅 Market Risk 與 Research/Paper 的完整交易日 live evidence 仍待收斂。

- [ ] **觸底反彈 AI 學習**
  - [x] Phase 1：凍結正式 `range-rebound-0.3` Baseline；研究回放不修改正式 feed / Top 3。
  - [x] Phase 1：版本化 Dataset / Feature schema v1，共 26 個特徵；收集 PASSED / PENDING / NEAR_MISS / REJECTED_CONTROL。
  - [x] Phase 1：Historical Backfill 2023-09-04～2026-10-01，共 742 個交易日、100 檔、897 筆 Dataset；D1 open、10 交易日 label、1/3/5/10/20D outcome、MFE / MAE 已完成。
  - [x] Phase 1：私有 SQLite `/home/ubuntu/easystock-learning-data/rebound/dataset.sqlite`、每日 22:30 收集 / label timer、Dataset Audit / leakage guard 已完成；future leakage 0、duplicate 0、critical 0。
  - [ ] **Phase 1.5：資料補強**：K 線 coverage 由目前 58.23% 補到至少 90%，優先補齊歷史行情缺口。
  - [ ] Phase 1.5：建立可 point-in-time 重建的歷史 Market Context（TAIEX / OTC / 類股日資料、stock vs market / sector、market regime）；不得把今天的玉山即時資料倒灌過去。
  - [ ] Phase 1.5：補歷史財務 point-in-time / publication date；無法證明當時已公開的財務資料維持 null，不可 future leakage。
  - [ ] Phase 1.5：維持兩個研究 profile：`rebound-tech-v1`（技術 + 量價 + Market Context）與 `rebound-full-v1`（再加 Financial PIT），避免財務 PIT 不足阻塞全部研究。
  - [ ] Phase 1.5：重跑 Backfill / Labels / Audit，成熟可訓練樣本目前 237 筆，先累積到至少 500～1,000 筆再做正式模型比較。
  - [ ] Phase 1.5：TIMEOUT 目前 154 / 237，Phase 2 前需評估三分類（SUCCESS / FAIL / TIMEOUT）或兩階段模型，避免只做 SUCCESS vs FAIL 丟掉大部分樣本。
  - [ ] Phase 2：Baseline / Logistic Regression / HistGradientBoosting 正式比較；目前只允許 pipeline sanity check，不得 Candidate / Shadow。
  - [ ] Phase 2：Walk-forward + 10 交易日 embargo + holdout；以相同 Top 3 訊號數比較 Target Hit Rate、5D / 10D return、MFE / MAE、PF、Drawdown、Brier。
  - [ ] Phase 2：Shadow 驗證，再決定是否 Applied；不自動晉升。

- [ ] **永豐實盤當沖後台（Owner-only）**
  - 第一階段先建立獨立「永豐實盤當沖」分頁 / Tab，僅在 Google 登入且通過既有 Owner/Admin 驗證後顯示。
  - 未登入時首頁 / 後台導覽都不顯示入口；即使直接輸入 route 或呼叫 API，也必須由後端強制回 401 / 403，不能只靠前端隱藏。
  - 第一版只做安全入口與 UI / backend skeleton：券商狀態、實盤模式 OFF、AUTO OFF、今日持倉 / 委託 / 成交 / 損益、帳戶設定與 KILL SWITCH placeholder。
  - 未來正式接永豐後，持倉區要顯示目前持有股狀態：股票、數量、均價、現價、未實現損益、報酬率、持倉來源 / 策略、持有時間、可賣數量與券商同步時間。
  - 持倉區新增 Owner-only 手動「賣出」入口，可針對單一持股執行全數或指定數量賣出；送單前需再次確認帳戶 / 持倉 / 可賣數量 / 價格類型，並寫入 audit / live ledger。
  - 手動賣出與 AUTO EXIT 必須共用同一套 broker reconciliation / order / deal / ledger 流程，避免兩套帳務。
  - 第一版所有交易按鈕預設 disabled，不處理真實 API Key / CA、不啟用 LIVE AUTO、不送任何真實委託。
  - 預留未來模式：OFF / SHADOW / PAPER / LIVE AUTO。
  - 永豐 API / CA 憑證安全持久化。
  - AUTO ON / OFF、Auto Resume、KILL SWITCH。
  - 真實委託 / 成交 / 持倉 Reconcile。
  - 獨立 `live_trade_*` 帳本。
  - 今日交易、損益、手續費、稅與歷史報表。
  - 今日 PnL、單筆交易、Equity Curve 圖表。
  - PAPER vs LIVE 執行差異比較。

- [x] **首頁 AI 復盤改版：淘汰舊 OpenAI 每日文字復盤**
  - 已完成：首頁改為「每日盤後研究摘要」，主要讀取 `daytrade_learning_status` / `research_summary`，不再以 `dual_review_status` 作為主要狀態來源。
  - 2026-10-03 補充：目前盤後 AI 不直接改變正式策略 / 交易決策，公開首頁不再需要 AI 在線 / 離線 / Provider 燈號；研究資料可繼續保留，但 AI 狀態僅在 Owner / Admin 需要時查看。
  - 已加入 stale / freshness 判斷，過期資料不再顯示成目前正常狀態。
  - 已顯示可驗證的交易、樣本、Label、模型、runtime 與 validation 指標；沒有資料時明確顯示待資料 / 待確認。
  - AI 改為每週 Architecture Review 或異常觸發分析，不再每天固定產生文字復盤。
  - 已完成 GitHub main → VM canonical deploy 與 release identity 驗收；VM / origin/main / GitHub main SHA 已一致。

- [ ] **API / 資料源健康燈號**
  - 首頁新增脫敏後的 API / 資料源狀態，只顯示真正影響首頁 / 行情可用性的核心資料服務。
  - 第一階段包含：永豐行情、玉山行情、Fugle、Firebase。
  - **首頁不顯示任何 AI Provider / AI 盤後 / AI Review 燈號**；目前 AI 盤後不直接影響正式交易或首頁核心功能，AI 詳細狀態僅保留 Owner / Admin 後台。
  - LINE / Telegram 不放首頁公開燈號，僅保留在 Owner / Admin 後台自行查看。
  - 公開狀態統一為 ONLINE / DEGRADED / OFFLINE / UNKNOWN；收盤後行情源可顯示 MARKET CLOSED，不誤判離線。
  - 判定以實際資料 freshness / 最近成功資料時間為主，不只看 HTTP 200 或 WebSocket 是否仍連線。
  - 首頁只顯示脫敏摘要；詳細 latency、error code、reconnect、連續失敗等資訊只放後台。
  - 不公開 API Key、Token、帳號、broker account、完整 endpoint、VM / IP、憑證細節、stack trace 或精確 quota。

- [ ] **AI Architecture Guardian 系統健檢**
  - 每日 Tests / CodeQL / Secret Scan / Dependabot / Trivy / 自訂安全規則。
  - 每週 AI Architecture Review。
  - 不在公開首頁放 AI / Guardian 狀態燈；結果與 Critical / High / Medium / Low 詳細報告放 Owner / Private Admin。
  - 第一階段只掃描、分析、報告、通知，不直接修改交易系統。

- [ ] **GitHub / 模型核心保護與 Public / Private Core 拆分**
  - Public repo 只保留網站、Chrome UI 與必要 API Client。
  - 策略、模型、訓練、交易、Shioaji、風控移入 Private Core。
  - 移除 `raw.githubusercontent.com` 等直接 GitHub 關聯。
  - Public repo 採乾淨 Git history，避免舊 commit 持續暴露核心程式。



---

## 當沖學習 / Research Governance（持續執行，2026-10-05）

### 現況
- Phase 2A / 2B / 2C 的歷史研究已建立，但 Phase 2C 不是 production-ready。
- 已加入 Research Trial Ledger、Objective Function Governance、OOS Consumption Ledger、Dataset Registry 與 Pristine Holdout Policy。
- `PHASE2C_FUTURE_60D` 為未曝光確認保留區：自 2026-10-05 起收集前 60 個符合條件交易日。
- 在正式 one-shot unseal 前，禁止讀取該 holdout 的 performance / outcome，避免把未曝光樣本耗損成另一組 discovery data。
- 目前治理狀態維持：
  - `PRODUCTION_READY=false`
  - `INDEPENDENT_CONFIRMATION=false`
  - 未曝光未來資料保持 pristine / untouched。

### 原則
- Research 可以持續收集、標記、治理與離線分析。
- 不得因研究結果漂亮就直接 Promote / Applied。
- 正式策略 / runtime 與 Research Governance 保持隔離。
- 未曝光確認只允許一次正式評估；若評估後再調參，必須建立新的未曝光樣本，不得重用同一 60 日 holdout 宣稱獨立確認。

---

## Market Risk Gate 修正（2026-09-30）

### 問題定義
本次屬於 Market Risk Gate bug，不是 AI 模型 performance 問題。

2026-09-30 的實盤證據顯示：
- 盤前資料仍停留在 2026-09-25。
- 9/30 沒有新的 premarket brief，導致 `premarket_missing_or_stale`。
- 盤中即時市場風控另出現 `index_quote_missing_or_stale` / `valid=False`。
- 雷達 11:07～11:10 持續可抓到 2～9 檔候選，Shioaji 個股行情、爆量雷達、Top 候選流程正常。
- 模型為 `research-2026-09-24`，`mode=model`、`ready=True`、threshold 0.6，模型本身正常啟動。
- 大量策略評估在進入模型前就被「市場紅燈」 veto，因此最終 0 ENTRY。

### 已確認的錯誤行為
目前系統把以下不同事件壓成同一個 RED：
1. 盤前資料 stale。
2. 即時 index quote 缺失 / stale / snapshot 無效。
3. 市場本身真的進入高風險狀態。

這三者不應共享同一個交易語意。

核心原則：
> 資料異常 != 市場真的危險。

### 正確架構
```text
08:35 盤前資料
   │
   └── 只做初始風險
             ↓
09:00 開盤
             ↓
      即時市場風控
       ↙          ↘
 Shioaji       玉山 API
 加權指數      加權 / 櫃買 / 類股
       ↘          ↙
       資料品質檢查
             ↓
       Market Risk
             ↓
 GREEN / YELLOW / RED
```

### Fallback 規則
- 盤前資料 stale：
  - 不直接等同市場 RED。
  - 標示資料品質異常 / UNKNOWN / DEGRADED。
- Shioaji 大盤失效但玉山正常：
  - 使用玉山。
  - 不鎖盤。
- 玉山失效但 Shioaji 正常：
  - 使用 Shioaji。
  - 不鎖盤。
- Shioaji + 玉山都失效：
  - 才進 fail-safe RED / BLOCK。
- 盤前 RED，但盤中連續即時資料證實市場轉強：
  - 允許重新校正成 YELLOW / GREEN。
- 所有 Market Risk 狀態都需保留來源、quote_at、freshness 與判定原因。

### 本次不調整
不要因 0 ENTRY 去改：
- 模型 threshold 0.6。
- 爆量 >= 1.4x。
- 主動買盤 >= 52%。
- 60 秒量 >= 10。
- 60 秒成交額 >= 150 萬。
- 漲幅上限 8%。

雷達與模型不是本次根因。

### 盤前任務追查
需檢查：
- `easystock-premarket.timer`
- `easystock-premarket.service`
- 9/29、9/30 是否有執行失敗。
- calendar gate 是否誤判。
- Firebase publish 是否失敗。
- premarket brief 是否寫入了其他節點 / release。
- credential / network / API error。
- service exit code 與 journal。

### 驗收條件
修正完成後至少確認：
1. premarket stale 不會直接造成全市場 RED。
2. Shioaji / 玉山任一來源正常即可提供市場 context。
3. 兩個即時來源都失效才觸發 fail-safe。
4. 盤前風險可以被盤中可靠資料重新校正。
5. RED 必須代表真實市場風險，而不是單純資料缺失。
6. 今日 9/30 資料完整保留作研究樣本。
7. 下一交易日重新做完整盤中驗證。

---

## Research Trade 與 Paper Wallet 解耦 + Trade Episode 去重（2026-10-01）

### 問題一：Paper 資金限制污染 Research / AI 樣本
2026-10-01 實盤案例：3189 景碩通過正式 ENTRY 條件，但一張成本超過目前模擬可用現金，因此 Paper Wallet 回傳 `insufficient_cash`。現行 `PositionManager.open_position()` 在 `before_open` 沒有 `status=bought` 時直接 return，後續 `learning.entry()`、EXIT、MFE / MAE 與盤後研究摘要全部遺失。

核心原則：

```text
Signal acceptance
!=
Paper execution
```

只要通過：
- Market Gate
- Strategy
- Model（model mode 時）
- 使用者價格 / 漲幅等正式 ENTRY 條件
- fresh quote

就必須建立資金獨立的 Research / Shadow Position。

Paper Wallet 另行判斷：
- `paper_execution=FILLED`
- `paper_execution=SKIPPED`
- `paper_skip_reason=insufficient_cash`

Paper 帳戶仍維持真實資金、整張、費稅與部位限制，不可用無限資金假裝成交。

### Research Trade 需要完整追蹤
Research Position 需使用真實 point-in-time 行情持續計算：
- entry_time / entry_price
- highest_price / lowest_price
- MFE / MAE
- stop loss
- take profit
- trailing / breakeven
- strategy exit
- force exit
- exit_time / exit_price
- pnl_pct
- decision_mode / model_version / model_score / threshold
- paper_execution / paper_skip_reason

首頁「每日盤後研究摘要」需至少能區分：
- 策略有效訊號數
- Research Trades 數
- Paper 實際成交數
- Paper 因資金限制略過數
- Research win / loss / pnl / MFE / MAE / exit reason

AI 訓練 / 研究以 Research Trade 為主要交易結果證據，不能只看 Paper Wallet 是否買得起。

### 問題二：同股連續 Tick 不得重複建單
景碩資金不足時，目前後台可看到每數秒重複寫：
`略過：可用現金不足以支付一張買進成本與手續費`

這代表同一訊號 episode 被反覆嘗試，不應拿來當多筆研究交易或大量重複事件。

正確 Trade Episode：

```text
第一次完整 ENTRY 成立
        ↓
Research Trade #1 OPEN
        ↓
OPEN 期間再次出現 ENTRY
        ↓
不建立新 Trade
只更新既有 Position
        ↓
EXIT 條件成立
        ↓
Research Trade #1 CLOSED
        ↓
之後完整 ENTRY setup 再次成立
        ↓
Research Trade #2 OPEN
```

### 同股再進場規則
Research 層允許同股同日多次交易，但需同時滿足：
1. 上一筆 Research Trade 已 CLOSED。
2. 新 ENTRY 是之後重新成立的有效 setup。
3. 不可把同一持續訊號的多個 Tick 視為不同交易。
4. 每一筆需有獨立 trade_id / episode_id。
5. Paper 是否允許 re-entry 可保留自己的風控設定，不必與 Research 完全相同。

2026-10-01 景碩約在：
- 10:33～10:34
- 12:07 左右

出現兩個明顯訊號時段。盤後僅可利用當時已保存資料判斷：若第一筆在第二段之前已依現行 exit 規則 CLOSED，12:07 才能建立第二個 Research Episode；否則仍是第一筆 OPEN Position 的再次訊號。

### Log 去重
同一 Research Episode 若 Paper 因相同原因無法成交：
- 第一次記錄 `paper_skip_reason=insufficient_cash`。
- 後續相同 Tick / 相同 episode 不再每數秒重複寫相同略過 log。
- 若上一筆 CLOSED、建立新 episode，才可重新記錄一次該 episode 的 Paper execution 結果。

### 歷史回補原則
若回補 2026-10-01 景碩：
- 必須使用當時已保存的 tick / bar / model / gate / entry evidence。
- 從原本 ENTRY 時點開始順序重播。
- 不得使用收盤價或未來 K 棒決定過去是否進場。
- 無足夠 point-in-time evidence 時寧可標記不可回補，不得製造假 Research Trade。

### 驗收
至少新增 regression tests：
1. `insufficient_cash` 不會阻止 Research Position 建立。
2. Paper current_capital 不會被 Research Trade 修改。
3. Research Position 仍可正常 exit 並產生 pnl / MFE / MAE。
4. Paper filled 時只產生一筆 Research Trade，不重複。
5. 同一 OPEN episode 連續 ENTRY Tick 不新增第二筆。
6. 第一筆 CLOSED 後，完整 ENTRY 重新成立可建立第二筆。
7. 同 episode 的 `insufficient_cash` log 只記一次。
8. 盤後摘要能同時顯示 Research Trade 與 Paper execution 統計。
9. model / strategy / market gate 拒絕的標的不應被偽造成 Research Trade。
10. root 與 `vm_runtime` 對應邏輯不得 drift。

---

## 下一版 Paper 模擬：每日當沖買進額度制（待下一次改版一次完成）

### 定位
Paper Trading 不再模擬「有一筆本金、買進扣現金、賣出補回現金」的現金帳戶，而是模擬固定的每日當沖買進額度。

```text
daily_buy_limit
      ↓
今天 BUY gross 累計
      ↓
daily_buy_used
      ↓
daily_buy_remaining
```

範例：每日額度 1,000,000 元，今日先買 300,000 元後即剩 700,000 元；即使該筆之後賣出，當日剩餘額度仍為 700,000 元。下一交易日依當日 BUY fills 自然重新從 0 使用，不另做午夜 reset job。

### 下一版一次移除的舊概念
公開 / Admin UI 不再顯示：
- 模擬起始本金。
- 目前模擬帳戶資金。
- 可用現金。
- 模擬累積權益。
- 任何由 PnL 推導出的「目前本金 / Equity」。

尤其目前類似「模擬累積權益 199,809 元」的顯示，在下一版一併移除。

舊 DB 欄位如 `initial_capital`、`current_capital`、`starting_cash`、`start_balance`、`end_balance` 可因 migration / 歷史相容暫留，但不能再作為 BUY gate 或新版 UI 語意。

### 新版後台
至少顯示：
- 每日當沖買進額度。
- 今日已使用額度。
- 今日剩餘額度。
- 今日額度使用率。
- 今日已實現損益。
- 今日手續費。
- 今日證交稅。
- 今日淨損益。
- 累積淨損益。

若保留長期圖表，使用「累積淨損益曲線」，基準從 0 元開始，不再做虛擬 Equity Curve。

### 額度規則
- `daily_buy_used = SUM(BUY gross)`。
- BUY 手續費不吃額度。
- SELL 金額不回補額度。
- SELL 手續費 / 稅不影響額度。
- 今日 / 歷史 PnL 不改變明日 `daily_buy_limit`。
- 額度不足時 Paper 標記 `daily_buy_limit_exceeded`。
- Research Trade 不受 Paper 額度限制，仍完整追蹤 ENTRY / EXIT / MFE / MAE / PnL。

### 實作時機
本項 **2026-10-03 只記錄，不立即修改**。等下一次 Paper / Admin 改版時，連同 DB migration、後台 UI、盤後摘要與 regression tests 一次完成，避免分兩次改動帳務語意。

---

## 首頁 LOGO 圖片效能優化

### 問題
首頁目前 LOGO 圖片疑似檔案偏大，首次進站時讀圖時間較長，影響首屏體感。

### 修正方向
1. 先確認目前 LOGO：
   - 原始檔案大小。
   - 像素尺寸。
   - 顯示尺寸。
   - PNG / WebP / AVIF 等實際格式。
   - 是否重複載入或被不同 URL / cache bust 重新下載。
2. 保留現有品牌視覺與透明背景，重新輸出適合首頁顯示尺寸的輕量版本。
3. 優先避免「顯示 100px，但下載 1000px+ 原圖」。
4. 若不影響相容性，可提供 WebP / AVIF，並保留 PNG fallback。
5. HTML 明確提供 `width` / `height`，避免 layout shift。
6. 僅在確定 LOGO 為首屏關鍵資源時使用 preload / fetchpriority；不得讓大圖 preload 反而拖慢 CSS / JS。
7. 保留正確 cache 行為，版本更新時才換資源 hash / query。

### 驗收
- 視覺與目前 LOGO 一致。
- 透明背景與邊緣正常。
- transfer size 明顯下降。
- 首次載入不再因 LOGO 長時間空白 / 延遲。
- 不造成 CLS 或其他首屏資源退化。

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

## 目前版本：Chrome Extension 1.03（1.0X Bugfix 線）

### 目標
- 1.02 專門處理 1.01 實盤累積 BUG，不加入登入 / 雲端同步等大型功能。
- GitHub main 完成修正後同步 VM，再以完整交易時段做實盤驗證。
- 若實盤仍出現 BUG，沿用 1.03、1.04…逐版修正，直到 1.0X 穩定線完成。

### 版本編號規則
- `1.01 / 1.02 / 1.03 / 1.04 ...`：Bugfix / 穩定性 / 資料正確性 / UI 相容性修正。
- 1.0X 不加入 Google 登入、Firebase 個人資料同步等大型架構功能。
- `2.0`：Google 登入 + Firebase 使用者同步 + 第一次登入本機資料 Migration。
- 未來若 2.0 上線後仍只是修 BUG，再依既定版本策略使用對應 patch 版本，不把 BUG 修正與大型功能混在同一版。

### 優先驗證項目
- 盤中掃描是否正常。
- 當沖 / 隔日沖資料是否正確更新。
- Chrome 通知是否正常觸發。
- 股票資料更新時間與首次出現時間是否正確。
- VM / Firebase / API / Chrome Extension 間資料同步是否穩定。
- 開盤時可能出現的效能、延遲與例外狀況。

### 1.02 已修正的 1.01 Chrome 小工具 BUG
> 下列保留 1.01 的問題背景與 1.02 修正方向。程式修正已進 GitHub main；完成 VM 同步後再做開盤實測。
\n1. ✅ **加權指數更新時間**
   - 目前 `fetchTaiexIndex()` 雖直接抓 TWSE MIS，但 `feedCache` 共用 `TTL = 5 分鐘`。
   - 盤中加權指數不應使用 5 分鐘快取。
   - 修正方向：盤中獨立成約 10～30 秒更新頻率。
   - UI 顯示實際來源時間，例如 `資料時間 09:08:25`，避免只顯示畫面刷新時間。
\n2. ✅ **個股日 K 盤中仍顯示昨日**
   - 目前歷史日 K 優先使用 Yahoo `interval=1d`，盤中不保證提供今日尚未完成的日 K。
   - 修正方向：歷史日 K + 今日即時 / 分時 OHLC 合併。
   - 09:00～13:30 顯示「今日未完成 K 棒」；收盤後再轉成正式日 K。
   - 不可用假資料補今日 K。
\n3. ✅ **分時走勢圖 X 軸跟著目前資料長度拉伸**
   - 現在 `drawIntraday()` 依 `visibleCount` 計算 X 軸，所以早盤幾分鐘資料會撐滿整張圖。
   - 修正方向：台股日盤 X 軸固定 `09:00～13:30`。
   - 09:30 永遠落在固定時間位置，不因目前只有 30 分鐘資料而跑到最右端。
   - 現在時間之後的區段保持空白，直到新資料逐步填入。
   - 建議固定主要刻度：`09:00 / 10:00 / 11:00 / 12:00 / 13:00 / 13:30`。
\n4. ✅ **個股列表右側時間疑似 +8 時區錯誤**
   - 現象：個股右側時間與台灣實際時間不一致，疑似多加 8 小時。
   - 前端目前優先使用 `q.time`，否則才解析 `updated_at`。
   - 後端 `public_feed.py` 的 `updated_at` 已使用 `datetime.now(TPE).isoformat()`，本身已帶 `+08:00`。
   - 檢查方向：確認 `q.time` 來源、UTC / TPE 是否被重複轉換，以及前端是否對已帶 `+08:00` 的時間再次手動加時區。
   - 修正原則：後端輸出明確含 offset 的 ISO 8601；前端統一只轉一次 `Asia/Taipei`，禁止手動再 +8。
\n5. ✅ **右下角重新整理不是實際強制刷新**
   - 現象：例如 00878 可能有更新，但 2330 台積電按重新整理沒有反應。
   - `btn-refresh` 會送 `SNAPSHOT refresh:true`，但 `feeds(now, true)` 進入後仍先檢查 5 分鐘 `feedCache`，所以可能直接回舊資料。
   - `enrichMissingQuotes()` 目前只補缺報價 / 缺漲跌幅；若舊報價的 `price` 與 `change_pct` 仍是有效數字，即使已過期也不會重新抓。
   - 修正方向：使用者手動按重新整理時必須真正 bypass cache，重新抓 public feed / 大盤，並依每檔股票 freshness 判斷是否需要重抓即時行情。
   - 不可只判斷欄位「有值」，還必須判斷 `updated_at / quote_at` 是否新鮮。
\n6. ✅ **Chrome Popup 初次開啟白屏並縮到最小**
   - 現象：點擊 Chrome 小工具後，資料讀取期間整個介面先呈現白色、很小的 Popup，等資料回來後才恢復完整尺寸。
   - 目前 `popup.js` 初始化最後直接 `await act({ type: 'SNAPSHOT', refresh: true })`，完整畫面要等待遠端資料後才 render。
   - Popup CSS 目前固定寬度約 440px，但沒有固定 / 最低高度，因此資料尚未渲染時 Chrome 會依當下少量內容縮小 Popup。
   - 修正方向：
     - HTML 初始即提供完整 Shell / Skeleton 畫面。
     - 設定合理 `min-height` 或固定初始高度，避免 Popup 尺寸跳動。
     - 開啟時先立即 render 快取 / placeholder，不阻塞 UI。
     - `SNAPSHOT` 改背景非阻塞更新，資料回來後再局部更新。
     - Loading 階段延續目前深色 / 淺色主題，不應出現突兀純白閃屏。
\n7. ✅ **首頁有觸底反彈但 Chrome 小工具沒有顯示**
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

## Chrome Extension 2.0 規劃

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

## 玉山 API 行情資料源整合規劃

### 定位
玉山 API 在 EasyStock 中只扮演「行情 / 市場資料供應者」，不做交易。

禁止用途：
- 不送出買進 / 賣出委託。
- 不建立自動交易。
- 不管理券商持倉。
- 不把玉山帳戶憑證做成交易權限。
- 不因資料源接通而直接改變正式 ENTRY / EXIT。

### 目前狀態
- 已完成玉山 API 登入驗證。
- WebSocket 已成功連線。
- 已成功送出市場資料訂閱並收到 subscribed / heartbeat 等事件。
- 2026-09-30：正式只讀 Provider、七個已驗證價格指數、重連與 freshness、本機 market context / Dataset snapshot 已完成；詳見 [行情與健康狀態](MARKET_DATA_HEALTH.md)。新 feature 尚未加入正式模型。

### 第一階段資料
優先收集：
- 加權指數。
- 櫃買指數。
- 電子類。
- 半導體類。
- 金融類。
- 電子零組件類。
- 航運類。
- 其他後續確認對當沖有價值的市場 / 類股指數。

### AI 用途
玉山資料先作為市場 context / feature，不直接作為交易訊號。

初期可加入：
- index_return_1m / 5m / 15m。
- sector_return_1m / 5m / 15m。
- sector_vs_market_strength。
- intraday_market_regime。
- 大盤 / 櫃買同步或背離。
- 個股相對所屬類股強弱。

後續延伸：
- 上漲 / 下跌家數。
- 漲停 / 跌停家數。
- 創高 / 創低家數。
- 成交量 / 成交金額廣度。
- 類股領漲 / 領跌排名。
- 資金輪動。
- 市場 breadth / risk-on / risk-off。
- 類股 regime 與強弱切換。

### 資料治理
不同來源必須保留來源身分，不可混成「同一筆行情」：
- source
- symbol / index_code
- quote_at
- received_at
- freshness
- sequence / event id（若來源提供）
- schema_version

與既有 Shioaji / Fugle / Firebase 整合時，必須能知道：
- 哪一個來源提供哪一欄。
- 哪個來源優先。
- 來源失效時是否 fallback。
- fallback 後 UI / AI 是否能辨識來源已改變。

### AI 導入原則
流程：
```text
玉山即時市場資料
      ↓
標準化 Market Context
      ↓
Dataset 記錄
      ↓
離線研究 / Shadow
      ↓
確認有增益
      ↓
才考慮加入正式模型 Feature
```

禁止：
```text
接上玉山 API
→ 當天直接改模型
→ 當天直接影響 ENTRY
```

所有新增 Feature 必須經過：
- point-in-time 檢查
- missing / stale 處理
- walk-forward / holdout
- 與現有 baseline 比較
- Shadow 驗證

---

## 當沖制度 / 費稅模擬對齊（2026-09-30）

### Review 文件
- `docs/DAYTRADE_COMPLIANCE_REVIEW_2026-09-30.md`
- 本次 Review 僅整理現況、偏差與建議，未修改正式程式碼。

### 總體結論
目前 EasyStock 當沖模擬偏向保守的「現股先買後賣」模式；帳務 / 風控邏輯本身未發現 bug。

### 已符合的主要項目
- 當沖證交稅 0.15%。
- 手續費計算。
- 整張交易。
- 當日平倉。
- 內外盤等相關模擬邏輯。

### 尚待對齊的偏差
- 強制平倉時間。
- 允許進場時間。
- 雙稅率處理。
- 當沖資格過濾。
- 漲跌停鎖死。
- 證交稅進位規則。

### 實作原則
後續若執行修正：
1. 先確認台股現行交易制度與券商實際規則。
2. Paper / Research / Live 共用一致的費稅與交易資格定義。
3. 不改寫既有歷史 ledger；若口徑變更，以版本欄位區分。
4. 新增 regression tests，覆蓋費稅、平倉時間、資格與漲跌停限制。
5. 實盤模組上線前必須完成這一輪對齊。

---

## 觸底反彈 AI 學習規劃

### 目前先決問題：統一正式策略定義
現況存在兩套不同的「觸底反彈」邏輯：
- `scan_rebound.py`：以 MA20 大幅乖離、突破昨高、紅 K、5 日反彈等條件為主。
- `assets/rebound-engine.js`：以重複支撐 / 壓力區、近期回測支撐、突破或止跌確認、ATR、風報比、失效價與目標價為主。

AI 上線前必須先統一正式定義，避免同一個「rebound」標籤混用兩套不同策略造成學習污染。

目前規劃優先以較完整的 `range-rebound` 邏輯作為正式基準，之後將核心演算法搬到 VM / Python，前端 JS 只負責顯示。

### Phase 1 實作結果（2026-10-01）

Phase 1 已完成並部署：
- Baseline：`range-rebound-0.3`，正式 Web / Chrome / Top 3 未被研究管線修改。
- 私有 Dataset：`/home/ubuntu/easystock-learning-data/rebound/dataset.sqlite`。
- Dataset / Feature schema：v1，共 26 個特徵。
- Candidate kinds：PASSED / PENDING / NEAR_MISS / REJECTED_CONTROL。
- Historical Backfill：2023-09-04～2026-10-01，共 742 個交易日、100 檔、43,210 個有封存行情的股票交易日。
- Dataset rows：897。
- 成熟 Label：SUCCESS 29、FAIL 54、TIMEOUT 154、AMBIGUOUS 0；成熟且可訓練 237，UNLABELED 660。
- K 線 coverage：58.23%；已有 K 線之 volume coverage 100%。
- Historical Financial PIT coverage：0%。
- Historical Market Context coverage：0%。
- Near Miss：89（net_rr 87、距支撐 2）；明確淘汰股票以 deterministic control sample 分開保存。
- Leakage Audit：future leakage 0、duplicate ID 0、critical 0、warning 6。
- 研究排程：交易日 22:30（Asia/Taipei）自動執行。
- Phase 1 完成 commit / deploy：`31a4170b170a82b8df9ce8a96e0fd3143ddd2113`；VM HEAD / origin/main / release-info 一致，failed systemd units = 0。
- 尚未訓練任何正式 Rebound AI 模型，尚未啟用 Shadow。

### Phase 1.5：資料補強（正式 Phase 2 前）

目前主要瓶頸不是模型程式，而是 point-in-time coverage 與成熟樣本數。

優先順序：
1. **K 線 coverage**：目前 58.23%，先補到至少 90%。不得用 future-adjusted / 不可驗證資料污染歷史 replay。
2. **Historical Market Context**：以歷史日資料建立可重建的 TAIEX / OTC / 類股 context，不依賴今天才接上的即時玉山資料。
3. **Historical Financial PIT**：必須保存真正 publication / filing date；只有能證明在 signal_date 當時已公開的數值才能進 feature。
4. 重跑 Backfill / Label / Audit，持續由每日 timer 累積 forward samples。
5. Mature trainable rows 目前 237；正式模型比較前目標先累積到至少 500～1,000 筆。

建議第一批 Historical Market Context：
- taiex_return_1d / 5d / 20d
- otc_return_1d / 5d / 20d
- stock_vs_market_5d / 20d
- sector_return_5d
- stock_vs_sector_5d
- market_regime

研究 profile 分開：
- `rebound-tech-v1`：技術面 + 量價 + 可驗證 Market Context。
- `rebound-full-v1`：上述特徵 + 可驗證 Financial PIT。

若 Financial PIT 尚未完整，不應阻擋 technical profile 繼續累積與研究，但不得把目前最新財務資料倒灌到歷史 signal_date。

目前成熟 Label 分布中 TIMEOUT 為 154 / 237，約佔多數。Phase 2 不應直接只做 SUCCESS vs FAIL 二分類而丟棄 TIMEOUT。正式模型設計前需比較：
- 三分類：SUCCESS / FAIL / TIMEOUT。
- 或兩階段：先判斷 10 日內是否產生明確結果，再對有結果樣本判 SUCCESS vs FAIL。

在 Phase 1.5 完成前，只允許模型 pipeline / feature sanity check；不可稱為 Candidate、不可上 Shadow、不可影響正式 rebound_feed。

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

資料成熟度與目前決策：
- Phase 1 已完成 Historical Bootstrap 與 leakage audit。
- 目前 K 線 coverage 58.23%、成熟可訓練 237 筆，尚不足以可靠比較完整 Baseline / Logistic / HistGradientBoosting。
- Phase 1.5 先將 K 線 coverage 補到至少 90%，並補可驗證 Market Context / Financial PIT。
- Mature trainable rows 先累積到至少 500～1,000 筆，再進正式 Walk-forward 模型比較。
- 每日 forward data 繼續自動累積；歷史 Bootstrap 只能使用 signal_date 當時可取得的資料。
- 通過 walk-forward / holdout / forward shadow 才能 Applied。
- 必須避免 future leakage、current-universe bias 與不同 strategy_version 混用。

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

### 第一階段：Google Owner 登入後才可見的實盤分頁

先建立「永豐實盤當沖」獨立分頁 / Tab，作為未來真正接永豐線上當沖的固定入口。

顯示與存取原則：
- 未登入 Google：不顯示此分頁入口。
- 已登入 Google 但不是既有 Owner / Admin：不顯示且不可進入。
- Google Owner 登入成功：才顯示「永豐實盤當沖」。
- 不可只靠前端 `display:none`；直接輸入 route 仍必須驗證 session / Owner。
- 所有未來 `/api/live/*` 或等價實盤 API 都必須再次由後端驗證 Owner 權限。
- 未登入應回 401；已登入但非 Owner 應回 403。

第一版 UI 骨架：

```text
永豐實盤當沖

券商狀態        尚未啟用
實盤模式        OFF
自動交易        OFF

帳戶設定        尚未開放
連線永豐        尚未開放

今日持倉        --
今日委託        --
今日成交        --
今日淨損益      --

KILL SWITCH     placeholder / disabled
```

第一版安全限制：
- 所有可能造成券商動作的按鈕預設 disabled。
- 不保存或要求真實 Shioaji API Key / Secret / CA。
- 不登入實際券商交易 session。
- 不啟用 `LIVE AUTO`。
- 不送出任何真實委託。
- 不因此修改現行 Paper / Shadow / AI ENTRY 邏輯。

未來模式預留：

```text
OFF
SHADOW
PAPER
LIVE AUTO
```

回歸測試至少覆蓋：
1. 未登入時 Tab 不可見。
2. 未登入直接開 route 被拒。
3. 非 Owner 被拒。
4. Owner 登入後才可見。
5. 未授權直接呼叫 live API 被拒。
6. 預設 `LIVE AUTO=false` / OFF。
7. 第一版不存在任何可成功送出真實委託的執行路徑。

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

### 持有股狀態與 Owner 手動賣出

永豐實盤分頁正式接 Broker 後，需有獨立的「目前持有股」區塊，資料以永豐實際持倉為最高權威。

每筆持倉至少顯示：
- 股票代號 / 名稱。
- 持有數量。
- 可賣數量。
- 平均成本。
- 目前價格。
- 未實現損益。
- 未實現報酬率。
- 進場時間 / 持有時間。
- strategy / model version（若此部位由 EasyStock 產生）。
- position source：AUTO / MANUAL / EXTERNAL。
- broker sync time。
- reconcile status。

若持倉是使用者在券商端手動買入、不是 EasyStock 建立，也必須能顯示，但要標記為 `EXTERNAL` / `MANUAL`，不可假裝是 AI 策略部位。

Owner-only 後台可提供「手動賣出」入口：
- 單一持股全數賣出。
- 指定數量賣出（若 Broker / 策略支援）。
- 明確顯示價格類型 / 委託類型。
- 送單前重新讀取 Broker 持倉，確認可賣數量。
- 送單前再次確認 Owner session 與指定券商帳戶。
- 成功送單後以 Order Callback / Deal Callback 更新狀態。
- 未成交 / 部分成交需持續追蹤，不可直接視為已平倉。
- 真實成交後才更新 Live Ledger / PnL。
- 所有手動賣出操作必須寫入 audit log。

手動賣出與自動策略出場不可建立兩套執行引擎。兩者都必須走同一套：

```text
Owner Manual Sell / Strategy Exit
            ↓
       Trade Gate
            ↓
      Broker Order
            ↓
    Order / Deal Callback
            ↓
       Reconcile
            ↓
      Live Ledger
            ↓
      Position / PnL
```

若持倉 / 可賣數量 / 本機 ledger 與 Broker 不一致：
- 禁止手動送出新賣單。
- AUTO PAUSED。
- 先完成 Reconcile。
- 後台顯示明確不一致原因。

第一階段 UI skeleton 仍保持所有賣出按鈕 disabled；只有未來正式完成 broker credential、account binding、reconcile、order/deal callback 與 safety tests 後，才可解鎖真實賣出。

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

## API / 資料源健康燈號規劃

2026-09-30：第一版已實作六個來源的公開摘要、首頁小卡、Owner 詳細診斷及 Firebase 客戶端寫入拒絕。實際請求 / 報價證據控制狀態；未觀察到的 AI 呼叫顯示待命。部署與測試方式見 [行情與健康狀態](MARKET_DATA_HEALTH.md)。

### 公開首頁不顯示 AI 燈號（2026-10-03）
- 首頁健康燈只服務「使用者現在看到的行情 / 資料是否可用」。
- AI Provider、盤後 AI Review、研究模型 runtime 等狀態不放公開首頁。
- 目前盤後 AI 不直接影響正式交易決策，因此公開 AI ONLINE / OFFLINE 對使用者沒有實際操作價值。
- AI / Model / Guardian 詳細健康狀態改放 Owner / Admin；未來只有在某個 AI 服務真的成為公開核心功能的直接依賴時，才重新評估是否需要公開狀態。

### 公開首頁定位
首頁只顯示可公開、脫敏後的健康摘要，不直接暴露後台診斷資料。

第一階段顯示：
- 永豐行情
- 玉山行情
- Fugle
- Firebase
- 必要的 AI Provider

不放首頁：
- LINE Bot
- Telegram Bot

LINE / Telegram 狀態只在 Owner / Admin 後台查看。

### 公開狀態
統一使用：
- ONLINE
- DEGRADED
- OFFLINE
- UNKNOWN
- MARKET CLOSED（行情來源在非交易時段使用）

### 判定原則
不要只看「API 有沒有回 200」或「WebSocket 是否 connected」。

行情資料源至少綜合：
- 連線狀態
- last_ok_at
- last_data_at
- quote_at
- freshness
- parser 是否成功
- 是否連續失敗

盤中可依資料延遲判定，例如：
- <= 30 秒：ONLINE
- 30～120 秒：DEGRADED
- > 120 秒：OFFLINE / STALE

實際門檻依不同 provider 與資料頻率調整，不能所有來源硬套同一秒數。

盤後不應因沒有新 Tick 直接判 OFFLINE；應顯示 MARKET CLOSED，並保留最後正常資料時間。

### 首頁公開資料
建議只發布類似：

```json
{
  "generated_at": "2026-09-30T09:24:18+08:00",
  "providers": {
    "shioaji": {
      "status": "ONLINE",
      "last_ok_at": "2026-09-30T09:24:16+08:00",
      "last_data_at": "2026-09-30T09:24:15+08:00"
    },
    "esun": {
      "status": "ONLINE",
      "last_ok_at": "2026-09-30T09:24:17+08:00",
      "last_data_at": "2026-09-30T09:24:17+08:00"
    },
    "fugle": {
      "status": "DEGRADED",
      "last_ok_at": "2026-09-30T09:22:40+08:00",
      "last_data_at": "2026-09-30T09:22:40+08:00"
    },
    "firebase": {
      "status": "ONLINE",
      "last_ok_at": "2026-09-30T09:24:18+08:00"
    }
  }
}
```

公開 summary 不直接打各家 API，而由後端 / VM 統一產生後再發布。

### 後台詳細資訊
Owner / Admin 才能查看：
- latency_ms
- last_error_code
- last_error_at
- consecutive_failures
- reconnect_count
- last_quote_at
- source_version
- provider-specific diagnostics
- LINE / Telegram 狀態

### 不可公開
- API Key
- Token
- broker account
- person_id / account_id
- 完整 endpoint
- request headers
- VM hostname / private IP / path
- 憑證內容與憑證失敗細節
- stack trace
- 精確 quota / credential 狀態

### 與 Guardian 整合
API Health 第一版可先獨立完成，後續再併入 AI Architecture Guardian 的資料品質 / 外部依賴監控。

建議施工順序：
```text
玉山 API 基礎接入
      ↓
API / 資料源健康燈號
      ↓
Rebound Dataset
      ↓
AI Architecture Guardian
```

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

## AI NAS 自動開發串聯（持續建置）

### 已完成基礎
- 已建立獨立 ARM64 `easystock-antigravity` NAS 開發容器。
- 已建立獨立 NAS Codex development node。
- Antigravity / Codex 使用獨立容器、workspace 與資源邊界，不與正式 VM runtime 混用。
- 已具備 NAS pull-backup、SQLite source health check 與 Docker backup scheduler。
- NAS AI 節點可做 Git pull、程式修改、測試、commit / push main；是否 push 仍需明確任務，不在容器重啟時自動 pull/reset。
- 容器不掛 Oracle VM SSH key / SSH agent，不直接取得正式 VM deployment 權限。

### 目前進行中
目標不是單純「NAS 上能跑兩個 CLI」，而是形成穩定的 AI 開發鏈：

```text
使用者 / 任務入口
      ↓
Antigravity：整理需求 / 分派
      ↓
Codex：實作 / 測試
      ↓
必要時交叉 review
      ↓
Git main
      ↓
受保護的 VM canonical deploy
      ↓
測試 / release identity / runtime 回報
```

### 尚待完成
- 任務 session / handoff 的穩定協議。
- Antigravity 與 Codex 的工作衝突 / lock / ownership 規則。
- 失敗重試與中斷後續接。
- 避免兩個 AI 同時跑大型 `pytest` / build 導致 NAS OOM。
- 自動測試通過後的 Git 提交流程與人工邊界。
- 正式 VM 部署仍維持受保護流程，不因 NAS AI 節點存在而自動取得正式部署權。

### Runtime 判定
GitHub 只能證明上述容器 / compose / scripts / docs 已建立；NAS 上容器當下是否 `running`、是否已登入 Antigravity / Codex、是否正在執行任務，必須以 NAS Docker runtime 實際狀態確認。

---

## GitHub / 模型核心保護規劃

目前不併入 1.0X Bugfix 線；規劃於 2.0 或後續較大架構版本再處理。

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
# Paper 模擬：起始本金制 → 每日當沖買進額度制

- [x] `daily_buy_limit` 與由當日 BUY fills 重建的 used / remaining。
- [x] SELL 不恢復額度；費稅與 PnL / Equity 獨立計算。
- [x] Owner 調整額度保留已用額度與持倉。
- [x] Admin API / UI、Health 與每日盤後摘要使用新語意。
- [x] Research-only 與 episode 去重、re-arm 相容；額度不足仍完整追蹤。
- [x] Additive、idempotent migration；原欄位值驗證、備份與回歸測試。
- [ ] VM migration 與正式交易日驗收（需可連線的 VM shell）。

詳見 [PAPER_DAILY_BUY_LIMIT.md](PAPER_DAILY_BUY_LIMIT.md)。
