# 行情 Provider 與健康狀態

玉山服務只呼叫登入、行情 REST、WebSocket `indices` 訂閱及心跳；沒有委託、交易路由或持倉介面。沿用 VM 已安裝的 `@esun/marketdata` 2.2.0 SDK 與私有 `/etc/easystock/esun/` 設定，SDK 與憑證不放進公開 repo。

## 正式管線

`easystock-esun-marketdata.service` → `vm_runtime/esun_marketdata/provider.js` → 私有本機 `context.json` / `esun.json` → `market_data.context` / Market Risk Gate。

`indices.json` 的七個價格指數已在 2026-09-30 用玉山 `stock.intraday.tickers(type=INDEX)` 與逐一 quote 查詢核對：加權 IX0001、櫃買 IX0043、電子 IX0027、半導體 IX0028、金融 IX0039、電子零組件 IX0032、航運 IX0037。IR0001 是報酬指數，不能和價格指數混用。

指數 WebSocket `indices` payload 的 `index` 與 `time` 參照 SDK 與 [官方訊息文件](https://developer.fugle.tw/docs/data/websocket-api/market-data-channels/indices/)。每日漲跌只從 REST 真實基準價衍生；跨日不沿用昨日基準。報價時間和收到時間分開保存，未收到的 1/5/15 分鐘報酬與 regime 保留 null。

服務每 30 秒校準 REST 快照，5 秒檢查心跳；90 秒沒心跳重連。重連重新登入及訂閱，等待 1、2、5、10、30、60 秒，上限 60 秒。解析失敗只記 allowlist error code。私有目錄預設 `/home/ubuntu/easystock-market-data`，可用 `EASYSTOCK_MARKET_DATA_DIR` 覆寫。新鮮資料每分鐘保存 Dataset snapshot，先供研究 / shadow，沒有接進正式模型訓練或新增 ENTRY 條件。

## 健康判定

`easystock-provider-health.timer` 每分鐘執行 `python -m market_data.publish`。交易時段沿用 `market_calendar`，包含台灣假日與停班資訊，日曆失敗顯示 UNKNOWN。

|來源|證據與期限|
|---|---|
|永豐|盤中引擎實際指數 snapshot，90 秒報價、120 秒服務證據|
|玉山|連線、認證、七個訂閱、心跳、解析、90 秒報價、120 秒服務證據|
|Fugle|每 5 分鐘的唯讀個股 quote，360 秒報價；盤後每 15 分鐘|
|Firebase|實際讀取及 health 發布，180 秒|
|Gemini|盤前實際解析成功 / 失敗，24 小時；無近期請求顯示待命|
|OpenAI|無觀察到呼叫時顯示待命，不發送付費測試请求|

ONLINE=有效的新鮮證據；DEGRADED=延遲、解析或部分訂閱異常；OFFLINE=已觀察到失敗 / 連線斷開；UNKNOWN=缺乏證據 / AI 待命；MARKET_CLOSED=市場休市或盤後，沒有新 tick 不是故障。已知失敗仍保留，休市不掩蓋故障。

首頁只讀 `/market_data/provider_health`：schema_version、generated_at、market_state、六個固定 provider 的 status / last_checked_at。沒有 LINE / Telegram、錯誤內文、端點、路徑、帳號或金鑰。摘要超過 180 秒，前端降為 UNKNOWN。

詳細診斷保留於本機，透過現有 Google Owner 登入後的 `/admin/health` 提供，包含資料與心跳秒數、延遲、重連、訂閱、成功 / 失敗時間與 allowlist error code。Firebase 客戶端禁止寫入；部署只合併兩個 health 節點的讀取規則，保存及核對舊規則，不覆蓋其他政策。

## 部署及驗證

沿用 `bash deploy/update_vm_main.sh`，測試通過後安裝服務 / timer、套用最小 Firebase 規則、發布摘要並重載後台。SDK 未安裝則停止部署，不偷偷下載別的版本。原有行情資料、憑證與模型不改動。

只讀 smoke：設定一個臨時 `EASYSTOCK_MARKET_DATA_DIR`，執行 `node vm_runtime/esun_marketdata/smoke.js`。驗證登入、WS 認證、七個訂閱、事件、心跳及 normalized quotes；休市不要求新成交。

回歸測試：`pnpm test`、`python -m pytest tests -q`、`python -m pytest vm_runtime/tests -q`。測試時務必將 `EASYSTOCK_MARKET_DATA_DIR` 指向臨時資料夾，避免健康 fixture 影響正式證據。
