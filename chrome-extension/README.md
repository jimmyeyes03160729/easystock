# EasyStock Chrome 台股策略監控

完整 Manifest V3 原始碼。保留使用者提供的 400 × 600 popup 結構、配色及設定抽屜；Tailwind 編譯為本機 CSS，圖示與 JavaScript 全數隨套件提供。不含券商帳密，不下單，不改動 LINE / Telegram。

## 1.05 重點

- 版本號維持 1.05；全新「沖」字紅色毛筆書法風格 ICON（高對比透明去背）。
- 「底部反彈（觸底反彈）」功能確定移除，Chrome 不再顯示反彈候選。
- 迷你走勢圖時間軸改為固定 09:00～13:30 真實位置，不再把早盤資料硬拉滿整天。
- 盤中日 K 會追加今日正在形成的 partial K 棒，只吃台北當日有效分時資料。

## 1.03 Bugfix 重點

1.03 以目前正式 Chrome 小工具功能重新打包，不把已移除的「觸底反彈」功能加回來。

- Chrome 小工具目前只保留：自選、當沖、當沖 AI 架構。
- 觸底反彈維持在 EasyStock Web 首頁，不屬於本版 Chrome 小工具功能。
- 使用目前 repo 內已更新的 EasyStock 品牌 ICON（16 / 48 / 128）。
- 延續 1.02 的行情刷新、盤中 K 線、固定分時軸、時區與 Popup 載入修正。
- Google 登入、Firebase 使用者同步與本機 Migration 仍保留到 2.0。

## 1.02 Bugfix 重點

1.02 是 1.0X 穩定線，不加入 Google 登入或 Firebase 個人同步；這些大型功能延後到 2.0。

- 加權指數盤中改為獨立 30 秒刷新，並顯示 TWSE 實際資料時間。
- 手動重新整理真正 bypass 行情快取；自選報價同時依 `quote_at / updated_at` freshness 重抓。
- Yahoo 報價時間統一轉成帶 offset 的 ISO 8601，前端只做一次 `Asia/Taipei` 顯示，移除重複 +8 風險。
- 分時 X 軸預設固定 09:00～13:30，未到時間區段保留空白。
- 盤中日 K 由歷史日 K + 真實當日 1 分 K OHLC 合併，今日棒標記為 partial；不以假資料補 K。
- Popup 先顯示固定高度 Shell / Skeleton 與已儲存主題，再背景刷新，避免初次白屏與視窗縮小。


## 安裝與隔離 VM 測試

1. 在 `chrome-extension` 執行 `pnpm install --frozen-lockfile`、`pnpm build`、`pnpm test`。
2. 在有圖形桌面的 Windows / Linux VM 安裝 Chrome 116 以上，建立獨立 Chrome 使用者，不登入同步帳號。
3. 開啟 `chrome://extensions`，啟用開發人員模式，選「載入未封裝項目」，選 `dist/vm`。不選原始碼父層或 ZIP 檔。
4. VM 版不含任何遠端主機權限、不讀正式 Firebase / GitHub、不自動產生交易推播，示範報價有 VM 標示。查線圖仍會依使用者點擊開啟 Yahoo 網頁。
6. 輸入 `VIP888` 應開通 VM VIP；正式版刻意沒有這個公開通用序號。
7. 關閉 popup 後，背景仍可被 alarm 喚醒；Chrome / VM 必須運行且不能休眠。暫停 VM 期間不保證任何訊號通知。
8. 正式版載入 `dist/production`。兩個資料夾會是不同擴充功能身分，儲存資料隔離。更新前請匯出自選清單。

系統原生彈窗及聲音取決於 Chrome、Windows / Linux 通知權限、勿擾模式、VM 音效裝置；`silent: false` 不是音效保證。macOS / Linux 可能不顯示通知按鈕。模擬 API 測試不能代替這一步人工驗收。

## 使用方式

- 輸入 `2330` 或已有行情的精確名稱新增。上櫃用 `8299.TWO`，上市用 `2330.TW`；純代號預設 TW，輸入時須確認市場。不存在/未訂閱的股票保留自選但顯示無報價，不捏造行情。
- 策略開關全域套用。每五分鐘比對；這不是逐筆或低延遲當沖交易系統，短暫訊號可能錯過。
- 預設免費每日三笔正式通知；同股票跨策略三十分鐘冷卻，同一事件當日不重複。VIP 只解除三筆額度，仍保留冷卻和「今日忽略」。台北午夜切日。
- 通知本體與「查看線圖」開 Yahoo；「今日忽略」只抑制今天該股，不開線圖。配合按鈕語意，避免本來想靜音卻開啟網頁。
- 匯入需要 version=1 與 stocks 陣列，最多 100 檔，先驗證全部再確認取代；錯誤檔不會部分覆蓋。匯出只有清單，不包含 VIP 授權、通知紀錄或任何帳密。

## 配置與資料管線

`environment.js` 宣告 CONFIG_URL，指向本倉庫 main 分支的 `chrome-extension/config.json`。部署前需將檔案發布到該位置。`github_config_schema.json` 是使用者要求的**JSON 範例**，不是 JSON Schema 規格文件；範例過期時間刻意不會推播。正式 `config.json` 預設沒有推薦或通用 VIP。

資料流程：popup 只傳固定類型訊息 → background 驗證擴充功能與 popup 身分 → 讀取/更新 chrome.storage.local → 取得配置/公開行情 → 驗證時間與策略 → 保留額度及去重紀錄 → 建立 Chrome 通知。所有狀態改寫經同一佇列，避免 popup、alarm、點擊事件互相覆蓋。Chrome 在記錄額度後當機可能少一次通知，採「至多一次」而非重發交易訊號。

GitHub 配置成功或失敗請求都有五分鐘節流，重新整理不繞過 TTL。過期配置遇到網路失敗不繼續授予 VIP，也不推播。休市 alarm 仍每五分鐘喚醒，但不請求遠端/比對訊號；使用者手動開 popup 可讀最後行情及更新配置。

台北平日 09:00（含）–13:30（不含），加上 `market_holidays`。2026 休市表來自 [證交所](https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=html)。管理員每年更新，臨時颱風停市也需加入；不宣称只靠平日判定涵蓋所有停市。

### 正式行情與當沖

唯讀 `market_data/public_feed` 及 `market_data/intraday_live` 公開 Firebase 節點。不需要 Firebase 管理金鑰。

- 當沖只讀後端 `open_positions` 的 OPEN 進場訊號，不把 radar_top30 候選當成進場。
- 进場時間與報價時間都需為含時區 ISO 8601、同一天、非未來、五分鐘內。Chrome 睡眠或訊號已結束不補發舊進場。
- 目前公開 feed 常只有 price/name/updated_at/volume，沒有當日漲跌幅。此時實際訊號顯示「漲跌幅未提供」，絕不以 0% 或相對進場損益冒充。若未來發布 `change_pct` 或 `previous_close`，背景可顯示/計算日漲跌幅。沒有任何訊號時保持安靜。

### VIP 與付款安全邊界

- `global_vip_switch: true` 表示所有使用者暫時取得 VIP；false 時必須持有名單內 hash。不是付款總開關。
- 輸入碼在背景以 SHA-256 計算，只保留 hash。每次有效配置重新判斷授權，可移除 hash 撤銷（最多快取五分鐘）。明文序號不記錄、不匯出。
- **公開 hash 清單 + 可修改的用戶端不是防破解商業授權系統。** 不應把低熵序號 hash 當秘密。真正收費需要伺服器登入、授權驗證、付款 webhook、到期管理；本版付款只有 HTTPS 連結與確認，不偽裝收款/自動開通。
- `payment_gateway_url` 預設空字串。設定連結後會显示網站名稱，經使用者確認才開分頁。
- VM 才內建 VIP888；正式版請使用個別高熵授權碼，將 SHA-256 放入 config。不要在 GitHub 放 Firebase 私鑰、Telegram token 或明文序號。

## 驗收清單

先 `pnpm build` 再執行 `pnpm test` 驗證盤中/TPE 切日、快取、壞設定、VIP、冷卻與配額、原生通知路由、持久化狀態、來源過期、匯入/XSS 邊界與 VM 包內容。原生音效需在目標 VM 實測。

上線仍需：確認 CONFIG_URL 可讀、發布有效策略資料、完整 VM 原生通知人工驗收；如要商業販售，另建真正伺服器授權及隱私/商店審核流程。不宣稱已通過 Chrome Web Store 審核。

官方限制：[MV3 遠端程式碼](https://developer.chrome.com/docs/extensions/develop/migrate/remote-hosted-code)、[alarms 與睡眠/重啟](https://developer.chrome.com/docs/extensions/reference/api/alarms)、[原生 notifications](https://developer.chrome.com/docs/extensions/reference/api/notifications)。
