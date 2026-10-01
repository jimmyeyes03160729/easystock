# EasyStock Daytrade Knowledge V1 Phase 1 Fix Verification Report

- **驗證日期**：2026-10-02
- **執行角色**：EasyStock 專案資深量化系統工程師
- **驗證性質**：唯讀驗證與合規審計（Read-Only Verification Audit）
- **約束遵守**：未修改任何程式檔案、未新增 Feature/Rule、未調整 threshold、無 git commit/push、無 SSH/VM、未進入 Phase 2。

---

## 1. FIX-1 EXECUTION CLOCK VERIFICATION

### 1.1 時鐘契約程式與測試比對
時鐘契約嚴格比照 `daytrade_learning/research.py:281-282`：
- `signal_time`：訊號計算時點。
- `decision_available_time = signal_time + 2s`：運算與通訊安全緩衝。
- `execution_time = (decision_available_time).replace(second=0, microsecond=0) + timedelta(minutes=1)`：次分鐘第一秒開盤成交。
- `execution_price`：取自 `execution_time` 所屬 K 棒之 Open，加計滑價 bps。

### 1.2 逐例驗證結果
- **案例 A (`signal_time = 09:30:00`)**：
  - `decision_available = 09:30:02`
  - `execution_time = 09:31:00`
  - 判定：**PASS**。合法 execution 為 09:31 開盤價，絕不使用 09:30 open。
  - 代碼位置：`daytrade_learning/knowledge_v1/backtest_dataset.py:compute_causal_execution_time`
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_execution_clock_exact_minute_boundary`、`test_execution_clock_same_bar_open_forbidden`
- **案例 B (`signal_time = 09:30:30`)**：
  - `decision_available = 09:30:32`
  - `execution_time = 09:31:00`
  - 判定：**PASS**。合法 execution 為 09:31 開盤價，絕不使用 09:30 open。
  - 代碼位置：`daytrade_learning/knowledge_v1/backtest_dataset.py:compute_causal_execution_time`
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_execution_clock_inside_minute`（測試以 09:30:45 驗證同理，但在精確 09:30:30 上列為 VERIFY_GAP）。
- **案例 C (`signal_time = 09:30:59`)**：
  - `decision_available = 09:31:01`（已超過 09:31:00 開盤）
  - `execution_time = 09:32:00`
  - 判定：**PASS**。程式正確識別已過 09:31:00，遞延至 09:32:00 開盤。
  - 代碼位置：`daytrade_learning/knowledge_v1/backtest_dataset.py:compute_causal_execution_time`
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_execution_clock_inside_minute` (lines 179-184)
- **案例 D (`signal_time 接近收盤且不存在合法後續 bar`)**：
  - 判定：**PASS**。當無次分鐘 K 棒或成交量非正時，狀態標記為 `NO_CAUSAL_EXECUTION`，`execution_price` 與各期前向報酬一律為 `None`，不捏造價格。
  - 代碼位置：`daytrade_learning/knowledge_v1/backtest_dataset.py:130-153`
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_execution_clock_no_causal_execution_when_next_bar_missing`
- **指標起算點與資料洩漏檢核**：
  - `forward_return_*` (1m, 3m, 5m, 10m, 30m)、`mfe`、`mae` 均嚴格從合法 `execution_time` 與 `execution_price` 開始計算。
  - `ResearchEventRecord.features_vector()` 嚴格只回傳 `feature_snapshot`，絕不包含 `execution_price`, `execution_time`, `forward_return_*`, `mfe`, `mae`, `realized_pnl`。
  - 判定：**PASS**。
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_forward_metrics_calculated_strictly_from_execution_time_and_price`、`test_features_vector_excludes_labels_and_future_data`

**FIX-1 總評**：**PASS**

---

## 2. FIX-2 FEATURE SEMANTICS VERIFICATION

### 2.1 幾何特徵未定義領域防禦
- 重新確認 `F_upper_shadow_ratio`、`F_lower_shadow_ratio`、`F_close_location_value`：
  - 在 $High == Low$（平坦一字線）與 $High < Low$（倒錯異常棒）時，三者均回傳 `None`，絕不以 0.0 或 0.5 假冒為有效幾何值。
  - 代碼位置：`daytrade_learning/knowledge_v1/features.py:80-114`
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_candle_geometry_high_le_low_returns_none`
  - 判定：**PASS**。

### 2.2 生產函式原封不動
- 確認生產函式原生輸出未受修改：
  - `strategy_engine.upper_wick_ratio` 在平坦棒原生回傳 `0.0`。
  - `strategy_engine.bar_position` 在平坦棒原生回傳 `0.5`。
  - Knowledge V1 透過 Research-only wrapper 達成安全防禦，生產核心未變更。
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_production_functions_unmodified`
  - 判定：**PASS**。

### 2.3 雙口徑 VWAP 獨立性檢驗
- `F_dist_to_bar_vwap_pct`（Scope A: BAR_TYPICAL_PRICE_VWAP）：
  - 資料源：`closed_5m_bars`
  - 公式：典型價格典型加權 $[(H+L+C)/3 \times V] / \sum V$
  - 單位：`fraction`
- `F_dist_to_broker_avg_price_pct`（Scope B: BROKER_AVERAGE_PRICE）：
  - 資料源：`live_intraday_snapshot`
  - 公式：交易所官方成交總額 / 總量
  - 單位：`fraction`
- 兩者為獨立 Feature ID，註冊表未互相 alias。
- 測試案例：`tests/test_knowledge_v1_phase1.py:test_vwap_dual_scope_separation`
- 判定：**PASS**。

### 2.4 主動買賣流向防禦
- `KnowledgeV1Features.aggressor_buy_share(buy_volume, sell_volume)`：
  - 分母嚴格定義為：`total = buy_volume + sell_volume`（tick_type 1 與 tick_type 2 之和）。
  - 若 `tick_type 0`（未分類）或總量為 0，分母非正，安全回傳 `None`，不除以零、不補 0.5。
  - 測試案例：`tests/test_knowledge_v1_phase1.py:test_aggressor_flow_zero_volume_returns_none`
  - 判定：**PASS**。

**FIX-2 總評**：**PASS**

---

## 3. PARAMETER PROVENANCE VERIFICATION (關鍵審計發現)

完整掃描 `daytrade_learning/knowledge_v1/rules.py` 中所有影響規則觸發的數值門檻，並與權威標準檔案 `docs/daytrade_knowledge_v1/research_parameter_grids.yaml` 逐一核對：

| 規則 ID | 參數名稱 | 代碼數值 | 代碼綁定 Grid ID | Canonical Grids 實際定義 | 狀態比對 |
|---|---|---|---|---|---|
| C01 | `vwap_touch_band_fraction` | 0.003 | G01 | G01 (`vwap_touch_band_fraction`, [0, 0.001, 0.003, 0.005]) | **MATCH** |
| C01 | `vwap_stop_band_fraction` | 0.002 | G02 | G02 (`vwap_stop_band_fraction`, [0, 0.001, 0.002, 0.003]) | **MATCH** |
| C01 | `lower_shadow_support_ratio` | 0.25 | **G19** | G19 是 **`futures_spread_candidate` (0.003, 0.005, 0.006)** | 🚨 **COLLISION / FAIL** |
| C02 | `prior_high_window` | 20 | G04 | G04 (`prior_high_window`, [20, 60, 250]) | **MATCH** |
| C02 | `breakout_proximity_band` | 0.001 | **G20** | G20 是 **`pyramid_profit_trigger` (0.004, 0.008, 0.015)** | 🚨 **COLLISION / FAIL** |
| C02 | `breakout_max_extension` | 0.015 | **G20** | Canonical G20 雖有 0.015，但代表加碼獲利門檻而非突破上限 | 🚨 **MISATTRIBUTED / FAIL** |
| C03 | `pullback_volume_decay` | 0.5 | G17 | G17 (`pullback_volume_decay`, [0.3, 0.5, 0.7]) | **MATCH** |
| C04 | `rvol_threshold` | 1.5 | **G03 (錯植)** | Canonical G05 才是 `rvol_threshold`（G03 實為 `vwap_stop_ticks`） | 🚨 **TYPO / FAIL** |
| C04 | `aggressor_buy_share` | 0.6 | G14 | G14 (`aggressor_sell_share`, [0.5, 0.6, 0.7]) | **PARTIAL** |
| C04 | `breakout_max_extension` | 0.015 | **G20** | 同 C02，無專屬 Canonical Grid | 🚨 **MISATTRIBUTED / FAIL** |
| C05 | `aggressor_sell_share` | 0.6 | G14 | G14 (`aggressor_sell_share`, [0.5, 0.6, 0.7]) | **MATCH** |
| C05 | `drop_from_reference` | 0.005 | G15 | G15 (`drop_from_reference`, [0.005, 0.01, 0.02, 0.03]) | **MATCH** |
| C05 | `upper_shadow_rejection_ratio`| 0.45 | **G21** | G21 是 **`stop_ticks_candidate` (2, 3, 5)** | 🚨 **COLLISION / FAIL** |

### 具體問題回答：
1. **G19 是否真的存在於 `docs/daytrade_knowledge_v1/research_parameter_grids.yaml`？**
   - **否定**。Canonical G19 是「期現價差（futures_spread_candidate）」，根本不是下影線支撐（0.25）。代碼與 `candidate_rules.yaml` 自行定義的 G19 發生了嚴重的 **Grid ID 衝突（Grid ID Collision / Semantic Hijacking）**。
   - 判定：**FAIL**。
2. **G20 是否真的存在？**
   - **否定**。Canonical G20 是「加碼獲利門檻（pyramid_profit_trigger）」，根本不是突破鄰近帶（0.001）。
   - 判定：**FAIL**。
3. **G21 是否真的存在？**
   - **否定**。Canonical G21 是「停損檔數（stop_ticks_candidate）」，根本不是上影線拒絕比例（0.45）。
   - 判定：**FAIL**。
4. **0.015 是否已有自己的合法 Grid ID？**
   - **否定**。0.015 作為「突破延展上限（breakout max extension）」在 Canonical Grids 中**完全沒有合法 provenance 與專屬 Grid ID**。
   - 判定：**FAIL**。

**FIX-3 總評**：**FAIL**

---

## 4. SCOPE CREEP VERIFICATION

- **審查項目**：C02 `max_extension = 0.015`
- **審查事實**：
  - 在原始教材與 `docs/daytrade_knowledge_v1/` 中，Rule C02 的定義為「短均線多頭排列 + 開盤跳空開高 + 突破前高」。
  - 原始 Phase 1 實作只要價格高於突破點即觸發。
  - Phase 1 Fix 為了防止過度追高，額外增加了 `max_extension = 0.015` 限制（超過前高 1.5% 不予觸發），改變了候選規則的交易與過濾語意。
- **結論歸屬**：
  - **B. 本輪新加入的研究邏輯**。
  - 標記：**SCOPE_CREEP**。

---

## 5. TEST VALIDITY VERIFICATION

- **測試數量**：21 個 test methods 由 unittest 完整執行（`Ran 21 tests in 0.001s ... OK`）。
- **測試有效性**：
  - 每個測試均包含具體且嚴格之斷言（`assertEqual`, `assertIsNone`, `assertNotIn`, `assertTrue`, `assertFalse` 等）。
  - 無空測試、無只執行無斷言測試、無 skip、無 expectedFailure、無 mock/patch 掉核心邏輯。
- **特定場景覆蓋檢核**：
  - [x] `09:30:00 boundary`：覆蓋 (`test_execution_clock_exact_minute_boundary`)
  - [ ] `09:30:30 intraminute`：未明確測試 09:30:30（測試使用的是 09:30:45）-> **VERIFY_GAP-1**
  - [x] `09:30:59 crossing-minute`：覆蓋 (`test_execution_clock_inside_minute`)
  - [x] `NO_CAUSAL_EXECUTION`：覆蓋 (`test_execution_clock_no_causal_execution_when_next_bar_missing`)
  - [x] `future mutation`：覆蓋 (`test_future_mutation_does_not_alter_execution_selection`, `test_mathematical_lookahead_regression_proof`)
  - [x] `H == L`：覆蓋 (`test_candle_geometry_high_le_low_returns_none`)
  - [x] `VWAP dual semantics`：覆蓋 (`test_vwap_dual_scope_separation`)
  - [x] `zero classifiable aggressor volume`：覆蓋 (`test_aggressor_flow_zero_volume_returns_none`)
  - [x] `parameter provenance`：覆蓋 (`test_c01_provenance_and_grid_injection` 等)
  - [ ] `unregistered magic number detection`：目前測試僅驗證已知參數，缺乏「與 Canonical Grids 字典自動一致性比對」之防偽測試 -> **VERIFY_GAP-2**

**TEST VALIDITY 總評**：**PASS_WITH_GAPS**

---

## 6. PRODUCTION ISOLATION

- **Git Diff 檢驗**：
  - `git diff HEAD -- strategy_engine.py intraday_live.py position_manager.py market_risk.py daytrade_learning/model_runtime.py`
  - 結果：**完全為空（0 lines changed）**。
- **Runtime Import 檢驗**：
  - 搜尋全專案生產模組，無任何生產代碼 import `daytrade_learning.knowledge_v1`。
  - candidate evaluator 未被任何生產排程或即時推論載入。
- 判定：**PASS**。

---

## 7. 摘要與最終結論

```text
FIX1_CAUSALITY=PASS
FIX2_SEMANTICS=PASS
FIX3_PROVENANCE=FAIL
SCOPE_CREEP=FOUND
TEST_VALIDITY=PASS_WITH_GAPS
PRODUCTION_ISOLATION=PASS

BLOCKERS=2
MAJOR=2
MINOR=1
VERIFY_GAPS=2
```

### 問題清單
- **BLOCKERS (2)**：
  1. `BLOCKER-1` (Grid ID 衝突與偽溯源)：`rules.py` 與 `candidate_rules.yaml` 將 0.25、0.001、0.45 綁定至 G19、G20、G21，但 Canonical `docs/daytrade_knowledge_v1/research_parameter_grids.yaml` 中 G19 為期現價差、G20 為加碼獲利、G21 為停損 ticks。此三項幾何與突破參數在 Canonical 文件中**完全缺失**，構成偽溯源。
  2. `BLOCKER-2` (未登記策略門檻)：C02 / C04 引入之 `max_extension = 0.015` 無合法 Canonical Grid ID 與來源標註，且改變交易過濾語意，屬未登記策略門檻。
- **MAJOR (2)**：
  1. `MAJOR-1` (Grid ID 錯植)：`rules.py` 中 `G05_RVOL_THRESHOLD` 的 `grid_id` 誤植為 `"RESEARCH_GRID_G03"`（G03 實為 `vwap_stop_ticks`，G05 才是 `rvol_threshold`）。
  2. `MAJOR-2` (C04 參數命名語意偏差)：C04 買方量佔比使用 G14，但 Canonical G14 定義為 `aggressor_sell_share`。
- **MINOR (1)**：
  1. `MINOR-1`：`CandidateEvaluationResult.parameter_provenance` 中同時存在縮寫鍵與完整變數鍵（如 `touch_band` 與 `g01_touch_band`）。
- **VERIFY_GAPS (2)**：
  1. `VERIFY_GAP-1`：未顯式測試 `signal_time = 09:30:30` 的邊界用例。
  2. `VERIFY_GAP-2`：測試套件缺少與 Canonical `research_parameter_grids.yaml` 雙向校驗機制。

---

### 最終結論

依據判定規則：
> 「只要存在以下任一情況：... canonical parameter provenance 缺失、未登記策略 threshold ... 一律 NEEDS_FIX。」

**最終判定：`NEEDS_FIX`**
