# 02 開盤八法・尾盤八法

## 檔案清單（27 檔）

修改：index.html、assets/dashboard-layout.js、llm_paper/run.py、package.json、tests/test_asset_versions.cjs、tests/test_dashboard.cjs、tests/test_mobile_nav.cjs。

新增：assets/eight-methods.js、eight_methods/__init__.py、eight_methods/rules.py、eight_methods/feed.py、paper_helpers.py、deploy/easystock-eight-methods.service、deploy/easystock-eight-methods.timer、deploy/retire_short_term.sh、docs/EIGHT_METHODS.md、tests/test_eight-methods.cjs、tests/test_eight_methods.py、tests/test_paper_helpers.py。

移除：assets/short-term.js、short_term/__init__.py、short_term/feed.py、deploy/easystock-short-term.service、deploy/easystock-short-term.timer、deploy/install_short_term.sh、tests/test_short_term.cjs、tests/test_short_term_feed.py。

獨立觀察模組 OPENING_EIGHT_METHODS_V1 / CLOSING_EIGHT_METHODS_V1，不下單、不訓練模型、不讀封存 holdout。03 共用函式已移至 paper_helpers.py；營收研究與治理證據保留。

開盤編號依 https://www.yunfar.com.tw/GBSSKILL/starting-8ways.html ：UUU、UUD、UDD、DUU、DDU、DDD、DUD、UDU。每個時點使用不晚於該時點、30 秒內的最近成交；缺 Tick 與平盤不分類。09:15 之前不公布結果。

台股規則 TW_XQ_SCRIPT_V1 依 https://www.xq.com.tw/xstrader/大陸股神楊永興的尾盤八法/ 的實際腳本（非文中另一段 50–300 億建議）：漲幅 3–5%、累積股數 / 過去五日平均股數 > 1、換手率 2–10%、總市值 50–500 億 TWD、今日量 > 昨日量且昨日量 > 前日量 × 0.8、MA5 > MA20 > MA60 且 MA60 上升、同時點漲幅強於所屬大盤、價格 ≥ 日高 × 0.98。均線包含截至觀察時點的當日價格；歷史日 K 僅限之前的交易日。13:25 起全部觀察訊號截止（採更嚴格的排除邊界）。

CN_ORIGINAL_V1 獨立保存大陸門檻（換手率 5–10%、50–200 億 CNY、持續放量、短均線與 60 日線向上、尾盤新高且不破均線）。其定性項目未量化，不啟用，不借用台股條件。

現有來源盤點：Shioaji journal 每五分鐘記錄價格與真實 quote_at；a_candidates 即時投影提供有成交時間戳的有限股票；官方 market-daily.sqlite 提供交易日、昨收與歷史日 K。只唯讀一般 bars / sessions / indices，沒有讀標籤、holdout 或績效。Shioaji 歷史 archive 為盤後流程，不能填今日缺 Tick；玉山現有指數 REST 僅提供加權當下漲幅，未提供三個歷史時點，不能假冒開盤資料。public_feed 的 updated_at 是本機接收時間，volume 是單筆量，故不作本模組輸入。沒有新券商請求或 WebSocket。

目前可由現有來源計算：有新鮮價格且有昨收時的當日漲幅、有足夠日 K 時的均線趨勢；journal 有各邊界成交時才分類開盤。現有投影沒有可靠累積量、換手率、市值、完整當日高點及完整上市櫃指數成交序列，其他項目逐項不足。計算器已支援這些欄位，但預設 adapter 不捏造或啟用它們。觀察股票限來源實際出現者，不代表全市场掃描；指數卡片是資料狀態，不是候選股票。

VM 待人工授權：先執行 `python -m eight_methods.feed`（預設僅寫獨立輸出目錄，不發布），確認來源路徑、schema 與行情覆盖，再安裝 deploy/easystock-eight-methods.service / timer；`--publish` 僅寫 public_feed/opening_eight 與 closing_eight。舊 scheduler 用 deploy/retire_short_term.sh 停用並清理 unit，保留資料庫與歷史 JSON。新 unit 尚未安裝；網站需一併部署。未修改交易引擎與 vm_runtime 固定鏡像，不啟用 Actions。

## 2026-10-13 驗證紀錄

基準 main：666ad08。六個共用 helper 的 AST 與原 feed 完全相同。新增八法、helper 與原 03 測試合計 32 passed。npm test 的 node:test 集 71 passed，其他連鎖 frontend/UI/chart/asset/revenue/B-lane 檢查均通過；額外 Paper limit UI 通過。Chrome extension 兩種套件建置成功、41 tests passed。Chrome headless 390px 與 1280px 檢查新區塊無橫向溢出。

VM 僅在 /tmp/easystock-eight-test.WTGCqd8s 測試副本執行，未替換正式 checkout 或啟停服務。`pytest tests -q`：901 passed、5 failed、2 skipped、59 subtests passed。用原始 main 再跑相關三檔測試，重現完全相同的五個失敗：test_admin_order_safety 一項、test_model_runtime_governance 一項、test_owner_live_console 三項。原因為既有訂單測試 MagicMock JSON 序列化/500 對 403，以及模型 identity 回傳 approved-model-gate-v3 對預期 v-test；未刪除或放寬斷言。

CI 的 Python 獨立腳本皆已執行。部分額外檢查仍受環境與既有鏡像限制：daytrade_learning/test_core.py 兩個錯誤為缺 sklearn，VM Python 3.10 無法滿足 repo 指定 scikit-learn 1.8.0（需 Python >=3.11）；vm_runtime/easystock_admin/test_admin.py 九個錯誤為固定鏡像缺 release 模組；通知鏡像原直接執行缺 PYTHONPATH，補上 CI 的 PYTHONPATH=. 後 11 項通過。Windows 全 repo pytest 尚有 fcntl 與同名鏡像收集衝突。Linux shell 檢查需正規化 Windows checkout 的 CRLF；原腳本正規化後語法通過。不能宣稱全 repo 全綠。

以今日真實 journal 和官方日 K 唯讀計算，截點 2026-10-13 13:20 Asia/Taipei：308 檔觀察股票、6 檔開盤可分類、302 檔資料不足、來源解析無診斷錯誤。該截點 journal 尾盤價格全部不新鮮，沒有捏造候選／通過項目；正式 publisher 的即時價格另讀既有 a_candidates，仍不補不存在的量、換手與市值。指數資料不足會如實呈現。這是來源可用性驗證，非策略績效或 holdout 比較。

唯讀確認舊 easystock-short-term.timer 仍 enabled。退役及新排程均需部署授權；尚未發布新 Firebase feed 或網站。
