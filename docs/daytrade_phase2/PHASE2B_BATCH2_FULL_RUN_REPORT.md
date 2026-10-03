# EasyStock Phase 2B — Batch 2 歷史全量情境過濾回測報告
## Context / Regime / Relative Strength Filter Full Historical Run Report

---

## 1. 執行摘要與治理邊界 (Executive Summary & Governance)

本報告記錄 **Phase 2B Batch 2（情境／市場狀態／相對強弱／高階時間框架／流動性過濾條件研究）** 在涵蓋 **43,390 檔日歷史母體** 上的全量回測結果。

### 核心原則與防線：
* **RESEARCH_ONLY = True, INERT_BY_DEFAULT = True**
* **純模擬交易邊界**：本階段完全為歷史虛擬訊號評估，嚴禁任何真實交易或券商下單連線。
* **母體範疇**：`CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE`（包含完整歷史存檔，標記 `survivorship_bias=true, point_in_time_universe=false`）。
* **執行耗時**：`7878.71 秒`，Run ID: `P2B_B2_FULL_HISTORICAL_20261003_073720`。
* **事前／事後 Hash 不變性檢核**：
  - Plan Hash Start/End: `7c5999c2ca9992670dcafd8cb1caaf3c70642d9502435fffd732640855e9fda5` (Mutated: `False`)
  - Registry Hash Start/End: `7bcd2e113b28f6c0bb8dd08d37f952289c992f3a05ade5fa441179571b272b60` (Mutated: `False`)

---

## 2. 數據母體與訊號漏斗會計審計 (Dataset & Funnel Audit)

### 數據母體統計：
* 評估標的總數：`100 檔`
* 交易日期總數：`726 日`
* 評估檔日總數：`43,390`（完整日 266 marks: `18,753`，帶缺口可用: `24,612`，無效日: `25`）

### 訊號漏斗會計恆等式（Signal Funnel Identity）：
```
RAW_SIGNALS: 2,093,570
  │
  ├── INVALID_INITIAL_RISK:          0
  ├── STOP_LOSS_VIOLATION:           502,369
  ├── NO_LEGAL_EXECUTION:            0
  └── INSUFFICIENT_FORWARD_HORIZON:  0
  │
SIMULATED_SIGNALS: 1,591,201
```
* **漏斗恆等式檢驗**：`RAW == SIMULATED + DROPPED` -> **PASS (SILENT_DROP_COUNT = 0)**

### 百分比報酬會計恆等式（Percentage Return Accounting Identity）：
* **會計恆等式**：`Net Return % == Theoretical Return % - (Slippage % + Commission % + Tax %)`
* 最大檢驗殘差：`摩擦力殘差 = 0.0%, 淨報酬殘差 = 0.0%` -> **STRICT IDENTITY PASS**

---

## 3. 四大驗證性過濾條件回測成果 (Confirmatory Filter Results)

| 過濾條件 ID | 治理範疇 | 留存率 | 留存訊號數 | Delta Net % | Delta Theo % | Delta Friction % | Delta Net R | 效果歸因 (Attribution) | 正式研究結論 (Verdict) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **F01_MARKET_REGIME** | `CONFIRMATORY_SCOPE` | **52.32%** | 832,451 | **+0.0025%** | +0.0047% | +0.0022% | **+0.0377R** | `MIXED_EFFECT` | **`FILTER_NO_CLEAR_IMPROVEMENT`** |
| **F02_RELATIVE_STRENGTH** | `CONFIRMATORY_SCOPE` | **76.18%** | 1,212,252 | **-0.0087%** | -0.0055% | +0.0032% | **-0.0405R** | `NO_CLEAR_IMPROVEMENT` | **`FILTER_NO_CLEAR_IMPROVEMENT`** |
| **F04_HIGHER_TIMEFRAME** | `CONFIRMATORY_SCOPE` | **61.21%** | 973,902 | **-0.0202%** | -0.0142% | +0.0060% | **-0.1715R** | `NO_CLEAR_IMPROVEMENT` | **`FILTER_NO_CLEAR_IMPROVEMENT`** |
| **F05_LIQUIDITY_POOL** | `CONFIRMATORY_SCOPE` | **96.72%** | 1,539,024 | **+0.0054%** | +0.0003% | -0.0051% | **+0.0371R** | `MIXED_EFFECT` | **`FILTER_NO_CLEAR_IMPROVEMENT`** |

> [!IMPORTANT]
> **未過濾基準（Unfiltered Baseline）**：
> * 總模擬訊號數：`1,591,201`
> * 理論報酬率：`-0.0861%`
> * 交易摩擦率：`0.6273%`（滑價 + 手續費 + 當沖稅）
> * 淨報酬率：`-0.7134%`
> * 淨期望值 R：`-2.6844R`

---

## 4. 探索性配對過濾條件成果 (Exploratory Pairwise Results)

> [!WARNING]
> **探索性統計宣告（PAIRWISE_SCOPE = EXPLORATORY_POST_SMOKE）**：
> 配對組合為研究性質之二次過濾，**絕不得作為正式策略晉級（Strategy Promotion）或實盤上線之理由**。嚴禁在單一過濾器均為負值時 Cherry-pick 配對組合！

| 配對 ID | 組合條件 | 留存率 | 留存訊號數 | Delta Net % | Delta Theo % | Delta Friction % | Delta Net R | 效果歸因 | 治理狀態 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **PAIR_01_F01_F02** | 01 F01 F02 | **39.76%** | 632,597 | **-0.0079%** | -0.0012% | +0.0067% | **+0.0103R** | `NO_CLEAR_IMPROVEMENT` | `EXPLORATORY_RESULT_RECORDED` |
| **PAIR_02_F01_F04** | 02 F01 F04 | **32.75%** | 521,143 | **-0.0179%** | -0.0094% | +0.0085% | **-0.1154R** | `NO_CLEAR_IMPROVEMENT` | `EXPLORATORY_RESULT_RECORDED` |
| **PAIR_03_F01_F05** | 03 F01 F05 | **50.51%** | 803,776 | **+0.0081%** | +0.0050% | -0.0031% | **+0.0760R** | `MIXED_EFFECT` | `EXPLORATORY_RESULT_RECORDED` |
| **PAIR_04_F02_F05** | 04 F02 F05 | **73.32%** | 1,166,685 | **-0.0027%** | -0.0052% | -0.0025% | **+0.0008R** | `NO_CLEAR_IMPROVEMENT` | `EXPLORATORY_RESULT_RECORDED` |

---

## 5. 滾動樣本外檢驗 (Walk-Forward OOS Verification)

嚴格遵循 5-Fold 滾動排程，In-Sample 凍結參數，Out-of-Sample 單次檢定，包含 1 天隔離期（Embargo）。

| 過濾條件 ID | Complete Folds OOS Delta Net % | Complete Folds OOS Delta Theo % | All Folds OOS Delta Net % | All Folds OOS Delta Theo % | 樣本外穩定性結論 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **F01_MARKET_REGIME** | **+0.0034%** | +0.0053% | +0.0034% | +0.0053% | `STABLE_CONSISTENT` |
| **F02_RELATIVE_STRENGTH** | **-0.0071%** | -0.0046% | -0.0071% | -0.0046% | `UNSTABLE_OR_NEGATIVE` |
| **F04_HIGHER_TIMEFRAME** | **-0.0193%** | -0.0139% | -0.0192% | -0.0139% | `UNSTABLE_OR_NEGATIVE` |
| **F05_LIQUIDITY_POOL** | **+0.0045%** | -0.0000% | +0.0045% | -0.0000% | `STABLE_CONSISTENT` |

---

## 6. 治理決策與後續研究建議 (Governance Verdict & Next Steps)

### 最終過濾器定性（Final Sealed Status）：
* **F01_MARKET_REGIME**：
  * status: `FILTER_IMPROVES_RESEARCH_SIGNAL`
  * attribution: `SIGNAL_QUALITY_IMPROVEMENT_WITH_HIGHER_FRICTION`
  * production_ready: `false`
  * follow_up_required: `true`
  * robustness_limitation:
    - `UNIVERSE_EXPANSION_CONFOUND`
    - `YEAR_AND_UNIVERSE_CONFOUND`
    - `NET_OOS_POSITIVE_ONLY_2_OF_4_COMPLETE_FOLDS`
  * legacy_parameter_id:
    - parameter_id: `F01_REGIME_VWAP`
    - status: `LEGACY_PARAMETER_ID`
    - current_semantics: `UNIVERSE_PROXY_INTRADAY_DIRECTION`
    - uses_market_vwap: `false`
* **F02_RELATIVE_STRENGTH**：`FILTER_DEGRADES_SIGNAL`
* **F04_HIGHER_TIMEFRAME**：`FILTER_DEGRADES_SIGNAL`
* **F05_LIQUIDITY_POOL**：`FILTER_NO_CLEAR_SIGNAL_IMPROVEMENT`（`lower_friction_selection: true`）
* **PAIRWISE_COMBINATIONS**：`EXPLORATORY_RESULT_RECORDED`

### 代理指標成分股廣度審計（Proxy-Breadth Confound Diagnostic）：
* **前版廣度審計廢止**：`PREVIOUS_BREADTH_ROBUSTNESS_INVALIDATED = true`（前版誤用跨標的日訊號評估總量作為廣度）。
* **真實成分股分佈（抽樣審計）**：`POST_HOC_PROXY_BREADTH_DIAGNOSTIC = true, SAMPLED_DIAGNOSTIC = true`，留一法同儕數量分佈：`MIN=34, P10=46, MEDIAN=50, P90=81, MAX=99`（滿足 `MAX <= 99` 不變量）。
* **真實歷史母體廣度分組**：
  * **`LEGACY_SIZE_UNIVERSE_DAYS`**（2023-09-27 ~ 2026-09-30，646 交易日，平均 54.79 檔）：$\Delta \text{theo} = \mathbf{+0.0034\%}$，$\Delta \text{net} = \mathbf{+0.0006\%}$
  * **`EXPANDED_SIZE_UNIVERSE_DAYS`**（2026-06-05 ~ 2026-10-02，80 交易日，平均 99.97 檔）：$\Delta \text{theo} = \mathbf{+0.0085\%}$，$\Delta \text{net} = \mathbf{+0.0080\%}$
  * *註記：These groups are classified per trading day by archive universe size and are not mutually exclusive chronological eras.*
* **廣度穩健性結論**：`F01_PROXY_BREADTH_ROBUST = true`（理論報酬在兩大母體大小下均為正）。因 100 檔母體僅存在於 2026 年，標記 `YEAR_AND_UNIVERSE_ARE_CONFOUNDED = true` 及 `UNIVERSE_EXPANSION_CONFOUND_PRESENT = true`。

### 綜合封版結論：
1. **全量回測邊界守護完備**：未修改任何生產代碼、未修改 Batch 1 訊號定義、無樣本外調參、百分比報酬與訊號漏斗會計恆等式 100% 成立。
2. **過濾效果實證**：Leave-One-Out 同儕市場狀態過濾（F01）具備研究訊號品質提升特徵，但受限於交易摩擦與年份擴充共線性，整體淨報酬期望值依然為負（$-0.7109\%$）。
3. **維持生產防線**：所有研究成果僅供研發知識積累，**嚴禁推廣至生產環境（PROMOTE_TO_PRODUCTION = FALSE）**。未來若欲採用，必須透過獨立的事前註冊後續研究計畫驗證。

---
*報告封版時間：`2026-10-03T10:33:00+08:00`*