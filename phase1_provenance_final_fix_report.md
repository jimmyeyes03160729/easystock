# EasyStock Daytrade Knowledge V1 Phase 1 參數溯源最終修復報告 (Provenance Final Fix Report)

- **修復日期**：2026-10-02
- **執行角色**：EasyStock 專案資深量化系統工程師
- **修復依據**：`phase1_fix_verification.md` 之 2 個 BLOCKERS 與 2 個 MAJORS 審計結論
- **核心合規宣告**：
  - `PRODUCTION_FILES_CHANGED = false`（生產核心檔案零變更）
  - 無修改 `strategy_engine.py`、`intraday_live.py`、`position_manager.py`、`market_risk.py` 或正式 model runtime。
  - 嚴格保留 Canonical G19、G20、G21 原生定義，徹底解除 Semantic Hijacking。
  - C02 徹底移除 `max_extension = 0.015`（消除 Scope Creep），恢復 Phase 1 原始 candidate specification。
  - 修復 `G05_RVOL_THRESHOLD` 指向 canonical `G05`。
  - 建立 fail-closed 之 `CanonicalGridValidator`，防範未來未註冊參數或語意衝突。

---

## 1. 參數網格溯源修正對照表 (Parameter Provenance Migration Matrix)

| 參數名稱 (PARAMETER_NAME) | 數值 (VALUE) | 原錯植 ID (GRID_ID_BEFORE) | 修正後 Canonical ID (GRID_ID_AFTER) | 權威比對 (CANONICAL_MATCH) | 來源狀態 (SOURCE_STATUS) | 來源依據 (SOURCE_IDS) | 備註說明 |
|---|---|---|---|---|---|---|---|
| `futures_spread_candidate` | 0.005 | G19 | **G19** | **MATCH** | AI_QUANTIZED | SV016, AQ_R_004 | **保留 Canonical 原始語意**（期現價差，期貨） |
| `pyramid_profit_trigger` | 0.008 | G20 | **G20** | **MATCH** | AI_QUANTIZED | AQ_R_011 | **保留 Canonical 原始語意**（加碼獲利門檻） |
| `stop_ticks_candidate` | 3.0 | G21 | **G21** | **MATCH** | AI_QUANTIZED | AQ_R_007, AQ_R_008 | **保留 Canonical 原始語意**（停損檔數） |
| `lower_shadow_support_ratio` | 0.25 | G19 (衝突) | **G22** | **MATCH** | AI_QUANTIZED | SV004, AQ_R_003 | **新註冊 Canonical Grid**（解除 G19 占用） |
| `breakout_proximity_band` | 0.001 | G20 (衝突) | **G23** | **MATCH** | AI_QUANTIZED | SV001, AQ_R_001 | **新註冊 Canonical Grid**（解除 G20 占用） |
| `upper_shadow_rejection_ratio`| 0.45 | G21 (衝突) | **G24** | **MATCH** | AI_QUANTIZED | SV005, AQ_R_008 | **新註冊 Canonical Grid**（解除 G21 占用） |
| `rvol_threshold` | 1.5 | G03 (錯植) | **G05** | **MATCH** | AI_QUANTIZED | SV001, AQ_R_001 | **修復 Grid 錯植**（G03 為 stop ticks） |
| `vwap_touch_band_fraction` | 0.003 | G01 | **G01** | **MATCH** | AI_QUANTIZED | AQ_R_003 | 保持對齊 |
| `vwap_stop_band_fraction` | 0.002 | G02 | **G02** | **MATCH** | AI_QUANTIZED | AQ_R_003 | 保持對齊 |
| `prior_high_window` | 20.0 | G04 | **G04** | **MATCH** | AI_QUANTIZED | SV001, AQ_R_001 | 保持對齊 |
| `aggressor_sell_share` | 0.6 | G14 | **G14** | **MATCH** | AI_QUANTIZED | H01 | 保持對齊 |
| `drop_from_reference` | 0.005 | G15 | **G15** | **MATCH** | AI_QUANTIZED | AQ_R_010 | 保持對齊 |
| `pullback_volume_decay` | 0.5 | G17 | **G17** | **MATCH** | AI_QUANTIZED | SV004, AQ_R_008 | 保持對齊 |

---

## 2. 核心問題修復細節

### 2.1 解除 G19 / G20 / G21 Semantic Hijacking
- **問題**：先前修復將未具名的 0.25、0.001、0.45 便宜行事套用 G19、G20、G21，但 Canonical `research_parameter_grids.yaml` 中 G19 實為期現價差、G20 為加碼獲利門檻、G21 為停損 ticks。
- **修復**：
  1. 完整保留 Canonical G19, G20, G21 原生定義不變。
  2. 盤點 Canonical 最大 ID（現為 G21），向下依序配置全新 ID：
     - `G22`：`lower_shadow_support_ratio` (0.25, values: [0.20, 0.25, 0.30])
     - `G23`：`breakout_proximity_band` (0.001, values: [0.0, 0.001, 0.002])
     - `G24`：`upper_shadow_rejection_ratio` (0.45, values: [0.40, 0.45, 0.50])
  3. 正式追加寫入 `docs/daytrade_knowledge_v1/research_parameter_grids.yaml`，並在 `candidate_rules.yaml` 與 `rules.py` 中更新指向。

### 2.2 徹底移除 C02 Scope Creep (`max_extension = 0.015`)
- **問題**：前一輪為防止追高而自行新增 `max_extension = 0.015` 限制，該門檻無 Canonical Grid ID，且改變了 Candidate Rule 原始交易語意。
- **修復**：
  - 在 `rules.py` 中將 `evaluate_c02_daily_trend_and_open_breakout` 之 `max_extension` 判斷全面移除。
  - C02 回歸 Phase 1 原始 candidate specification：
    $$\text{MA5} > \text{MA10} > \text{MA20} \quad \land \quad \text{gap\_open\_pct} > 0.0 \quad \land \quad \text{dist\_to\_prior\_high\_pct} \le \text{proximity\_band}$$
  - 在 `candidate_rules.yaml`、`KnowledgeV1Parameters` 及測試中同步移除 `max_extension`。
  - 將 0.015 記錄於下文「未來研究候選區（FUTURE_RESEARCH_CANDIDATE）」，不污染正式候選規則。

### 2.3 修復 G05 RVOL Grid ID 錯植
- **問題**：`rules.py` 中 `G05_RVOL_THRESHOLD` 之 `grid_id` 誤植為 `"RESEARCH_GRID_G03"`（G03 實為 `vwap_stop_ticks`）。
- **修復**：
  - 修正為 `grid_id="RESEARCH_GRID_G05"`，與 Canonical G05 (`rvol_threshold`) 100% 精準對齊。

### 2.4 實作 CanonicalGridValidator (Fail-Closed)
- 新增模組 `daytrade_learning/knowledge_v1/validator.py`：
  - 動態載入 `docs/daytrade_knowledge_v1/research_parameter_grids.yaml`。
  - 驗證項目：`grid_id` 是否存在、`parameter_name` 是否精確相符、`value` 是否在 canonical 候選值清單內、`status` 是否一致。
  - 若有任何不符直接拋出 `ValueError`（Fail-Closed），嚴禁自動創造假 ID 或靜默降階。

---

## 3. 未來研究候選區 (FUTURE_RESEARCH_CANDIDATE)

本區塊記錄自正式規則中剝離之非規格研究想法，**不進入正式候選規則或生產代碼**：

- **候選參數**：`breakout_max_extension`
- **提議數值**：0.015 (1.5%)
- **研究假說**：突破前高後若已延伸超過 1.5%，短線追價期望值降低，可能具備逆向過濾效果。
- **後續路徑**：需待 Phase 2 正式建立研究假說 H06 並通過預註冊 Grid 審查後，方可考慮配置全新 Grid ID。

---

## 4. 測試覆蓋與新增驗證

本輪在 `tests/test_knowledge_v1_phase1.py` 中全面擴充測試至 **29 個測試**，新增項目包含：

1. `test_canonical_g19_g20_g21_preserved`：斷言 Canonical G19, G20, G21 原生定義未受覆蓋。
2. `test_new_research_parameters_in_canonical_grids`：斷言 G22, G23, G24 正式存在於 Canonical YAML。
3. `test_g05_mapping_points_to_g05`：斷言 G05 RVOL 正確指向 G05。
4. `test_validator_fail_closed_on_missing_grid_id`：斷言未註冊 Grid ID (G999) 必拋異常。
5. `test_validator_fail_closed_on_parameter_name_mismatch`：斷言名稱不符必拋異常。
6. `test_validator_fail_closed_on_unallowed_value`：斷言非 Canonical 數值必拋異常。
7. `test_all_active_strategy_thresholds_validated_against_canonical`：遍歷所有參數通過 Canonical 檢驗。
8. `test_c02_scope_creep_removed_and_breakout_trigger`：斷言 C02 即使大幅突破（+3.3%）依然觸發，證明 Scope Creep 限制已移除。
9. `test_execution_clock_exact_093030_intraminute`：補足 exact 09:30:30 時鐘測試（次分 09:31:00 成交）。

---

## 5. 測試執行結果 (Test Results)

1. **Phase 1 Knowledge V1 專案測試**：
   - 執行命令：`python -m unittest tests/test_knowledge_v1_phase1.py`
   - 結果：`Ran 29 tests in 0.015s ... OK`
2. **既有核心測試**：
   - 執行命令：`python -m unittest tests/test_ai_history_audit.py tests/test_fugle_pipeline.py tests/test_market_calendar.py tests/test_market_risk_gate.py tests/test_model_runtime_governance.py tests/test_paper_legacy.py tests/test_parsers.py tests/test_premarket_entry.py tests/test_provider_health.py tests/test_range_rebound.py tests/test_rebound_learning_audit.py tests/test_rebound_learning_backfill.py tests/test_rebound_learning_features.py tests/test_rebound_learning_labels.py tests/test_research_episodes.py tests/test_research_replay.py tests/test_research_schedule.py tests/test_selection.py tests/test_verify_intraday_runtime.py`
   - 結果：`Ran 72 tests in 2.266s ... OK`（既有測試 0 破壞、0 回歸）
3. **生產隔離性確認**：
   - `git diff HEAD -- strategy_engine.py intraday_live.py position_manager.py market_risk.py daytrade_learning/model_runtime.py` 為空。
   - `PRODUCTION_FILES_CHANGED = false`。

---

## 6. 標準化摘要指標

```text
PHASE1_TESTS=29
EXISTING_TESTS=72
CANONICAL_GRID_TESTS=7
CAUSALITY_TESTS=11
PROVENANCE_TESTS=4

G19_PRESERVED=true
G20_PRESERVED=true
G21_PRESERVED=true
G05_MAPPING_FIXED=true
C02_SCOPE_CREEP_REMOVED=true
PRODUCTION_FILES_CHANGED=false

FINAL_STATUS=READY_FOR_FINAL_VERIFICATION
```
