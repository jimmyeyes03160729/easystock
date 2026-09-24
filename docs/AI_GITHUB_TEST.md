# EasyStock GitHub 連線與測試分支說明文件

此檔案由 Antigravity 於測試分支 `ai/github-test` 建立，用於驗證 Git 分支管理、本地 Commit 與 GitHub 遠端儲存庫連線機制。

---

## 1. 測試分支基本資訊
* **分支名稱**：`ai/github-test`
* **建立時間**：2026-09-24
* **目的**：驗證非主分支（non-main branch）之變更提交與 GitHub 推送流程。
* **影響範圍**：
  * 僅包含說明文件與開發規則設定。
  * 不修改 `main` 主分支。
  * 不影響現有日線資料更新、盤中即時狀態或歷史資料庫。

---

## 2. 安全合規聲明
* **無機密資訊**：本提交絕不包含任何券商 API Key、Secret、Telegram Token、LINE Channel Token、Firebase Service Account 憑證、OAuth 密鑰、私鑰或 `.env` 檔案。
* **無正式部署**：本分支不包含任何會自動觸發 Oracle VM 遠端部署的自動化腳本。
* **CI 範圍**：推送至此測試分支僅會執行 `test.yml` 離線回歸測試（單元測試、靜態語法檢查），不會變更生產環境或任何線上排程。
