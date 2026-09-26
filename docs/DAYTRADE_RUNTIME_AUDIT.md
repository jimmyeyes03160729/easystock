# 當沖 Runtime 核對與修正（2026-09-27）

## 修正範圍

- 模型模式驗證核准狀態、schema、缺值及分數門檻，禁止隱性退回規則模式。
- 研究／線上特徵集中定義；legacy 研究仍隔離。修正 README 未區分 repo 與 VM 的敘述。
- 盤前日期／基礎風險分數驗證，AI 新聞分數只作建議。每 30 秒讀取加權指數，資料逾時停止新進場。
- 模擬買進先提交 SQLite 才記錄 ENTRY。模擬平倉及日結統計原子提交，失敗保留部位，trade_id 防止重複結算。
- 持倉保留現金、手續費及跨股票並行買進保護；重啟從 SQLite 對帳恢復。
- 明確分開 fixed／trailing／hybrid 出場模式及保本參數，技術出場共用部位鎖與結算；預設保留 hybrid。
- 收集紀錄預設啟用；新增每日盤後樣本→標籤→候選模型排程。沒有當日樣本不執行。
- 模型應用狀態不再把「檔案可載入」當成「VM 實際已應用」。

## 驗證邊界

使用離線暫存 SQLite、模型 fixture、模擬 API。尚未驗證正式 VM 的版本、Shioaji 指數訂閱／快照權限、正式資料下的整日流程。
雲端 SSH 嘗試回傳 Network is unreachable，未進入金鑰驗證；這不表示 VM 或金鑰本身故障。

研究 labels 仍是固定停損／停利的保守基準，不能當成完整線上策略淨收益。候選模型預設禁止部署；沒有產生或宣稱任何已驗證模型。

## 本機 Codex／Windows 的 VM 核對

在有現成 SSH 金鑰的 Windows 電腦，先取得此分支程式。金鑰保持在本機，不放入 repo 或服務環境檔。

```powershell
# 在 repo 目錄執行。將 <VM_HOST> 換成現有 Oracle VM IP。
Get-Content -Raw .\deploy\audit_vm_runtime.py | ssh -i "$HOME\.ssh\oracle-easystock.key" ubuntu@<VM_HOST> "python3 - /home/ubuntu/easystock"
```

核對程式只輸出 Git HEAD、已追蹤檔案異動、來源／執行檔雜湊及服務狀態，不輸出憑證內容。

若 VM 實際程式與 repo 不同，先備份並讀取差異，尤其檢查現有 11 特徵 AI 實驗、模擬帳務及環境變數；不能把此五特徵修正當成相同版本直接覆蓋。

## 部署流程

1. 核對 `systemctl cat` 的 WorkingDirectory／ExecStart，確認實際服務讀的是哪套來源（此內容只在本機檢視，不公開貼出環境中的秘密）。
2. 備份現行程式、systemd unit、模擬 SQLite（含一致性備份）及現有環境檔；保留 VM 未提交修改。
3. 確認沒有未結束或需要對帳的模擬持倉；核對此分支與 VM 程式差異。跨日或歷史無日期持倉不會自動刪除。
4. 在 VM 的獨立測試環境跑 README 的測試，再用可用券商唯讀行情驗證 `IX0001`（舊版 `001`）Snapshot 時間戳、漲跌幅及讀取權限。
5. 停止相關盤中／學習 timer 及 service，避免安裝途中排程啟動；保留原啟用狀態供完成後恢復。
6. 將核對完成的 commit 放到 `/home/ubuntu/easystock`，執行 `python3 deploy/install_intraday_runtime.py --check-only`，再執行 `python3 deploy/install_intraday_runtime.py`。installer 檢查來源已提交、服務已停止、語法，備份並安裝；失敗回復來源，不啟動盤中服務。
7. 確認既有 `.env`：`LIVE_ENTRY_MODE=rules`、`LEARNING_ENABLED=1`。若設 `model`，須另外提供符合 README 契約且真正核准的 `AI_PAPER_MODEL_PATH`。既有 11 特徵模型不相容，勿僅修改 schema 標籤。
8. 盤後 pipeline 使用 `/home/ubuntu/easystock-learning-venv/bin/python`，須有 VM requirements 及 `scikit-learn==1.8.0`。先核對既有 learning timers，避免同時安裝兩套排程，再安裝 `deploy/easystock-research-cycle.service` 與 `.timer`，執行 `systemctl daemon-reload` 並啟用選定的單一 timer。
9. 在下一個交易日驗收風險狀態、模擬資金不足、ENTRY／EXIT、盤後報告與 training-status。休市／無樣本日應 skipped；樣本不足應 blocked；不是模型部署成功。

## 設定與實際影響

- 指數紅燈預設 −2%、黃燈 −1%。來源最長 90 秒、檢查最長 45 秒；資料取得失敗停止新進場，但不停止既有持倉出場。
- 盤前風險採當日 base score，因此 AI 建議不再改變硬性燈號。若盤前報告缺 base score，需更新盤前程式並重新產出。
- `LIVE_EXIT_MODE=hybrid` 保留固定目標。只有明確改成 `trailing` 才移除固定目標出場；這個選擇未經績效優化。
- 強制平倉結算失敗時保持持倉，每 5 秒重試至服務結束；不能保證外部資料故障時仍能在指定價格完成。
- SQLite 帳務為來源，Firebase／通知是鏡像。外部發布失敗會記錄錯誤；仍需 VM 驗收與監控，不能宣稱完整跨服務 exactly-once。

## 秘密檔案

`.gitignore` 已排除 `.env`、client_secret、SSH key、PEM、SQLite。核對工具不讀取或輸出秘密內容；本修正沒有把金鑰加入版本控制。
