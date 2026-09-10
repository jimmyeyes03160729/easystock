# Easystock 當沖學習模組 — 第一期研究版

此資料夾是既有大改版的新增模組，可直接加入 GitHub 根目錄。
它尚未接入 Oracle VM 正式當沖服務；單純上傳 GitHub 不會開始收集、排程、呼叫 Gemini 或改變推薦。
不包含先前首頁大改版的交付檔案。

## 已完成

- SQLite 不可覆寫事件快照、完成分鐘 K、實際／模擬結果分開保存。
- 強制檢查推薦當時最新價格的漲幅與價格區間；價格等於上限可通過、超過則排除。
- 過期／未來行情及不一致的漲幅資料拒絕使用；缺少資料不補零。
- 收盤掃描已保存的連續分鐘 K，列出五分鐘收盤價漲幅達 2% 的事件；2% 是初版研究定義，不是推薦條件，也不代表已涵蓋全市場。
- Gemini 收盤研究摘要。只送計算後統計及急漲事件，不送金鑰、持倉或私人資料；假設不能直接變成交易規則。
- LogisticRegression 候選訓練：至少 81 個交易日期與 500 個模擬樣本，同一套政策、股票池及後台設定；保留最後 20 日期測試，間隔 1 日期。
- 新舊策略使用同一段測試資料比較扣成本後平均報酬與勝率，輸出模型係數及 Brier score。
- 永遠不自動升級正式模型。尚未實作資金／重疊持倉模擬、組合最大回撤、多期 walk-forward、前瞻影子運行與正式切換，故不能當作可部署模型。

## 接線前需要的 VM 程式

請提供去除硬編碼密鑰後的：
1. 真正寫入 `/market_data/intraday_live` 的當沖主程式。
2. 取得 Shioaji 行情、FirebaseStore、選股、進出場及尾盤報表的相關模組。
3. `stock_command_service.py` 與 LINE 相關模組、systemd service/timer 設定。

保留原本 VM 密鑰與環境檔；只編輯供檢查的副本，不要上傳 .env、服務帳號 JSON 或 SSH 私鑰。
拿到程式後，才能完成資料欄位轉換、盤中捕捉、未成交／停損停利模擬、交易日排程、Firebase 報表發布與網站顯示。
目前沒有認證的 VM 連線，沒有在你的 VM 執行或重啟任何服務。

## 在 VM 暫存檢查（不會啟動正式服務）

把此資料夾放在 `/home/ubuntu/easystock/daytrade_learning`。
以下命令一次一行執行，只檢查 Python 語法與建立獨立研究資料庫：

```bash
cd /home/ubuntu/easystock
.venv/bin/python -m py_compile daytrade_learning/core.py
mkdir -p /home/ubuntu/easystock-learning-data
chmod 700 /home/ubuntu/easystock-learning-data
.venv/bin/python daytrade_learning/core.py --db /home/ubuntu/easystock-learning-data/research.sqlite review --date 2026-09-10
```

尚未接入資料時顯示 events=0 是正常的，不代表今天没有急漲股票。
研究 SQLite 放在 repo 外，不要上傳 GitHub；WAL 模式請使用 SQLite backup API 備份，不要只複製正在寫入的 .sqlite 檔。

训练另用獨立環境，不變更正式當沖服務套件：

```bash
python3 -m venv /home/ubuntu/easystock-learning-venv
/home/ubuntu/easystock-learning-venv/bin/python -m pip install -r daytrade_learning/requirements.txt
/home/ubuntu/easystock-learning-venv/bin/python daytrade_learning/test_core.py
/home/ubuntu/easystock-learning-venv/bin/python daytrade_learning/core.py --db /home/ubuntu/easystock-learning-data/research.sqlite train
```

資料不够會顯示 blocked，這是預期行為，不能改小門檻來宣稱模型有效。
不要將 tests 中的合成資料匯入正式研究資料庫。

## 資料介面（供接線實作）

`Store.capture(event)`：在現有當沖選股評分前保存所有候選，包含未入選與一般對照股票；回傳 id。
每次送 LINE 前另取最新行情重新呼叫 `gate(snapshot, settings)`，不能重用原先推薦時的檢查结果。
初版行情時效上限 60 秒是資料檢查預設，接入後應依資料源刷新頻率進一步檢討。

必要 event 欄位：

| 欄位 | 意義 |
| --- | --- |
| symbol | 股票代號字串 |
| observed_at / quote_at / features_as_of | 決策、行情、特徵最後資料的 ISO 時間，必須含時區 |
| price / previous_close | 当時價格／昨收，正數 |
| settings | min_price、max_price、max_gain_pct 三欄 |
| policy_version / universe_version | 策略與股票池版本 |
| baseline_selected | 原正式策略是否會推薦，boolean |
| features | gain_pct、return_5m_pct、volume_ratio、vwap_distance_pct、market_gain_pct |

百分比用百分點：7 表示 7%，不要填 0.07。volume_ratio 是倍數。
volume_ratio 必須用當時可取得的歷史同時段基準計算；VWAP 只用到決策時刻。
features_as_of 的檢查無法證明來源一定無偷看未來：轉接程式仍須確保計算窗口、新聞發布時間、股池與政策版本正確。
原始快照可能含不必要資料，轉接器應只傳上述允許欄位。

`Store.bar(bar)`：symbol、at（已完成一分鐘 K 結束時間）、available_at、open、high、low、close、volume。
只接入一般交易時段 K；同一分鐘資料修正需另外保留版本，不覆寫舊資料。

`Store.outcome(result)`：id、kind（actual 或 simulation）、execution_policy、entry_at、exit_at、entry_price、exit_price、shares、cost_twd。
價位須已反映滑價；cost_twd 必須包含進出手續費及賣出交易稅，按實際帳戶、商品及當時規則計算，沒有內建假設費率。
只接受當日決策後的進出場；未成交不填假成交，也不算成功／失敗。
每個候選的模擬須使用一致的、事前固定的進場延遲、停損停利和最晚出場規則；同 K 同碰停損停利應用更細行情或保守判定。
同一事件的 actual 和 simulation 若都需保留，接線時需擴充 outcome 複合鍵；目前每事件只接受一份結果。

CLI 可依序匯入 JSONL，每行 `{"type":"event|bar|outcome","data":{...}}`；事件需先於結果。
逐行入庫，重跑相同紀錄不重複寫入，衝突就停止並保留此前已匯入資料。

## Gemini

`GEMINI_API_KEY`、`GEMINI_REVIEW_MODEL` 由服務環境提供，不在程式寫死；模型名稱要選你帳戶可用且支援 generateContent 結構化輸出的版本。
模組不自動讀取既有 .env，也不修改現有盤前 Gemini 程式。
待接線完成後的明確呼叫方式：

```bash
.venv/bin/python daytrade_learning/core.py --db /home/ubuntu/easystock-learning-data/research.sqlite review --date 2026-09-10 --gemini
```

此命令會在環境金鑰及模型已設定時送出一次 Gemini API 請求，可能產生 API 費用。開發驗證沒有實際呼叫 Gemini。
沒設定金鑰或 Gemini 失敗仍保留計算統計。AI 输出只供研究，不能作為模型輸入或改動推薦。
現版本未接新聞，所以不會聲稱知道個股上漲原因。

## 後續排程與更新

預定在台灣交易日收盤行情完整後執行一次研究報表，建議目標 14:10；這是設計目標，尚未新增任何 timer。
正式接線需處理交易日曆、資料到齊重試、排程重入鎖、按日期冪等及執行紀錄。樣本不足不訓練；候選訓練可每週執行，通過前瞻驗證後才考慮升級。

正式版本更新前會建立獨立程式備份、確認真實服務名稱，再提供完整部署與回復命令。
此版本只新增目錄，因此停用研究呼叫即可停用；不可拿研究副本覆蓋你的正式當沖服務。

參考：
- https://ai.google.dev/gemini-api/docs/structured-output
- https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html
