# EasyStock Daytrade Knowledge V1 Phase 1 修復報告 (Phase 1 Fix Report)

- **執行日期**：2026-10-02
- **執行角色**：EasyStock 專案資深量化系統工程師
- **修復依據**：`phase1_cross_review.md` 審查之 3 項 MAJOR 缺陷
- **生產安全承諾**：
  - `PRODUCTION_FILES_CHANGED = false`（生產核心檔案零變更）
  - 無修改 `strategy_engine.py`、`position_manager.py`、`market_risk.py` 或正式 model runtime。
  - 無啟用實單、無 SSH VM、無 git commit/push、無建立 subagent、無平行委派、未進入 Phase 2。

---

## 1. 缺陷修復細節 (Fix Implementation Details)

### FIX-1：Backtest Causality & Delayed Execution Clock
- **FIX_ID**：`FIX-1`
- **original_problem**：
  原 `backtest_dataset.py` 在訊號發生當下，可能直接使用同一 bar 的 open 作為模擬成交價，造成嚴重的 optimistic execution bias（將未來開盤即時成交視為已知）。同時缺少明確的時間劃分契約，且前向指標計算未對齊合法撮合時間。
- **files_changed**：
  - `daytrade_learning/knowledge_v1/backtest_dataset.py`
- **symbols_changed**：
  - `compute_causal_execution_time`
  - `ResearchDatasetBuilder.calculate_transaction_cost`
  - `ResearchDatasetBuilder.build_record`
  - `ResearchEventRecord.features_vector`
- **old_behavior**：
  訊號時間與成交時間未分開；以傳入 K 棒序列的第一根 open 成交，可能同 bar 回填成交價；特徵向量與前向標籤未嚴格隔離。
- **new_behavior**：
  1. 嚴格沿用 `daytrade_learning/research.py:281-282` 現行工程契約：
     - `signal_time`：訊號計算時點。
     - `decision_available_time = signal_time + 2s`：防範網路傳輸與運算延遲之安全緩衝。
     - `execution_time = (decision_available_time).replace(second=0, microsecond=0) + 1m`：次分鐘第一秒開盤成交。
  2. 成交價取自 `execution_time` 所屬 K 棒之 Open，加上設定之滑價 bps（預設 5 bps）。同一 bar 的 open 絕對不可回填成交。
  3. 若找不到在 `execution_time` 開盤之有效 K 棒，或成交量非正，狀態標記為 `NO_CAUSAL_EXECUTION`，成交價與前向報酬填為 `None`，絕不捏造或外推價格。
  4. Forward returns（1m, 3m, 5m, 10m, 30m）、MFE、MAE 嚴格從 `execution_time` 與 `execution_price` 起算。
  5. `ResearchEventRecord.features_vector()` 嚴格只回傳 `signal_time` 當下快照特徵，完全隔離所有前向標籤與成交後資訊。
- **tests_added**：
  - `test_execution_clock_exact_minute_boundary`：整分鐘邊界（09:30:00）延遲到次分鐘（09:31:00）開盤。
  - `test_execution_clock_inside_minute`：分內時點（09:30:45）延遲到次分鐘（09:31:00）開盤。
  - `test_execution_clock_same_bar_open_forbidden`：驗證 09:30:00 訊號絕不能以 09:30:00 Open 成交。
  - `test_execution_clock_no_causal_execution_when_next_bar_missing`：無次分鐘 K 棒時標記 `NO_CAUSAL_EXECUTION`。
  - `test_forward_metrics_calculated_strictly_from_execution_time_and_price`：回傳與最大潛在獲利/虧損嚴格基於合法成交點。
  - `test_features_vector_excludes_labels_and_future_data`：特徵向量不含任何前向資訊。
  - `test_future_mutation_does_not_alter_execution_selection`：成交後數據突變不影響成交時點與價格選擇。
- **provenance**：
  契約與參數完全取自既有代碼庫 `daytrade_learning/research.py:281-282`。
- **remaining_risk**：
  若歷史資料在特定分鐘發生斷漏，將觸發 `NO_CAUSAL_EXECUTION` 丟棄事件，離線回測需使用具連續完整性的分鐘歷史源。

---

### FIX-2：Reuse Equivalence & Feature Semantics
- **FIX_ID**：`FIX-2`
- **original_problem**：
  1. 幾何特徵在 $High \le Low$（如單一價平坦 K 棒）時，受限於生產函式回傳 0.0 或 0.5，未能正確表達幾何未定義；
  2. 模糊了「5分鐘 K 棒典型價格 VWAP」與「券商/交易所即時成交均價」兩種不同口徑，合併為單一特徵有失嚴謹；
  3. 積極成交量在買賣量皆為 0 時未妥善回傳 `None`。
- **files_changed**：
  - `daytrade_learning/knowledge_v1/features.py`
  - `daytrade_learning/knowledge_v1/registry.py`
  - `reused_features.yaml`
- **symbols_changed**：
  - `KnowledgeV1Features.upper_shadow_ratio`（防禦型 Wrapper）
  - `KnowledgeV1Features.lower_shadow_ratio`
  - `KnowledgeV1Features.close_location_value`（防禦型 Wrapper）
  - `KnowledgeV1Features.dist_to_bar_vwap_pct`（Scope A 特徵）
  - `KnowledgeV1Features.dist_to_broker_avg_price_pct`（Scope B 特徵）
  - `KnowledgeV1Features.calculate_bar_typical_vwap`（別名）
  - `KnowledgeV1Features.aggressor_buy_share`
  - `RegistryStatus.PARTIAL_REUSE`
- **old_behavior**：
  原先標記為 `EXISTING_REUSED`（IDENTICAL），但 $High \le Low$ 時生產端回傳 0.0/0.5，研究端未加防禦；VWAP 未嚴格區分口徑；成交量為 0 時可能產生未定義數值。
- **new_behavior**：
  1. 將複用特徵自 `IDENTICAL` 降階重分類為 `PARTIAL_REUSE`。
  2. 建立 Research-only defensive wrappers：在呼叫生產函式前攔截 $High \le Low$ 或非正價格，嚴格回傳 `None`。**生產端 `strategy_engine.py` 之 `upper_wick_ratio` 與 `bar_position` 行為維持 100% 不變**。
  3. 嚴格拆分 VWAP 為兩種獨立口徑特徵：
     - `F_dist_to_bar_vwap_pct`（Scope A: BAR_TYPICAL_PRICE_VWAP，基於 5 分鐘 K 棒 typical price 與成交量）。
     - `F_dist_to_broker_avg_price_pct`（Scope B: BROKER_AVERAGE_PRICE，基於即時累積成交總金額/總量）。
  4. `aggressor_buy_share`、`aggressor_sell_share`、`aggressor_volume_delta` 在可分類成交量為 0 時一律回傳 `None`。
- **tests_added**：
  - `test_candle_geometry_high_le_low_returns_none`：驗證平坦 K 棒回傳 None。
  - `test_production_functions_unmodified`：驗證生產函式原生輸出不受干擾，而 wrapper 正確回傳 None。
  - `test_vwap_dual_scope_separation`：驗證兩口徑計算獨立且數值隔離。
  - `test_aggressor_flow_zero_volume_returns_none`：驗證零成交量時安全回傳 None。
- **provenance**：
  幾何特徵未定義領域回傳 None 遵循標準量化契約；兩口徑 VWAP 分別精確對應 `strategy_engine.py:calculate_vwap` 與 `intraday_live.py:price_vs_avg_pct`。
- **remaining_risk**：
  下游模型在處理 K 棒特徵時須具備非空斷言或填補策略（已在研究註冊表明確標示 `missing_data_policy`）。

---

### FIX-3：Parameter Provenance Audit & Grid Injection
- **FIX_ID**：`FIX-3`
- **original_problem**：
  5 大候選規則內嵌未具名之浮點門檻值（Magic numbers），如 0.25 下影線支撐、0.001 突破鄰近帶、0.45 上影線壓力等；規則 C02 缺乏突破窗口上限，易產生過度追高之無效觸發；評估結果缺乏結構化參數溯源鏈。
- **files_changed**：
  - `daytrade_learning/knowledge_v1/rules.py`
  - `candidate_rules.yaml`
- **symbols_changed**：
  - `GridParameter`
  - `KnowledgeV1Parameters`
  - `CandidateEvaluationResult.parameter_provenance`
  - `KnowledgeV1RuleEvaluator.evaluate_c01_vwap_pullback_support`
  - `KnowledgeV1RuleEvaluator.evaluate_c02_daily_trend_and_open_breakout`
  - `KnowledgeV1RuleEvaluator.evaluate_c03_pullback_volume_decay`
  - `KnowledgeV1RuleEvaluator.evaluate_c04_breakout_with_rvol`
  - `KnowledgeV1RuleEvaluator.evaluate_c05_failed_rebound_reversal`
- **old_behavior**：
  部分門檻寫死於代碼；C02 只要價在均線之上與前高之上即永久觸發，可能在開盤大幅過期後誤判；`parameter_provenance` 僅為簡易格式化字串。
- **new_behavior**：
  1. 全面消除 Magic Numbers：將所有規則門檻抽換為 `GridParameter`，統一註冊於 `KnowledgeV1Parameters`。
  2. 補足並註冊未具名參數至研究網格：
     - `RESEARCH_GRID_G19`：`lower_shadow_support_ratio` (種子值 0.25，網格 [0.20, 0.25, 0.30])。
     - `RESEARCH_GRID_G20`：`breakout_proximity_band` (種子值 0.001，網格 [0.0, 0.001, 0.002]) 與 `breakout_max_extension` (種子值 0.015，網格 [0.010, 0.015, 0.020])。
     - `RESEARCH_GRID_G21`：`upper_shadow_rejection_ratio` (種子值 0.45，網格 [0.40, 0.45, 0.50])。
  3. C02 增加 `max_extension` (0.015) 邊界檢核：價格若超過前高 1.5% 視為過度延展，嚴禁追高觸發。
  4. 評估結果回傳結構化 `parameter_provenance` 字典，每筆包含 `value`、`grid_id`、`parameter_name`、`source_claim_id`、`ai_quantized_id` 與 `status`。
  5. 顯式標明所有數值之 `AI_QUANTIZED` 標記，絕不混淆作者原始教材與工程量化參數。
- **tests_added**：
  - `test_c01_provenance_and_grid_injection`：驗證 G01/G19 注入與溯源字典完整性。
  - `test_c02_provenance_and_breakout_range_bounds`：驗證 G20 突破區間與逾限防追高（+3.3% 突破不觸發）。
  - `test_c03_c04_c05_provenance`：驗證 G03, G14, G15, G17, G21 之溯源標籤與 AI_QUANTIZED 標註。
  - `test_candidate_evaluation_result_provenance_integrity`：驗證所有規則評估結果皆具備非空結構化溯源。
- **provenance**：
  - G01/G02: `docs/daytrade_knowledge_v1/research_parameter_grids.yaml:12,26`, `AQ_R_003`
  - G04: `research_parameter_grids.yaml:53`, `AQ_R_001, AQ_R_002`, `SV001, SV002`
  - G05: `research_parameter_grids.yaml:67`, `AQ_R_001`, `SV001`
  - G14: `research_parameter_grids.yaml:186`, `H01`
  - G15: `research_parameter_grids.yaml:200`, `AQ_R_010`
  - G17: `research_parameter_grids.yaml:226`, `AQ_R_008`, `SV004`
  - G19: 新註冊研究網格（0.25 下影線支撐），`AQ_R_003`
  - G20: 新註冊研究網格（0.001 突破鄰近帶，0.015 突破最大容許延展帶），`AQ_R_001`
  - G21: 新註冊研究網格（0.45 上影線反轉壓力），`AQ_R_008`, `SV005`
- **remaining_risk**：
  `AI_QUANTIZED` 僅代表合理的研究探索起點，並非經驗證之生產邊際門檻，進入 Phase 2 時必須進行超參數網格回測。

---

## 2. 本輪檔案異動清單

### 2.1 修改之研究檔案（位於 daytrade_learning/knowledge_v1/）
1. `daytrade_learning/knowledge_v1/backtest_dataset.py`：落實延遲執行時鐘與標籤隔離（FIX-1）。
2. `daytrade_learning/knowledge_v1/features.py`：落實防禦型 Wrapper 與雙口徑 VWAP（FIX-2）。
3. `daytrade_learning/knowledge_v1/registry.py`：狀態更新為 `PARTIAL_REUSE`，登記雙口徑 VWAP（FIX-2）。
4. `daytrade_learning/knowledge_v1/rules.py`：全面抽換為 `GridParameter` 實體與結構化溯源（FIX-3）。

### 2.2 修改之測試檔案
5. `tests/test_knowledge_v1_phase1.py`：大幅擴充為 21 個單元測試，全面覆蓋 FIX-1、FIX-2、FIX-3。

### 2.3 更新與新增之規範報告文件
6. `reused_features.yaml`：更新為 `PARTIAL_REUSE`，詳列防禦語意差異（FIX-2）。
7. `candidate_rules.yaml`：更新 G19、G20、G21 網格與結構化溯源資訊（FIX-3）。
8. `phase1_fix_report.md`：本修復報告。

### 2.4 生產環境防護確認
- **生產核心檔案修改數：0**
- `PRODUCTION_FILES_CHANGED = false`

---

## 3. 測試執行結果 (Test Execution Verification)

### 3.1 Phase 1 專案測試 (Knowledge V1 Phase 1 Suite)
- **執行命令**：`python -m unittest tests/test_knowledge_v1_phase1.py`
- **測試總數**：21
- **測試結果**：全部 PASS (OK)
- **測試分組**：
  - `TestKnowledgeV1FeatureSemantics`：6 個（幾何、雙口徑 VWAP、流向防禦）
  - `TestKnowledgeV1CausalityAndClock`：10 個（因果時鐘、延遲執行、無偷看未來數學證明）
  - `TestKnowledgeV1ParameterProvenance`：4 個（網格注入、溯源鏈、突破上限防追高）
  - `TestKnowledgeV1RegistryAndBoundaries`：1 個（註冊表狀態與禁止項目邊界隔離）

### 3.2 既有測試 (Existing Core Test Suites)
- **執行命令**：
  `python -m unittest tests/test_ai_history_audit.py tests/test_fugle_pipeline.py tests/test_market_calendar.py tests/test_market_risk_gate.py tests/test_model_runtime_governance.py tests/test_paper_legacy.py tests/test_parsers.py tests/test_premarket_entry.py tests/test_provider_health.py tests/test_range_rebound.py tests/test_rebound_learning_audit.py tests/test_rebound_learning_backfill.py tests/test_rebound_learning_features.py tests/test_rebound_learning_labels.py tests/test_research_episodes.py tests/test_research_replay.py tests/test_research_schedule.py tests/test_selection.py tests/test_verify_intraday_runtime.py`
- **測試總數**：72
- **測試結果**：全部 PASS (OK, 0 回歸, 0 破壞)

---

## 4. 統計指標與狀態

```text
PHASE1_TESTS=21
EXISTING_TESTS=72
CAUSALITY_TESTS=10
PROVENANCE_TESTS=4
PRODUCTION_FILES_CHANGED=false
FINAL_STATUS=READY_FOR_REVIEW
```

> [!NOTE]
> 本報告後續經 `phase1_fix_verification.md` 審計指出 G19-G21 語意衝突與 C02 Scope Creep，已於最新報告 [`phase1_provenance_final_fix_report.md`](file:///c:/Users/Jimmy/Projects/easystock/phase1_provenance_final_fix_report.md) 中完整修復並通過 29 項單元與 Canonical Grid 驗證測試。
