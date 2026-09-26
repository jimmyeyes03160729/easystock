# EasyStock｜當沖研究與模擬帳務

[開啟 Dashboard](https://jimmyeyes03160729.github.io/easystock/) · By JimmyWei

本 README 描述 repo 的可驗證行為。Oracle VM 的實際執行檔、環境設定及服務狀態必須另外核對；更新 GitHub 不會自動更新 VM。

## 當沖進場

盤中引擎接收 Shioaji Tick，透過量能雷達挑選候選股，使用已完成的 5／15 分 K。
新進場須符合 09:30–12:30、候選股、即時報價、後台價格／漲幅限制、每日 5 筆上限、模擬帳戶狀態及可用資金。

`LIVE_ENTRY_MODE` 明確區分兩種模式：

| 模式 | 進場判斷 |
|---|---|
| `rules`（預設） | 舊策略 `daytrade_score >= 76`、無 veto、至少兩項理由 |
| `model` | 固定模型檔載入成功、已核准、特徵完整、分數達 artifact 門檻，並保留策略 veto 及獨立風控；不要求舊策略分數達 76 |

模型模式缺模型、模型未核准、資料缺漏或低於門檻，一律跳過新進場，**不會自動退回規則模式**。
目前 repo 不附任何已核准模型，也不宣称 VM 已啟用模型。

## 模型與學習

研究與線上模型共用 `vm_runtime/daytrade_learning/features.py` 的 `daytrade-research-v1` 固定順序：

1. `gain_pct`：對前收盤漲跌幅（百分點）。
2. `return_5m_pct`：對約 5 分鐘前 Tick 的報酬（百分點）。
3. `surge_60s`：60 秒量能倍數。
4. `buy_ratio_60s`：可分類成交中的買盤比例（0–1）。
5. `amount_60s`：60 秒成交金額。

缺少資料不能填 0；行情 Tick 最長 30 秒，5 分鐘參考 Tick 最長 330 秒，至少 300 秒歷史與 50% 可分類成交。
`core.py` 的五欄研究原型保留獨立的 legacy schema，不能當成線上模型。歷史文件中的 11 欄 `quote-markout-pilot-1` 不符合此 schema，會被拒絕載入。

`AI_PAPER_MODEL_PATH` 固定 JSON artifact 路徑。載入器驗證 `approved=true`、`deployment_allowed=true`、schema、特徵順序、維度、有限數字及正尺度；標準化後使用 logistic score，並真正比較 `threshold`。研究 artifact 保持未核准，不能僅為上線而手改旗標。

- `LEARNING_ENABLED=1` 為預設；明確設成 `0` 才停用紀錄。
- 雷達樣本按每檔每 5 分鐘記錄，ENTRY／EXIT 記錄包含模擬成交身分及結算結果。
- `learning_cycle.py` 串接當日盤後收集／標籤建立與候選模型訓練。沒有同日樣本就跳過，不把休市日當學習日。
- 訓練要求同一設定至少 101 個日期、1,000 筆樣本及足夠正負例；不足時回報 blocked。
- 候選模型不自動核准或替換隔日模型。盤後 Gemini 文字復盤也不等於更新線上模型。
- 歷史標籤仍是固定停損停利研究基準，包含保守成本，不是線上 trailing／技術出場帳戶績效；完整策略回放與樣本外驗證仍是核准前置條件。

## 市場風險

- 盤前必須為台灣當日的 `scan_date`；硬性燈號使用 `base_risk_score`（≤35 綠、≥65 紅）。
- Gemini ±5 分保留為建議分數，`advisory_market_level` 不決定交易硬性閘門。
- 盤中每 30 秒重新讀取盤前資料並取得加權指數 Snapshot；新 SDK 使用 `IX0001`，舊 SDK 相容 `001`。
- 預設指數跌幅 ≤−1% 黃、≤−2% 紅，可用 `LIVE_INDEX_YELLOW_PCT`、`LIVE_INDEX_RED_PCT` 調整；這是明確的風險設定，非已驗證最佳參數。
- 指數來源時間最長 90 秒，檢查結果最長 45 秒。缺漏、過期、未來時間、API 失敗或盤前資料無效，停止新進場。
- 盤前與盤中取較保守燈號。既有持倉仍執行出場管理。加權指數不代表已涵蓋全部個股及櫃買風險。

## 模擬成交及出場

SQLite 為模擬帳務來源。買進會保留已持倉本金與買進手續費，單檔預算不超過本金 80%；不足一張、帳戶暫停或已有部位不產生 ENTRY。
成交後才記錄研究 ENTRY、發布 Firebase 及通知。平倉在同一 SQLite transaction 內更新本金、每日合計、事件及刪除持倉；結算失敗保留持倉，以 trade_id 防止重複結算。Firebase 為鏡像；重啟時從 SQLite 還原成交部位，過日或不一致資料須對帳。

`LIVE_EXIT_MODE` 可設：

| 模式 | 出場策略 |
|---|---|
| `hybrid`（預設，保留原策略） | 固定停利 + 移動停利 |
| `fixed` | 固定停利，不執行移動停利 |
| `trailing` | 移動停利，不因固定 +1.2% 目標出場 |

所有模式仍有固定停損、動態保本、12:55 強制平倉。技術出場預設啟用，由完成的 5 分 K 觸發；`LIVE_TECHNICAL_EXIT_ENABLED=0` 可關閉。共用同一部位鎖與結算流程。

預設停損 −0.8%、固定停利 +1.2%、移動停利 +0.6% 啟動／自高點回落 0.4%。保本設定獨立為 `LIVE_BREAKEVEN_ACTIVATE_PCT=.006`、`LIVE_BREAKEVEN_FLOOR_PCT=.0035`；保本價不是跳價時的保證成交價。固定停利亦按觀察到的模擬價格成交，不是精確封頂。

## 部署與驗證

- [本次修正、VM 核對與部署步驟](docs/DAYTRADE_RUNTIME_AUDIT.md)
- [VM 來源與環境](vm_runtime/README.md)
- [系統架構](docs/ARCHITECTURE.md)
- [2026-09-21 VM 實驗敘述封存（未重新驗證）](docs/README_VM_EXPERIMENT_2026-09-21.md)

```bash
python vm_runtime/tests/test_runtime_safety.py
python vm_runtime/daytrade_learning/test_integration.py
python vm_runtime/daytrade_learning/test_eod_fix.py
```

這些測試使用暫存資料庫／模擬外部介面，不代表 VM 已部署或通過盤中驗收。正式憑證與 `.env` 不得提交到 repo。此流程只處理模擬帳戶，不構成投資建議或收益保證。
