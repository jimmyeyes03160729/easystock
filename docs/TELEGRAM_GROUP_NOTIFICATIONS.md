# 群組專用當沖通知

## 行為

- `vm_runtime/intraday_live.py` 的進場／出場通知經 `trade_notifications.send_trade` 分流至 Telegram、LINE，策略、停損停利與每日推薦上限不變。
- Telegram 僅向私有設定檔指定的負數群組 ID 發送純文字。未建立 webhook／輪詢接收器，因此不讀取群組聊天，也不處理私人對話或股票查詢。未啟用付費廣播。
- LINE 僅接受已核准且未封存的群組。私人訊息（含原管理員綁定／修改指令）、舊聊天室及未核准群組均不回覆、不推播。盤前／盤後等其他自動推播強制停用。
- LINE 群組查詢回覆和進出場通知可分別控制；Telegram 只有進出場通知開關。部署保留目前 LINE 有效開關，不擅自重新開啟。
- 舊群組／個人資料在私有 SQLite 封存並從後台隱藏，不刪除歷史資料、不退出 LINE 群組。重新收到 webhook 也不能重新啟用。

## 憑證與管理

- Bot token 與群組 ID 放在 VM `/home/ubuntu/easystock-telegram.env`，權限 `0600`，不納入 Git、公開 Firebase、後台 JSON 或稽核紀錄。
- 設定鍵：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_GROUP_ID`。測試可用 `TELEGRAM_CONFIG_FILE` 改指定私有檔案；同名環境變數優先。拒絕正數個人 ID、username 與無效憑證格式。
- 後台沿用 Google 單一擁有者驗證、Secure/HttpOnly/SameSite cookie、Origin + CSRF、樂觀版本鎖。
- `GET /admin/notification-groups` 回傳去識別化群組控制與最近 10 筆傳送狀態；`PUT /admin/notification-groups/{line|telegram}/{id}` 修改開關。不能從網頁輸入任意目的地或更換 token。
- 停用的個人綁定 HTTP 入口回傳 403；Google 登入與推薦條件設定不變。

## 傳送與失敗處理

- 每次新進場通知向每個管道送出前都重查最新報價限制；出場通知不套用新進場門檻。
- 先嘗試 Telegram 再 LINE，各自捕捉失敗。Telegram 逾時不會阻止 LINE；LINE 額度不足也不影響已送出的 Telegram。
- 私有 SQLite 以事件／管道雜湊記錄 `pending/sent/failed/unknown`，不保存訊息正文。依實際 PositionManager 的 `position/trade`、事件類型、股票與進場時間識別；缺少交易身分時以台北日期與訊息雜湊識別，避免跨日相同短文被誤判重複。
- 採「至多一次嘗試」，不是保證送達：同一事件重複呼叫或程序重啟不會盲目重送。HTTP 逾時、當機前後可能無法確認是否送达，後台顯示結果不明／未確認；此時可能漏通知。Telegram `sendMessage` 沒有供此流程使用的冪等鍵。失敗紀錄不當成成功。
- 控制關閉或資料庫不可用時不發送。通知停用不停止既有訊號追蹤。

## 部署／驗證

`deploy/install_telegram_groups.py` 必須從已測試的 staging 副本執行；檢查既有來源雜湊、確認盤中引擎未執行、備份來源與 SQLite，再短暫重啟 LINE webhook／後台服務。僅封存已核對的舊群組，保留使用中群組的有效開關。`EASYSTOCK_CONFIRMED_GROUP_TAG` 與 `EASYSTOCK_RETIRED_GROUP_TAG` 為部署時核對原始 ID 的 SHA-256 前 8 碼，不是目的地本身。

本次 Bot 權限由 `getMe/getChat/getChatMember` 驗證；測試訊息須標示為系統連線測試，不能偽造交易進出場。不得為測試消耗 LINE 推播額度。

離線測試：`python vm_runtime/easystock_admin/test_notifications.py`、`test_conversations.py`、`test_admin.py`（Linux）、`node tests/test_admin_ui.cjs`。

官方介面：[Telegram sendMessage](https://core.telegram.org/bots/api#sendmessage)。
