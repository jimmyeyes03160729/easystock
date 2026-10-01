# EasyStock Daytrade Knowledge V1 Phase 1 研究實作報告 (Phase 1 Implementation Report)

- **實作日期**：2026-10-02
- **執行角色**：EasyStock 專案資深量化系統工程師
- **實作性質**：Phase 1 Research-Only Implementation（純研究實作、無生產行為變更、無實單、無 VM 部署、無 Git 異動）
- **核心合規宣告**：
  1. 未修改任何 production strategy 行為，未更動 `strategy_engine.py` 現有判斷結果。
  2. 未更動 `PositionManager` 停損停利機制與 `MarketGate` 風控狀態機。
  3. 未實作任何 `UNSUPPORTED` 功能（無假 L2 五檔、無假撤單流、無假期貨）。
  4. 候選規則（Candidate Rules）僅為離線評估器，絕不觸發任何真實或模擬委託。

---

## 1. 檔案異動清單

### 1.1 新增檔案 (12 個)
- **研究模組架構**：
  - `daytrade_learning/knowledge_v1/__init__.py`：Phase 1 研究套件初始化。
  - `daytrade_learning/knowledge_v1/registry.py`：研究特徵註冊表（區分四類狀態，定義因果與缺失數據策略）。
  - `daytrade_learning/knowledge_v1/causal_tools.py`：因果時鐘序列（`CausalBarSeries`）與無偷看未來波段確認器（`CausalSwingSegmenter`）。
  - `daytrade_learning/knowledge_v1/features.py`：優先候選特徵計算器與對應既有代碼之 Reusable Wrappers。
  - `daytrade_learning/knowledge_v1/rules.py`：5 大研究候選規則評估器（僅回傳 candidate 結構，門檻嚴格取自 Grid）。
  - `daytrade_learning/knowledge_v1/backtest_dataset.py`：研究回測資料集構建器（前向報酬、MFE/MAE、交易成本估算）。
- **測試套件**：
  - `tests/test_knowledge_v1_phase1.py`：涵蓋單元測試、因果時鐘、無偷看未來數學證明與回測構建器測試。
- **交付與規格 YAML**：
  - `implemented_features.yaml`：已實作之 17 項新研究特徵清單。
  - `reused_features.yaml`：已複用現有代碼庫之 5 項特徵對照表。
  - `unsupported_features.yaml`：受限於資料源而隔離之 13 項特徵清單。
  - `candidate_rules.yaml`：5 大研究候選規則評估器規格。
  - `phase1_implementation_report.md`：本實作報告。

### 1.2 修改現有檔案 (0 個)
- **修改檔案數：0**。所有新增代碼高內聚在獨立命名空間 `daytrade_learning/knowledge_v1/`，徹底杜絕污染正式生產與線上推論代碼。

---

## 2. 既有代碼複用 (Reused Existing Symbols)

為落實「不重複造輪子」之工程原則，本輪精確映射並複用了以下既有功能（經 Phase 1 Fix 強化為防禦型包裝）：

| 候選特徵 ID | 複用之現有 Symbol | 所在檔案 | 映射關係與原理 |
|---|---|---|---|
| `F_upper_shadow_ratio` | `upper_wick_ratio` | `strategy_engine.py:54` | **PARTIAL_REUSE_WRAPPER**：正常 K 棒複用計算；遇到 $H \le L$ 嚴格回傳 `None` 防禦，不修改生產端回傳 0.0 之行為。 |
| `F_close_location_value` | `bar_position` | `strategy_engine.py:41` | **PARTIAL_REUSE_WRAPPER**：正常 K 棒線性映射為 $2 \times \text{bar\_position} - 1 \in [-1, 1]$；$H \le L$ 嚴格回傳 `None`，不修改生產端回傳 0.5 之行為。 |
| `F_dist_to_bar_vwap_pct` | `calculate_vwap` | `strategy_engine.py:204` | **PARTIAL_REUSE**：複用現有 5分K 典型價格 VWAP。 |
| `F_dist_to_broker_avg_price_pct` | `price_vs_avg_pct` | `intraday_live.py:2385` | **PARTIAL_REUSE**：複用現有交易所官方即時累計均價。 |
| `F_aggressor_buy_share` | `buy_ratio_60s` | `intraday_live.py:2304` | **PARTIAL_REUSE**：直接複用 Shioaji Tick `tick_type`（1=外盤買, 2=內盤賣）之買量比例，可分類量為 0 時回傳 `None`。 |
| 交易成本模型 | `BUY_RATE`, `DAY_TAX_RATE`, `fee` | `paper_ledger.py:17-40` | **IDENTICAL**：回測資料集強制扣除 28 折手續費、低消 20 元與 0.15% 證交稅。 |

---

## 3. 測試驗證結果 (Test Results)

執行測試命令：`python -m unittest tests/test_knowledge_v1_phase1.py`

```text
Ran 29 tests in 0.015s
OK
```

### 關鍵測試覆蓋內容：
1. **Feature Unit & Semantics Tests**：驗證 `body_ratio`, `body_return_pct`, `lower_shadow_ratio`, `gap_open_pct`, `volume_acceleration`, `dist_to_prev_high_pct`, `intraday_return_nm`, `aggressor_flow` 數值計算之精確性；證明遇到 $H \le L$、缺少報價或無成交量時，函數皆安全回傳 `None`。
2. **Reuse Equivalence & Wrapper Tests**：證明防禦型 Wrapper 正確將 $H \le L$ 轉為 `None`，且生產函式原生邏輯 100% 保持不變。
3. **Dual VWAP Tests**：證明 5分K Typical VWAP 與即時券商成交均價隔離為獨立特徵。
4. **Execution Clock & Causality Tests**：證明訊號於分內（含 09:30:30、09:30:45）或分界點（09:30:00、09:30:59）皆依 +2s 緩衝順延至合法開盤成交，同一 bar open 絕不回填，無未來 K 棒時記錄 `NO_CAUSAL_EXECUTION`，前向指標與特徵向量嚴格隔離。
5. **Canonical Parameter Provenance & Consistency Tests**：證明 Canonical G19、G20、G21 原始語意保留未受覆蓋，新研究參數註冊於 G22、G23、G24，G05 正確對齊，且 C02 成功移除 `max_extension` Scope Creep。
6. **CanonicalGridValidator Fail-Closed Tests**：未註冊 Grid ID、名稱不符或數值超出範圍時皆嚴格拋出 `ValueError`。
4. **Causal Clock Tests**：證明 `CausalBarSeries.as_of(t)` 絕不洩漏結束時間大於 $t$ 的任何未來或未收盤 K 棒。
5. **Causal Swing Confirmation Tests**：證明波峰在 $k$ 發生時，必須延遲至 $k+c$ 棒完成後才會發出 confirmed pivot，且 `confirmed_time > pivot_time`，防範傳統 ZigZag 事後諸葛問題。
6. **Look-Ahead Regression Proof（核心數學證明）**：
   - 構造情境：給定截至 09:05 的乾淨序列，計算特徵字典 $S_1$。
   - 後續故意加入 09:06-09:20 的嚴重未來噪聲（價格暴跌 70%、成交量放大 1,000,000 倍）。
   - 再次對 09:05 進行 `as_of` 查詢並計算特徵字典 $S_2$。
   - **斷言通過：$S_1 == S_2$ 嚴格相等**！數學上確認未來資料的任何變動對過去特徵產生 0 影響。
7. **Candidate Rule Trigger Tests**：驗證 5 大候選規則在符合與不符合門檻時之精確觸發與原因輸出。
8. **Research Dataset Builder Tests**：驗證前向收益率與 MFE/MAE 僅於離線階段生成，絕對不污染即時 `feature_snapshot`。
9. **既有回歸測試**：執行 `tests/test_market_risk_gate.py`，20/20 測試全數綠燈通過。

---

## 4. 嚴格因果性與 Look-Ahead 防護機制

1. **K 棒收盤契約**：特徵計算嚴格限定使用 `CompletedBar`（$end\_time \le t$）。未完成之盤中即時棒絕不可被視為完整 OHLC。
2. **因果波段確認 (Causal Swing Segmentation)**：
   - 拒絕未來可見之事後高低點（Look-ahead ZigZag）。
   - 實作 $k+c$ 延遲確認機制：波峰必須經由後續 $c$ 根棒的收盤價格皆未過高後方可確認。
3. **前向指標嚴格隔離**：
   - $1m, 3m, 5m, 10m, 30m$ 前向收益率及 MFE/MAE 只能在離線事件分析產出 `ResearchEventRecord` 時計算。
   - `CandidateEvaluationResult.feature_snapshot` 中嚴禁包含任何未來標籤。

---

## 5. 資料能力限制與隔離項目 (Unsupported Features)

本輪嚴格遵守指令，以下功能維持 `UNSUPPORTED` 狀態，**絕無設計假資料或 proxy 冒充**：
- **L2 五檔委託簿**：`F_order_book_imbalance_5`、`F_order_book_imbalance_weighted`、`F_bid_wall_thickness_ratio`、`F_bid_wall_mean_ratio`（因未訂閱 `BidAskSTKv1`，全面禁止回測）。
- **委託撤單流與 100ms 假單**：`F_wall_depletion_velocity`、`F_quote_flip_rate_1m`（台灣交易所與 Shioaji 未提供撤單事件流）。
- **台指期貨與跨市場資料**：`F_tx_traded_lots_spread`、`F_futures_bid_ask_spread_pct_book`、`F_futures_basis_pct`（未訂閱 TXF 期貨合約）。
- **放空與融券機制**：`AQ_R_010` 漲停回跌放空（現有系統僅支援現股多方 Paper Trade，無融券回測機制）。

---

## 6. 後續階段規劃 (Next Steps)

- **Phase 2（待批准）**：
  1. 擴充 `update_market.py` 的 T86 解析器，收集「自營商避險買賣超股數」，以支援 `F_dealer_hedging_share_ratio_eod`。
  2. 構建跨股票類股動能聚合器（Sector Matrix），以支援族群領頭羊回測。
- **本階段交付完畢，遵循停止條件，不進入 Git 提交或 VM 部署，交由人工 Cross Review。**
