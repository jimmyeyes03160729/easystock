# 現行模組與資料契約

## 職責與來源

| 範圍 | 程式 | 職責 |
|---|---|---|
| 日線發布 | `update_market.py` | 官方資料解析、指標、歷史技術研究、發布不可变批次 |
| 日線規則 | `strategy_rules.py` | 當前與歷史技術訊號共用的純函式 |
| 隔日衝研究 | `scan_intraday.py` | Fugle 完成分K與尾盤候選；保留既有研究排程，首頁目前隱藏此區塊 |
| 公開看板 | `index.html` | 資料讀取、狀態、價格篩選與圖表 |
| 底部反彈 | `assets/rebound-engine.js`、`rebound-ui.js` | 獨立試行規則與顯示，非共用日線回踩策略，沒有獨立回測績效 |
| 學習面板 | `assets/learning-status.js` | 僅建立與更新學習／復盤面板 |
| 首頁布局 | `assets/dashboard-layout.js` | 管理模組排列與顯示，不覆寫資料 renderer |
| 正式 VM 基準 | `vm_runtime/` | 已核對來源的 Shioaji、部位管理、LINE、Google 管理介面與已接線研究 |

底部反彈用成交金額至少 500 萬元，日線共用規則用 5,000 萬元；這是兩套不同研究條件，不能把分數、勝率或驗證結果相互套用。本次沒有調整選股、進出場或成本門檻。

## 日線資料

發布先完成 `/market_data/releases/{id}/{summary,meta,backtests,kline}`，最後才切換 `/market_data/active_release`。
`meta.kline_schema_version=1` 表示 K 線已包含在同一批次；前端將 ID 綁在個股資料上，圖表與反彈模組均從同一版本讀取。
舊批次缺少此欄位時仍讀舊 `/kline/{symbol}`，並保留既有日期檢查；這只是遷移相容模式，不宣稱同日修訂也具一致性。
前端每 60 秒檢查 `active_release`；隔日衝節點失敗不阻止日線更新。舊版本被清理後，舊畫面讀取該版本圖表會失敗，重新整理可取得現行批次，不偷偷改用其他版本。

## 即時狀態

每 5 秒讀取即時節點；單次讀取上限 12 秒，前次未完成時不重入。
成功的有效物件才替換最後快照。網路錯誤、權限錯誤、null 或無時間戳的結果不清空已知部位。
非當日、無效／未來時間或超過 60 秒未更新均有獨立提示；當天 `closed` 快照標示收盤，不冒充即時報價。
此狀態是傳輸與快照時效，不能證明上游券商每個 Tick 都完整送達。

## 認證與憑證

公開 GitHub Pages 無需登入；直接以 HTTPS 讀取 Firebase 白名單節點，不帶服務帳號或券商金鑰。localStorage 只保存顯示偏好。
Firebase `.read` 不在 `/market_data` 父節點開放，避免公開群組 ID、模擬交易、研究歷史；客戶端寫入全部拒絕。服務帳號透過 Admin SDK／OAuth 憑證在後端存取私有資料。

VM 管理介面另有 Google 登入：challenge cookie 與一次性 nonce → 後端驗證 Google token 簽章、有效期、audience/issuer → 驗證管理員 email、email_verified、nonce 與固定 subject → 核發 8 小時隨機 session cookie。
cookie 使用 Secure、HttpOnly、SameSite=Strict；SQLite 保存 session token 的雜湊，寫入設定另驗證 Origin 與 CSRF token，登出會刪除伺服器 session。
管理員地址在 repo 基準改由 `ADMIN_OWNER_EMAIL` 設定；缺少時拒絕登入。LINE 綁定僅接受已驗證 Webhook 的私訊與一次性綁定碼。

`.env`、服務帳號 JSON、SSH 私鑰與私有 SQLite 留在 VM／本機；版本庫不保存實際憑證。`tools/firebase_rules.py` 在 VM 使用既有憑證做規則部署與狀態驗證，不輸出 token 或私有資料內容。

## 測試

`pnpm install --frozen-lockfile --ignore-scripts && pnpm test` 執行前端與規則政策檢查。DOM 測試使用 jsdom，並非真實瀏覽器排版截圖。
Python 解析、選股、發布中斷、研究與管理員驗證以離線資料測試，納入獨立 push／PR CI。VM 的 fcntl 相關測試在 Linux 執行。
Firebase 本機政策檢查不是 emulator；部署後另用匿名及服務帳號實際 GET 驗證讀取邊界，不測試寫入正式資料。
