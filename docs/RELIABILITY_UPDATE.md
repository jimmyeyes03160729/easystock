# 模組可靠性修正（2026-09-15）

## 已完成

- 即時讀取失敗保留最後快照，獨立顯示斷線、無資料與超時；當日收盤快照不冒充即時。
- 日線摘要、回測與 K 線同版發布，任一必要寫入失敗不切換 `active_release`；圖表與反彈模組固定讀取對應版本。
- 日線刷新不再被隔日衝節點讀取失敗阻擋。
- 首頁布局移到 `dashboard-layout.js`；學習面板不再移除別的模組或覆寫全域 renderer。
- UI 測試改用 jsdom 並加入完整模組組合、失敗恢復與批次一致性測試。独立 push／PR CI 涵蓋日線、研究、管理員與前端測試。
- `vm_runtime/` 收錄已核對的正式來源；盤前根目錄入口轉接到這個版本，補齊本地相依模組。
- 管理員地址在 repo 基準由環境指定、未設定拒絕登入；SQLite 初始化連線確實關閉。這些 VM 基準改動尚未覆蓋正式服務。

## 已套用到線上的變更

### Firebase 規則

已將 `/market_data` 全域匿名讀取改成公開節點白名單。匿名群組、模擬交易、研究歷史與父節點讀取被拒絕；公開看板節點以及服務帳號私有讀取均驗證成功。
規則 SHA-256（canonical JSON）：`e537a1a7ab76b858da2735fdf88f138ec0d420242a2b5dc3280342a6ced724ec`。
最後成功部署前備份：`/home/ubuntu/easystock-maintenance/module-reliability/backups/firebase-rules-20260915T121152843935Z.json`。
使用 `tools/firebase_rules.py`，帶入當前規則雜湊才允許部署；验证失敗且線上仍是本次版本時才回復原規則。没有寫入或刪除業務資料。

原規則允許讀取私有節點，不應因一般前端問題直接回復成整個 `/market_data` 公開。需要相容其他讀取時，先核對客戶端與欄位，再增加指定公開節點。
Firebase REST 規則介面參考：https://firebase.google.com/docs/database/rest/app-management

### VM 日線發布

只對正式 `/home/ubuntu/easystock/update_market.py` 套用 `deploy/market-kline.patch`，保留 VM 與 GitHub 已存在的其他差異。
執行前確認服務未執行、原檔 SHA-256 正確，先備份，再以無模糊比對的補丁套用，最後通過 Python 語法檢查。沒有手動執行日線更新或當沖、沒有重啟 Bot。

- 原檔：`31dffe7cf83a6d27bc5ee2ab7139fb870f074f98e81e46c47e5f69d3f8695f30`
- 修正後：`3d5410f38bc73a95c1555e02a4d83b8e56dc4ee48cfdd9a3ebfe77c7ae8c2bae`
- 備份：`/home/ubuntu/easystock-maintenance/module-reliability/backups/update_market.before-kline.py`
- 下一次既有排程執行時會使用新版發布方式；未宣稱已重新產生正式批次。

若需回復此補丁，先確認日線服務不在執行且目標仍為上述修正後雜湊，再以備份覆蓋此單一檔案，並重新檢查語法。回復發布者後，前端仍可讀取既有新版及舊版資料。

## 網站與後續部署

前端及 GitHub 工作流程需經本分支合併與既有 Pages 部署後才會在線上生效。資料發布者可先更新；新前端對舊批次也保留相容。
`vm_runtime` 是來源與測試基準，不是將整個 VM 目錄一鍵覆蓋的部署包。尤其需保留 `.env`、憑證、管理員 SQLite、研究資料與既有 systemd 設定。

## 核對到的外部狀態

- VM 盤前服務當日成功完成；當沖服務 13:00 正常結束，並非斷線。
- VM 日線 timer 為 14:00；GitHub 日線排程仍為 16:15、20:15。未改動排程。
- 收盤 LINE 摘要服務有失敗記錄。唯讀 API 核對時 Token 有效，本月推播已用 197／200；兩個啟用群組中一個 summary API 回傳 200，另一個 404。
- 上述額度與群組狀態不足以倒推所有過去失敗的 HTTP 原因。未重送 LINE、未自動停用群組、未購買額度。

## 驗證範圍

- Python：7 項解析器、13 項選股／發布、6 項原型研究；另含盤前轉接檢查。
- VM 基準：16 項研究整合、15 項收盤處理、21 項管理員測試；Linux VM 離線測試禁止網路，其中訓練項因無 sklearn 跳過；同一項已在本機獨立研究環境通過。
- JavaScript：主前端、每日／歷史狀態、雙重復盤、全模組 DOM 組合、Firebase 白名單政策均通過。
- 未做真實下單、沒有呼叫付費 AI／發送 LINE 測試，也未驗證投資報酬。
