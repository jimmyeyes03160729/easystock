# EasyStock Daytrade Knowledge V1 與現有代碼庫映射報告 (Repository Mapping Audit)

- **審計日期**：2026-10-02
- **審計角色**：EasyStock 專案資深量化系統工程師
- **審計性質**：唯讀 Repository Audit（無代碼變更、無 Git 異動、無 VM 連線、無生產環境操作、無策略啟用）
- **主要參考規格**：`docs/daytrade_knowledge_v1/`
- **狀態標記定義**：
  - `EXISTS`：現有代碼庫已有完整對應實作與運行邏輯。
  - `PARTIAL`：已有部分實作、變形實作或計算基礎，但規格或介面尚未完全吻合。
  - `MISSING`：專案完全缺失該功能或邏輯，但底層基礎架構可能可支援擴充。
  - `UNSUPPORTED`：受限於現有資料源（無 L2、無期貨、無 Order Event 等）或硬體架構，當前無法支援。
  - `UNKNOWN`：現有代碼中存在無法由靜態代碼與文件確認其真實運行狀態之項目。

---

## 1. EasyStock 現有核心模組逐項審計 (12 大模組)

### 1.1 daytrade_learning
- **FILE_PATH**: `daytrade_learning/core.py`, `daytrade_learning/research.py`, `daytrade_learning/champion.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `daytrade_learning/research.py`: `simulate`, `fit_logistic`, `train_candidate`, `promote_candidate`
  - `daytrade_learning/champion.py`: `shadow`, `evaluate`, `freeze_once`
  - `daytrade_learning/core.py`: `Store`, `review`
- **EVIDENCE**: 實作了基於 SQLite 的事件快照、1 分 K 重建、離線 Logistic 回歸模型訓練、Walk-forward 多折驗證（至少 81 個交易日、500 個樣本門檻）、影子模型評估（`frozen_baseline`, `rolling_model`, `radar_baseline`, `formal_candidate`）。
- **STATUS**: `EXISTS`

### 1.2 intraday engine
- **FILE_PATH**: `intraday_live.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `intraday_live.py`: `compute_volume_surge_metrics`, `record_radar_tick`, `score_volume_surge`, `run_strategy_cycle`
- **EVIDENCE**: 接收 Shioaji WebSocket 逐筆 Tick 串流，維護最近 300 秒（`RADAR_HISTORY_SECONDS`）記憶體隊列，計算 `volume_60s`, `surge_60s`, `buy_ratio_60s`, `amount_60s`, `price_change_60_pct`，並排程觸發 5 分 K 策略評估與部位更新。
- **STATUS**: `EXISTS`

### 1.3 historical dataset
- **FILE_PATH**: `history/collector_core.py`, `history/daily_history.py`, `market_data/fugle_pipeline.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `history/collector_core.py`: `audit`, `Session`, `TICK_FIELDS`, `BAR_FIELDS`
  - `history/daily_history.py`: `summarize`, `eligible_failure`, `FLOOR` (2020-03-02)
- **EVIDENCE**: 透過 Shioaji 歷史 API 於每日 14:00-22:00 歸檔已完成日之股票（最多 200 檔）Tick 與分鐘 K 棒；Fugle 透過 GitHub Actions 收集隔日衝與日線清單。現有歷史資料庫存有 `(ts, close, volume, tick_type, bid_price, ask_price)` 與 1 分 K 棒，但無五檔深度掛單簿，無期貨 Tick，日線 T86 亦未解析自營商避險。
- **STATUS**: `PARTIAL`

### 1.4 feature pipeline
- **FILE_PATH**: `daytrade_learning/features.py`, `intraday_live.py`, `strategy_engine.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `daytrade_learning/features.py`: `FEATURES` (`gain_pct`, `return_5m_pct`, `surge_60s`, `buy_ratio_60s`, `amount_60s`), `vector`
  - `intraday_live.py`: `live_features`, `compute_volume_surge_metrics`
  - `strategy_engine.py`: `upper_wick_ratio`, `bar_position`, `trend_score`, `volume_score`, `calculate_vwap`
- **EVIDENCE**: 線上與研究共用 `daytrade-research-v1` 特徵契約（5 項特徵）；盤中即時計算量能爆發與內外盤買盤佔比；策略引擎計算 K 棒幾何形態與趨勢分。但特徵尚未模組化為統一行為註冊表（Registry），散落在各模組。
- **STATUS**: `PARTIAL`

### 1.5 model runtime
- **FILE_PATH**: `daytrade_learning/model_runtime.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `daytrade_learning/model_runtime.py`: `DaytradeModel`, `live_features`, `resolve_approved_model_path`
- **EVIDENCE**: 嚴格載入 `latest-approved.json`，校驗 SHA-256、schema_version、特徵維度、模型訓練有效天數（<=10交易日，否則判定 stale_model）；提供 `evaluate(features)` 計算勝率機率；若無 approved 模型則自動 fail-open/pass-through 或阻斷，具備完善防護。
- **STATUS**: `EXISTS`

### 1.6 paper trade
- **FILE_PATH**: `paper_account.py`, `position_manager.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `paper_account.py`: `buy`, `sell`, `get_account_state`
  - `position_manager.py`: `PaperWallet`, `PositionManager`
- **EVIDENCE**: 模擬撮合引擎，追蹤虛擬訂單成交、手續費、證交稅，支援市價/限價撮合代理。嚴格阻斷真實券商下單接口（不呼叫 Shioaji Order/Deal）。
- **STATUS**: `EXISTS`

### 1.7 paper ledger
- **FILE_PATH**: `paper_ledger.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `paper_ledger.py`: `buy`, `sell`, `transaction`, `init_schema`, `BUY_RATE`, `DAY_TAX_RATE`, `fee`
- **EVIDENCE**: 獨立的 SQLite 現金帳本，使用 WAL 模式與事務隔離；強制計算 28 折手續費、低消 20 元、0.15% 現股當沖證交稅；設有單檔資金 80% 上限、跨日未結部位阻斷買進等嚴格會計風控。
- **STATUS**: `EXISTS`

### 1.8 entry decision
- **FILE_PATH**: `strategy_engine.py`, `intraday_live.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `strategy_engine.py`: `evaluate_daytrade`, `trend_score`, `volume_score`, `liquidity_score`, `historical_edge_score`
  - `intraday_live.py`: `qualifies_volume_surge`, `in_entry_window` (09:30 - 12:30)
- **EVIDENCE**: 包含多維綜合評分（趨勢 30% + 量能 20% + VWAP 15% + 市場 10% + 流動性 10% + 歷史Edge 15%）；實作一票否決機制（Vetoes: 跌破VWAP、距VWAP過遠、末根爆上影、5分K破短低、市場紅燈）。
- **STATUS**: `EXISTS`

### 1.9 exit decision
- **FILE_PATH**: `position_manager.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `position_manager.py`: `PositionManager.on_tick`, `PositionManager.on_strategy_result`, `PositionManager.close_position`
- **EVIDENCE**: 支援固定停損（0.8%）、固定停利（1.2%）、移動停利（0.6%啟動/0.4%拉回）、動態保本機制（+0.6%啟動保本+0.35%稅費）、12:55 當沖強制平倉，以及 5 分 K 技術出場（跌破 VWAP、5分K 破短低）。
- **STATUS**: `EXISTS`

### 1.10 risk gate
- **FILE_PATH**: `market_risk.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `market_risk.py`: `MarketGate`, `snapshot_risk`, `premarket_context`
- **EVIDENCE**: 盤前結合 AI 晨報風險分數，盤中結合 TAIEX 即時指數快照；實作狀態機雙重確認防抖（連續 2 次確認才可自 RED 降級）；有效燈號為 RED 時產生 `gate_action = 'BLOCK'`，全面凍結開倉。
- **STATUS**: `EXISTS`

### 1.11 market regime
- **FILE_PATH**: `market_risk.py`, `strategy_rules.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `market_risk.py`: `snapshot_risk` (GREEN/YELLOW/RED)
  - `strategy_rules.py`: `technical_decision` (大盤均線與個股趨勢判斷)
- **EVIDENCE**: 現有大盤機制分為大盤三色燈號（依跌幅 -1% 與 -2% 判定）及日線趨勢；然而對族群（Sector）輪動、類股強弱對比、波動率體系（ATR Regime）則尚未具備動態劃分邏輯。
- **STATUS**: `PARTIAL`

### 1.12 tests
- **FILE_PATH**: `tests/`, `daytrade_learning/test_core.py`, `daytrade_learning/test_integration.py`
- **SYMBOL / FUNCTION / CLASS**:
  - `tests/test_market_risk_gate.py`: 測試風控閘門降級防抖與阻斷
  - `tests/test_model_runtime_governance.py`: 測試模型年齡、schema、維度與部署許可治理
  - `tests/test_research_replay.py`: 測試分鐘 K 回放與無偷看未來因果
  - `daytrade_learning/test_core.py`: 測試事件保存、K 棒入庫與訓練門檻
- **EVIDENCE**: 測試套件全面覆蓋風控防抖、模型治理、因果時鐘與資料解析。
- **STATUS**: `EXISTS`

---

## 2. 特別檢查 14 項專題深入分析

| 項次 | 專題檢查項目 | 審計結論 | 關鍵證據 (FILE_PATH / SYMBOL / DETAILS) |
|---|---|---|---|
| 1 | Knowledge V1 哪些 Feature 已存在 | **部分已存在** | `gain_pct`, `return_5m_pct`, `surge_60s`, `buy_ratio_60s`, `amount_60s` (`daytrade_learning/features.py:5`); `upper_wick_ratio` (`strategy_engine.py:54`); `calculate_vwap` (`strategy_engine.py:204`)。 |
| 2 | 名稱不同但功能相同的 Feature | **已精確定位** | 1. `upper_wick_ratio` == `F_upper_shadow_ratio` (公式完全一致)。<br>2. `bar_position` == `F_close_location_value` (CLV 為 `2 * bar_position - 1`)。<br>3. `buy_ratio_60s` == `F_aggressor_buy_share` (完全一致)。<br>4. `price_vs_avg_pct` / `vwap_distance` == `F_dist_to_vwap_pct`。<br>5. `surge_60s` == `F_volume_ratio_5m` 的 60 秒滾動等價物。 |
| 3 | 缺失 Feature | **已盤點列管** | 1. `F_turnover_rate_intraday` (缺少發行股數)。<br>2. `F_pullback_vol_decay_ratio` (缺少拉回/衝刺段因果分割器)。<br>3. `F_quote_flip_rate_1m` (缺少逐筆報價檔位跳動流)。<br>4. `F_dealer_hedging_share_ratio_eod` (T86 解析器丟棄自營商避險)。<br>5. `F_futures_basis_pct` (未訂閱台指期合約)。 |
| 4 | 現有歷史資料是否可支援 | **部分支援** | 可支援 1 分 K 與 5 分 K 日內特徵回測；可支援目標池歷史 Tick（含 `tick_type`）；**無法支援** L2 五檔深度掛單簿、台指期貨即時串流、T86 自營商避險資料。 |
| 5 | Tick 資料能力 | **具備即時串流，歷史局部歸檔** | `intraday_live.py:3304` `record_radar_tick` 維護記憶體 300 秒逐筆緩衝隊列；`history/collector_core.py:22` 歸檔 `(ts, close, volume, tick_type, bid_price, ask_price)`，但不保留全市場歷史 Tick。 |
| 6 | L2 / 五檔能力 | **UNSUPPORTED** | Repo 中 `intraday_live.py` 僅訂閱 `TickSTKv1`，無 `BidAskSTKv1`；歷史爬蟲亦無五檔欄位。 |
| 7 | 是否只有 snapshot | **混合架構** | 股票行情為 **即時 Tick 事件流**；大盤 TAIEX 為 **定時快照 (Snapshot)**；日線與選股為 **每日靜態快照**。 |
| 8 | 是否真的有 cancellation / order event | **完全不存在 (UNSUPPORTED)** | 台灣交易所不公開逐筆撤單流，Shioaji API 亦無台股撤單事件流。Knowledge V1 之「100ms 撤單/假單」只能作為無依據之代理假說。 |
| 9 | 是否能辨認 aggressor side | **EXISTS (完全支援)** | `intraday_live.py:1816` `tick_type_value` 直接讀取 Shioaji Tick: 1=外盤（主動買）、2=內盤（主動賣）、0=無法判定。`buy_ratio_60s` 依此精確計算。 |
| 10 | 是否能計算即時 VWAP | **EXISTS (兩種口徑)** | 1. 交易所官方全日成交均價：`intraday_live.py:2360` 讀取 `average_price`。<br>2. 5分K Typical Price VWAP：`strategy_engine.py:204` `calculate_vwap`。 |
| 11 | sector / index / market regime 現況 | **Index 已完備，Sector 缺失** | 指數風控閘門 `MarketGate` 完整運作；`update_market.py` 有靜態 `category`，但盤中與回測缺乏動態類股指數、資金流向與族群領頭羊計算引擎。 |
| 12 | look-ahead bias 風險 | **防護良好，已知邊界** | `daytrade_learning/research.py:281` 採信號後次分 K Open 進場（加 2 秒延遲）；`strategy_rules.py:98` 檢查行情日期。但須防範未完成棒之 OHLC 洩漏與非 PIT 股本/分類。 |
| 13 | 哪些 Knowledge V1 規則目前不能回測 | **5 條規則受阻** | `AQ_R_004` (無期貨及自營避險)、`AQ_R_005` (無台指期委買賣)、`AQ_R_007` (無五檔厚牆掛單)、`AQ_R_009` (無類股同步回放)、`AQ_R_010` (現有引擎不支援融券賣出/回補回測)。 |
| 14 | 哪些功能其實 repo 已有，不應重複開發 | **7 大核心能力禁區** | 詳見第 4 節「嚴禁重複開發功能清單」。 |

---

## 3. Knowledge V1 候選特徵與代碼庫映射表

| Feature ID | 候選特徵名稱 | Knowledge V1 狀態 | Repo 對應 Symbol / 檔案 | Repo 狀態 | 差異說明與處置 |
|---|---|---|---|---|---|
| `F_body_ratio` | 實體佔比 | AI_QUANTIZED | `strategy_engine.py` (OHLC可用) | `PARTIAL` | 可由 K 棒導出，無獨立欄位名。 |
| `F_body_return_pct` | 實體漲幅比率 | AI_QUANTIZED | `strategy_engine.py` (OHLC可用) | `PARTIAL` | 可由 K 棒導出，現有使用 `price_change_60_pct`。 |
| `F_upper_shadow_ratio` | 上影線比例 | AI_QUANTIZED | `strategy_engine.py:54` (`upper_wick_ratio`) | `EXISTS` | 名稱不同，公式完全相同。 |
| `F_lower_shadow_ratio` | 下影線比例 | AI_QUANTIZED | `strategy_engine.py:41` (`bar_position`) | `PARTIAL` | 目前僅有 K 棒位置，可補足下影線計算。 |
| `F_close_location_value` | 收盤位置值 (CLV) | AI_QUANTIZED | `strategy_engine.py:41` (`bar_position`) | `PARTIAL` | `bar_position` 區間為 [0, 1]，CLV 為 [-1, 1]。 |
| `F_gap_open_pct` | 開盤跳空幅度 | AI_QUANTIZED | `daytrade_learning/model_runtime.py:44` (`gain_pct`) | `PARTIAL` | 開盤初段等價於 `gain_pct`，無獨立持久化欄位。 |
| `F_ma_alignment_score` | 均線多頭排列分 | AI_QUANTIZED | `strategy_rules.py:39`, `strategy_engine.py:132` | `PARTIAL` | 現有多頭判定為布林值，非整數計分。 |
| `F_dist_to_prev_high_pct` | 距前高幅度 (High) | AI_QUANTIZED | `strategy_rules.py:30` (`near_high_ratio`) | `PARTIAL` | 日線有靜態前高比例；盤中有 ORB/前 6 根高點。 |
| `F_dist_to_prev_close_high_pct` | 距前高幅度 (Close) | AI_QUANTIZED | 無 | `MISSING` | 未區分 High-based 與 Close-based 前高。 |
| `F_dist_to_vwap_pct` | 距 VWAP 幅度 | AI_QUANTIZED | `strategy_engine.py:539` (`vwap_distance`), `intraday_live.py:2364` (`price_vs_avg_pct`) | `EXISTS` | 實質功能已存在且納入進出場決策。 |
| `F_relative_volume_open` | 早盤歷史相對量 | AI_QUANTIZED | `intraday_live.py:2272` (`surge60`) | `PARTIAL` | 現為日內前幾分鐘滾動基準，非跨日同刻基準。 |
| `F_volume_ratio_5m` | 5分K相對成交量 | AI_QUANTIZED | `strategy_engine.py:263` (`volume_score`) | `PARTIAL` | 使用 3 根對比前 9 根，邏輯等價。 |
| `F_volume_acceleration` | 成交量加速度 | AI_QUANTIZED | `intraday_live.py:2282` (`acceleration10`) | `PARTIAL` | 現有為 10 秒量比預期量，非二階差分。 |
| `F_turnover_rate_intraday` | 日內週轉率 | AI_QUANTIZED | 無 | `MISSING` | 未取得發行股數，無此計算。 |
| `F_pullback_vol_decay_ratio` | 拉回段量縮比率 | AI_QUANTIZED | 無 | `MISSING` | 缺乏波段高低因果分割邏輯。 |
| `F_order_book_imbalance_5` | 五檔委買賣失衡 (OBI) | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無 L2 五檔委託資料源。 |
| `F_order_book_imbalance_weighted` | 加權 OBI | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無 L2 五檔委託資料源。 |
| `F_aggressor_buy_share` | 主動買盤份額 | AI_QUANTIZED | `intraday_live.py:2304` (`buy_ratio_60s`) | `EXISTS` | 透過 Shioaji `tick_type` 直接計算，完全符合。 |
| `F_trade_aggressiveness_ratio` | 買賣積極度差額比 | AI_QUANTIZED | `intraday_live.py:2304` (`buy_ratio_60s`) | `EXISTS` | 數學上等於 `2 * buy_ratio_60s - 1`，功能等價。 |
| `F_bid_wall_thickness_ratio` | 買方大單牆厚度比 | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無 L2 五檔深度掛單簿。 |
| `F_bid_wall_mean_ratio` | 買方均值牆比率 | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無 L2 五檔深度掛單簿。 |
| `F_quote_flip_rate_1m` | 買賣報價跳動頻率 | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無逐筆委託報價跳動串流。 |
| `F_wall_depletion_velocity` | 大單牆消耗速度 | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無掛單明細與撤單事件。 |
| `F_dealer_hedging_ratio_eod` | 自營商避險金額比 | SOURCE_MISMATCH | 無 | `MISSING` | `parse_twse_t86` 未解析自營商欄位。 |
| `F_dealer_hedging_share_ratio_eod` | 自營商避險股數比 | AI_QUANTIZED | 無 | `MISSING` | `parse_twse_t86` 未解析自營商欄位。 |
| `F_futures_basis_pct` | 台指期現貨基差率 | AI_QUANTIZED | 無 | `MISSING` | 僅訂閱大盤加權 `IX0001`，未訂閱台指期。 |
| `F_tx_traded_lots_spread` | 台指期主動買賣口數差 | SOURCE_MISMATCH | 無 | `UNSUPPORTED` | 無期貨 Tick 串流。 |
| `F_sector_lead_lag_return_diff` | 族群領頭羊收益差 | AI_QUANTIZED | 無 | `MISSING` | 缺乏跨股票即時 PIT 族群連動引擎。 |
| `F_futures_bid_ask_spread_pct_book` | 期貨買賣價差率 | AI_QUANTIZED | 無 | `UNSUPPORTED` | 無期貨 L1 報價串流。 |

---

## 4. 嚴禁重複開發功能清單 (Do NOT Re-invent)

下列功能在 EasyStock repo 中已具備高度成熟、健全且經單元測試驗證之實作，後續研究與開發**嚴禁重複編寫或推倒重來**：

1. **逐筆內外盤主動成交判定器 (Aggressor Tick Classifier)**
   - 所在檔案：`intraday_live.py:1816` (`tick_type_value`) 與 `intraday_live.py:2287-2309`。
   - 說明：直接解析 Shioaji 原生提供之 `tick_type` (1=外盤買, 2=內盤賣, 0=未定)，並於 60 秒滑動窗口內計算 `buy_ratio_60s`。嚴禁再用 Lee-Ready 等 quote-rule 進行猜測重造。
2. **大盤風控閘門與降級防抖狀態機 (MarketGate Risk State Machine)**
   - 所在檔案：`market_risk.py:67` (`MarketGate`)、`market_risk.py:26` (`snapshot_risk`)。
   - 說明：已完備盤前晨報風險與盤中 TAIEX 即時漲跌幅整合，支援連續 2 次確認才准自 RED 降級之防抖機制，RED 狀態全面產生 `BLOCK` 阻斷信號。嚴禁重新造輪子。
3. **獨立 SQLite 現金帳本與當沖會計風控 (Paper Ledger SQLite Transactions)**
   - 所在檔案：`paper_ledger.py`。
   - 說明：支援 ACID 交易、28 折手續費、低消 20 元、0.15% 證交稅、單檔 80% 資金上限、跨日持倉防護。嚴禁另造無交易隔離之記憶體假帳本。
4. **多重動態出場與保本引擎 (PositionManager Exit Engine)**
   - 所在檔案：`position_manager.py:75`。
   - 說明：固定停損、固定停利、移動停利、動態保本機制（+0.6% 觸發保本 +0.35%）、12:55 強制出場、技術面破 VWAP 出場已全部實作且支援並行安全（`@synchronized`）。
5. **模型冠軍/挑戰者與影子治理體系 (Champion/Challenger Model Governance)**
   - 所在檔案：`daytrade_learning/champion.py`, `daytrade_learning/model_runtime.py`。
   - 說明：涵蓋 `frozen-baseline`、`latest-approved`、模型年齡檢查（<=10交易日）、Brier score、多折 Walk-forward 驗證，禁止繞過此模型門禁機制。
6. **K 棒幾何形態與實體比例計算 (Bar Geometry Tools)**
   - 所在檔案：`strategy_engine.py:41` (`bar_position`)、`strategy_engine.py:54` (`upper_wick_ratio`)。
   - 說明：上影線佔比與 K 棒收盤位置計算已內建且處理邊界防除零。
7. **不可變批次日線發布體系 (Immutable Market Data Releases)**
   - 所在檔案：`market_data/publish.py`, `update_market.py`。
   - 說明：歷史發布遵守版本化發布契約，避免直接破壞活躍盤中版本。
