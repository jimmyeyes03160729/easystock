# Oracle VM 程式來源

此目錄起源於 2026-09-15 VM 快照；之後的 repo 修正不等於 VM 已部署。`source-manifest.json` 僅是歷史來源紀錄，現在版本以 Git commit 及實際檔案雜湊為準。
只收錄程式、管理介面靜態資源與研究成本假設；未收錄 `.env`、服務帳號、私鑰、LINE 群組清單、個人交易紀錄或 SQLite。

## 執行邊界

- repo 根目錄：GitHub Pages、日線更新與 Fugle 隔日衝。
- 本目錄：Shioaji 當沖、LINE Webhook、Google 管理後台、已接線的當沖研究。
- 根目錄 `daytrade_learning` 是較早的獨立研究原型，與本目錄的正式研究版本分開測試，不能交叉覆蓋。
- 根目錄 `premarket_ai.py` 是轉接入口；實際 VM 版本為本目錄的 `premarket_ai.py`，其本地相依模組已一起收錄。
- 這是可審閱的來源基準，不會因 Pages 或日線 workflow 更新而自動覆蓋 VM 服務。

## 環境

使用 Linux、獨立 virtualenv 與本目錄 `requirements.txt`。訓練另需 `scikit-learn==1.8.0`，不應直接改動正式交易環境套件。
Shioaji 平台支援與券商帳戶連線仍須在部署主機驗證。既有 VM 服務依賴的環境檔、systemd 排程、資料目錄与 Google OAuth 設定必須保留。

管理員地址已改為 `ADMIN_OWNER_EMAIL` 環境變數，未設定時拒絕登入；初始化 SQLite 也會明確關閉連線。這些變更目前只在 repo 來源基準；部署前須先於服務環境設定既有管理員地址。
其他設定包括 `ADMIN_GOOGLE_CLIENT_ID`、`ADMIN_PUBLIC_ORIGIN`、`EASYSTOCK_ADMIN_DB`、`LEARNING_DATA_DIR`，僅提供給伺服器；不放進網頁。

## 離線驗證

從本目錄執行（測試使用暫存資料庫及模擬 API）：

```bash
python daytrade_learning/test_integration.py
python daytrade_learning/test_eod_fix.py
python easystock_admin/test_admin.py
```

不要直接執行正式主程式來測試；它們可能訂閱券商行情、写入 Firebase 或傳送 LINE。
歷史訓練與雙 AI 復盤的其他常駐／排程程式可能位於 VM 其他目錄，並不宣稱本快照已涵蓋整台 VM。

## 2026-09-27 Runtime 修正

請依 [部署核對文件](../docs/DAYTRADE_RUNTIME_AUDIT.md) 比對正式 VM 差異。模型預設規則模式、研究紀錄預設開啟；盤中風險及模擬帳務改為明確驗證後才發布成交。新增 `python tests/test_runtime_safety.py` 離線回歸。
