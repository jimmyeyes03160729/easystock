# EasyStock Chrome 台股策略監控

完整 Manifest V3 原始碼。保留使用者提供的 400 × 600 popup 結構、配色及設定抽屜；Tailwind 編譯為本機 CSS，圖示與 JavaScript 全數隨套件提供。不含券商帳密，不下單，不改動 LINE / Telegram。

## 安裝與隔離 VM 測試

1. 在 `chrome-extension` 執行 `pnpm install --frozen-lockfile`、`pnpm build`、`pnpm test`。
2. 在有圖形桌面的 Windows / Linux VM 安裝 Chrome 116 以上，建立獨立 Chrome 使用者，不登入同步帳號。
3. 開啟 `chrome://extensions`，啟用開發人員模式，選「載入未封裝項目」，選 `dist/vm`。不選原始碼父層或 ZIP 檔。
4. VM 版不含任何遠端主機權限、不讀正式 Firebase / GitHub、不自動產生交易推播，示範報價有 VM 標示。查線圖仍會依使用者點擊開啟 Yahoo 網頁。
5. 開啟設定，依序按「測試當沖推播」「測試反彈推播」。檢查 VM 桌面通知、系統通知中心與音效。兩種測試皆不占每日額度、不受開關/盤中/冷卻限制；測試通知的「今日忽略」只關閉測試，不會靜音正式訊號。
6. 輸入 `VIP888` 應開通 VM VIP；正式版刻意沒有這個公開通用序號。
7. 關閉 popup 後，背景仍可被 alarm 喚醒；Chrome / VM 必須運行且不能休眠。暫停 VM 期間不保證任何訊號通知。
8. 正式版載入 `dist/production`。兩個資料夾會是不同擴充功能身分，儲存資料隔離。更新前請匯出自選清單。

系統原生彈窗及聲音取決於 Chrome、Windows / Linux 通知權限、勿擾模式、VM 音效裝置；`silent: false` 不是音效保證。macOS / Linux 可能不顯示通知按鈕。模擬 API 測試不能代替這一步人工驗收。

## 使用方式

- 輸入 `2330` 或已有行情的精確名稱新增。上櫃用 `8299.TWO`，上市用 `2330.TW`；純代號預設 TW，輸入時須確認市場。不存在/未訂閱的股票保留自選但顯示無報價，不捏造行情。
- 卡片可勾選當沖/反彈，至少一個群組；× 刪除。三個分頁只篩選顯示，不變更監控設定。
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
- 可以透過配置 `daytrade_strategy_signals` 發布完整訊號；必要欄位與反彈一致。

### 反彈配置

`bounce_strategy_signals` 是後台發布的觀察訊號，不是擴充功能自算的勝率模型。每筆需要 `id, symbol, market, name, price, change_pct, reason, generated_at, quote_at`。id 必須跨輪詢穩定，同一推薦更新報價不得反覆改 id 製造重複事件。過期/不完整/未來時間的資料不推播、不列為當前推薦。自選股票須勾選反彈且開啟策略才通知；推薦顯示不等於交易建議。

空配置代表未發布訊號，不能說沒有機會。本次未部署每日/即時生成 GitHub 反彈 JSON 的新伺服器排程，現有網頁的反彈卡也不會被擴充功能自動抓取。要自動更新該清單，須由現有後台接續發布符合格式的訊號。

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
