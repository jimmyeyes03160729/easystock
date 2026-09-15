# Telegram 群組股票查詢

支援與 LINE 相同的 `P大盤`、`#台積電`、`#2330`、`P2330`、`K2330`、`T2330`、`D2330`、`#大盤`、`指令` 等；圖卡的即時／K 線／法人按鈕轉為 Telegram inline keyboard，點擊後產生相同查詢。`#` 查價沿用 LINE 的文字報價，P/K/T 則沿用同一 PNG 圖卡，沒有重做計算或改動交易策略。

## 流程與隔離

1. `easystock-telegram-stock-bot.service` 長輪詢 `getUpdates`（20 秒），取得一般訊息及按鈕 callback。
2. 僅接受設定中的 group/supergroup、非機器人發送者；私人、其他群組、編輯訊息均不處理。一般訊息超過 120 秒不補回覆。
3. 查詢回覆開關必須開啟；透過 loopback POST `/internal/telegram-query` 呼叫現有 LINE worker。使用由 Bot token 導出的專用 HMAC 驗證值，且限制 loopback 來源、JSON 大小、指定群組與每分鐘 15 次有效查詢。網頁與外部請求沒有此憑證。
4. LINE worker 使用既有 `parse_command`、`handle_command_with_cache`、`stock_command_service`、`line_card_renderer`。共用永豐登入與 60 秒圖片快取／跨程序鎖，不增加券商登入。一般閒聊不觸發資料查詢。
5. Telegram 直接上傳 RAM 圖卡，不請求任意外部圖片網址。檔名、目錄、PNG 標頭與 10 MB 大小限制均檢查；圖片下方按鈕轉成 callback 或 HTTPS 網站連結。

## 控制、隱私與失敗處理

- 後台 Telegram「群組查詢回覆」與「進出場通知」各自獨立；儲存沿用 Google 登入、CSRF、Origin 與版本鎖。
- `telegram_policy.replies` 新建時預設關閉，部署此功能時明確啟用；保留既有 push 與全部 LINE 設定。舊版只修改 push 的 API 請求不更動 replies。
- 不儲存聊天內容、姓名、私人 ID 或圖卡正文；SQLite 僅保留 polling offset 與最後成功輪詢時間。所有 update（包括被忽略者）均前移 offset，避免重複處理。
- 圖卡產生後、發送前再次檢查開關。關閉回覆不會停止當沖進出場推播，也不停止訊號追蹤。
- 採至多一次處理：發送逾時／程序在中途停止不自動重送，可能漏回覆；使用者可重發查詢。API 網路中斷自動重連、systemd 程序失敗自動重啟，單一 poller 使用 flock 防止重複消費。
- 回覆不含上游例外詳細資訊；token 不出現在程式碼、URL 日誌、後台或 Firebase。
- 不建立 Telegram webhook，也不變更 BotFather 隱私模式；Bot 必須維持指定群組管理員，才能收到普通 `P大盤`／`#股票` 訊息。既有 webhook 存在時拒絕啟動，避免搶占其他接收器。

官方介面：[getUpdates](https://core.telegram.org/bots/api#getupdates)、[sendPhoto](https://core.telegram.org/bots/api#sendphoto)、[inline keyboard](https://core.telegram.org/bots/api#inlinekeyboardmarkup)。

離線測試：`python vm_runtime/easystock_admin/test_telegram_queries.py`、`test_notifications.py`、`test_admin.py`（Linux）及 `node tests/test_admin_ui.cjs`。
