# 手動委託結果未確認：10/15 修復

今天11:13、11:15兩次手動委託被舊後端記為 `broker_submission_unknown`。對應工作程序的SDK日誌於03:13、03:15 UTC顯示HTTP401，接著中斷Solace連線。舊版沒有保存異常發生階段，不能僅憑歷史資料確定401是在憑證啟用還是實際送單時發生；舊的未知紀錄保留，不自動清除或重送。

手動券商元件改為明確使用 `Shioaji(simulation=False)`。安裝的SDK為1.7.4，建構式參數 `simulation=None`，不應依賴新版預設環境。既有實單雙重環境開關、Owner驗證、CSRF、限價／數量檢查均保留，沒有修改A/B研究或模擬元件。

登入在SDK支援時使用 `force_refresh=True`，避免只建立新的Python物件卻沿用快取權杖。重新登入失敗不再吞掉例外；401會將本機登入標記設為失效。這不會自動重試委託。

送出前分成連線、憑證檔案、帳戶、合約、憑證啟用、建立委託及最後驗證等階段。只有在尚未呼叫 `api.place_order` 時才允許標示 `not_submitted`，回傳固定、安全的錯誤代碼與階段，並保留請求識別碼避免同一請求重複使用。憑證啟用必須明確回傳True。

一旦呼叫 `api.place_order`，任何例外或缺少可靠委託識別碼都維持未知結果，不能靠401文字自行斷言沒有下單。網頁不自動重送，未知結果仍需對帳。已知未送出的新紀錄不占用賣出保留數量，也不被當成缺少遠端委託的對帳錯誤。

驗證使用Mock SDK、Flask測試與瀏覽器DOM測試；沒有呼叫真實送單API。API Key的交易／正式環境權限與實際憑證密碼，仍須由帳戶持有人確認；不能將登入或報價成功當成已驗證可成交。

官方參考：
- https://sinotrade.github.io/tutor/prepare/token/
- https://github.com/Sinotrade/rshioaji/blob/main/skills/shioaji/references/PREPARE.md
