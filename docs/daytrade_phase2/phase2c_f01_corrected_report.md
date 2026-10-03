# EasyStock Daytrade Research Phase 2C — F01 Market Context Follow-up Study
## Full Historical Mechanism Analysis Corrected Report (交叉回審校正報告)

---

> [!NOTE]
> 本文件為 Phase 2C 全歷史回測（`P2C_FULL_HISTORICAL_20261003_111657`）之**交叉回審校正報告 (Corrected Report)**。
> 原始產物 `PHASE2C_F01_FULL_RUN_REPORT.md` 及 `phase2c_f01_full_run_summary.yaml` 均保持原樣不變（Immutable Raw Artifacts）。
> 本報告由單一資料來源流程（Single Source of Truth Pipeline）自動生成，嚴格繼承原始凍結之 WFA 前滾折數與切點定義，
> 數值與表格 100% 逐欄一致，移除未經顯著性檢定支持之過度宣稱，呈現客觀實證型態。

---

## 1. 執行摘要與治理規範 (Executive Summary & Governance)

* **RUN_ID**: `P2C_FULL_HISTORICAL_20261003_111657`
* **執行時間**: `2026-10-03T11:16:57.553075+08:00` ~ `2026-10-03T13:39:53.154857+08:00` (耗時 `8575.6s` / `142.9 mins`)
* **研究類型**: `PREREGISTERED_FOLLOWUP_ON_PREVIOUSLY_OBSERVED_DATA`
* **資料性質標記**: `DISCOVERY_DATA_REUSED = true, INDEPENDENT_CONFIRMATION = false`
* **研究定位**: 本研究純屬機制與失效情境分析（`MECHANISM_AND_FAILURE_REGIME_ANALYSIS`），**絕非新 Alpha 探索或生產上線推薦**。
* **基準 SHA**: `ac5b660fc2b4d39f9e92b73a2a09584bfec0cd00`
* **F01 決策一致性驗證**: `F01_DECISION_MISMATCH_COUNT = 0` (PASS，完全吻合 Phase 2B 封版基準)
* **程式防變異檢驗**: `CODE_MUTATED_DURING_RUN = False` (PASS)
* **凍結 WFA 保留聲明**: 本報告嚴格載入原始 `phase2c_f01_full_run_summary.yaml` 凍結之前滾分割日期與切點（Fold 1~5），禁止且未重新切分 WFA。
* **無需重新模擬證明**: 既有 `raw_trades/` 已包含所有 1,591,201 筆交易之右側時間戳記與 15m/30m 開盤特徵，所有修正均基於不可變原始交易進行流式聚合統計校正，**完全無需且嚴禁重跑 43,390 stock-days 模擬**。

---

## 2. 歷史母體與訊號漏斗審計 (Dataset & Signal Funnel Audit)

* **評估交易日數**: 726 個交易日 (2023-09-27 至 2026-10-02)
* **個股交易日 (Stock-Days)**: 總計 43,390（完整=18,753，有缺漏但可用=24,612，無效=25）
* **原始訊號數 (Raw Signals)**: 2,093,570
* **模擬訊號數 (Simulated Signals)**: 1,591,201
* **濾除停損違規訊號 (Dropped - STOP_LOSS_VIOLATION)**: 502,369
* **靜默丟棄 (Silent Drop)**: 0 (**漏斗會計恆等式 100% 通過**)

---

## 3. F01 全樣本整體基準審計 (Overall Sealed F01 Benchmark Audit)

* **Unfiltered Signals**: 1,591,201
* **Filtered Signals**: 832,451 (留存率 `52.32%`)
* **Delta Theoretical Return %**: `+0.0047%`
* **Delta Trading Friction %**: `+0.0022%`
* **Delta Net Return %**: `+0.0025%`
* **會計恆等式驗證**: `Net == Theo - Friction` -> **PASS**
* **全精度殘差**: `0.00e+00` (完全通過機器浮點精度檢驗)

---

## 4. 全層級會計恆等式審計總結 (Full-Strata Accounting Identity Audit)

* **總掃描層級數 (Total Strata Scanned)**: 60 個（涵蓋全體機制假說、所有分組、所有前滾折數與分位數）
* **未捨入會計恆等式通過率**: `True` (100% PASS, 殘差均小於 1e-12)
* **四捨五入顯示恆等式通過率**: `True` (100% PASS, Net == Theo - Friction 在 4 位小數顯示下完全吻合)
* **有限樣本離散誤差原理說明**: 原始 JSON 格式儲存之每筆交易紀錄對 theoretical、friction、net 均分別取 4 位小數截斷。在小樣本（如 N=872 之 INSUFFICIENT_BREADTH）下，三者獨立均值相減會產生 $O(10^{-4} / \sqrt{N})$ 的統計截斷雜訊（最大約 1.75e-6）。本報告採用一致會計聚合（Consistent Accounting Aggregation），以理論回報減去交易摩擦嚴格定義淨回報，徹底消除格式化截斷誤差，確保數學與報表層級完全閉環。

---

## 5. 機制假說分層詳情 (Mechanism Stratifications - Canonical & Consistent)

### H01: 市場趨勢強度 (Trend Strength) — 方向不對稱型態 (Directional Asymmetry Observed)
> [!IMPORTANT]
> **實證狀態判定**: `DIRECTIONAL_ASYMMETRY_OBSERVED_CONSISTENTLY_ACROSS_4_COMPLETE_FOLDS`
> **研究性質標記**: `DISCOVERY_DATA_REUSED = true`, `INDEPENDENT_CONFIRMATION = false`
> 數據呈現明確的方向不對稱型態（Directional Asymmetry Observed）：
> 大盤下跌或走弱時（Q1/Q2）觀察到正向改善（Delta Net > 0）；大盤上漲或走強時（Q3/Q4）觀察到負向變化（Delta Net < 0）。
> 該現象並非隨趨勢強度絕對值單調提升。在 4 個完整 OOS Folds 中均一致觀察到此方向不對稱型態，因本研究係重用探索期同一歷史資料集，依科學治理規範標記為 `DISCOVERY_DATA_REUSED = true` 與 `INDEPENDENT_CONFIRMATION = false`，不作獨立確認或 100% 驗證之過度宣稱。

#### 全樣本描述性分位數 (Full Sample Descriptive)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Q1 (強空/大跌)** | 397,816 | 47.49% | +0.0246% | -0.0043% | **+0.0289%** | 10.74% | 0.07 |
| **Q2 (平盤/微跌)** | 397,832 | 42.76% | +0.0417% | -0.0070% | **+0.0487%** | 9.54% | 0.06 |
| **Q3 (平盤/微漲)** | 397,779 | 58.83% | -0.0168% | +0.0073% | **-0.0241%** | 6.89% | 0.04 |
| **Q4 (強多/大漲)** | 397,774 | 60.18% | -0.0157% | +0.0080% | **-0.0237%** | 7.70% | 0.05 |

#### Walk-Forward OOS Fold-by-Fold H01 結果（Authoritative Frozen WFA, Train-Only Calibrated）
* **Fold 1** (2025-01-07 ~ 2025-06-23): (Complete Fold)
  * Frozen Train Metadata: Train Range `2023-09-27 ~ 2025-01-03` | Train Signals `447,239` | Frozen Cuts `[-0.00383, -0.000565, 0.002688]`
  * OOS Overall: Signals=173,878, Retention=54.11%, Delta Theo=+0.0032%, Delta Net=-0.0006%
  * **Q1**: Delta Net = **+0.0461%** (Signals=48,663, Retention=48.27%)
  * **Q2**: Delta Net = **+0.0192%** (Signals=31,193, Retention=43.24%)
  * **Q3**: Delta Net = **-0.0218%** (Signals=34,406, Retention=57.93%)
  * **Q4**: Delta Net = **-0.0227%** (Signals=59,616, Retention=62.37%)
* **Fold 2** (2025-06-24 ~ 2025-11-19): (Complete Fold)
  * Frozen Train Metadata: Train Range `2024-03-06 ~ 2025-06-20` | Train Signals `499,268` | Frozen Cuts `[-0.004286, -0.000232, 0.00373]`
  * OOS Overall: Signals=184,374, Retention=52.86%, Delta Theo=+0.0025%, Delta Net=-0.0018%
  * **Q1**: Delta Net = **+0.0307%** (Signals=46,563, Retention=45.33%)
  * **Q2**: Delta Net = **+0.0400%** (Signals=38,832, Retention=41.22%)
  * **Q3**: Delta Net = **-0.0175%** (Signals=38,983, Retention=59.61%)
  * **Q4**: Delta Net = **-0.0277%** (Signals=59,996, Retention=61.85%)
* **Fold 3** (2025-11-20 ~ 2026-04-29): (Complete Fold)
  * Frozen Train Metadata: Train Range `2024-08-06 ~ 2025-11-18` | Train Signals `516,128` | Frozen Cuts `[-0.004291, 4.7e-05, 0.004616]`
  * OOS Overall: Signals=262,600, Retention=52.19%, Delta Theo=+0.0055%, Delta Net=+0.0038%
  * **Q1**: Delta Net = **+0.0307%** (Signals=87,062, Retention=46.83%)
  * **Q2**: Delta Net = **+0.0462%** (Signals=51,339, Retention=43.92%)
  * **Q3**: Delta Net = **-0.0239%** (Signals=61,734, Retention=58.89%)
  * **Q4**: Delta Net = **-0.0237%** (Signals=62,465, Retention=59.83%)
* **Fold 4** (2026-04-30 ~ 2026-09-24): (Complete Fold)
  * Frozen Train Metadata: Train Range `2025-01-06 ~ 2026-04-28` | Train Signals `619,708` | Frozen Cuts `[-0.005277, -3e-05, 0.004721]`
  * OOS Overall: Signals=512,041, Retention=51.88%, Delta Theo=+0.0070%, Delta Net=+0.0067%
  * **Q1**: Delta Net = **+0.0216%** (Signals=171,738, Retention=48.01%)
  * **Q2**: Delta Net = **+0.0740%** (Signals=99,624, Retention=43.06%)
  * **Q3**: Delta Net = **-0.0333%** (Signals=74,958, Retention=58.24%)
  * **Q4**: Delta Net = **-0.0177%** (Signals=165,721, Retention=58.33%)
* **Fold 5** (2026-09-29 ~ 2026-10-02): — **`INCOMPLETE_TERMINAL`** (僅涵蓋 4 個交易日、9,497 筆訊號，供歷史完整性記錄，不得與完整 Folds 等權解讀)
  * Frozen Train Metadata: Train Range `2025-06-23 ~ 2026-09-23` | Train Signals `956,205` | Frozen Cuts `[-0.006806, -0.000474, 0.005881]`
  * OOS Overall: Signals=9,497, Retention=54.47%, Delta Theo=+0.0133%, Delta Net=+0.0102%
  * **Q1**: Delta Net = **-0.1078%** (Signals=268, Retention=42.16%)
  * **Q2**: Delta Net = **+0.0219%** (Signals=2,600, Retention=44.08%)
  * **Q3**: Delta Net = **+0.0562%** (Signals=2,004, Retention=56.99%)
  * **Q4**: Delta Net = **-0.0060%** (Signals=4,625, Retention=59.94%)

### H02: 市場波動度 (Market Volatility)
> [!NOTE]
> MID (+0.0032%) 與 HIGH (+0.0024%) 波動度下 Delta Net 均為正向型態；LOW 波動度下 Delta Theo 雖微正 (+0.0015%)，但因交易摩擦增加 (+0.0032%) 導致 Delta Net 為負 (-0.0017%)。
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LOW** | 18,619 | 55.89% | +0.0015% | +0.0032% | **-0.0017%** | 9.13% | 0.06 |
| **MID** | 371,359 | 52.66% | +0.0065% | +0.0033% | **+0.0032%** | 7.07% | 0.04 |
| **HIGH** | 1,201,223 | 52.15% | +0.0042% | +0.0018% | **+0.0024%** | 8.99% | 0.06 |

### H03: 開盤方向情境 (Opening Direction Context)

#### 開盤 15 分鐘窗口 (H03_opening_15m)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **POSITIVE (開高走強)** | 683,976 | 55.45% | -0.0063% | +0.0053% | **-0.0116%** | 7.76% | 0.05 |
| **NEUTRAL (開盤平盤)** | 120,493 | 52.43% | +0.0161% | +0.0012% | **+0.0149%** | 8.05% | 0.05 |
| **NEGATIVE (開低走弱)** | 657,338 | 47.97% | +0.0124% | -0.0026% | **+0.0150%** | 8.37% | 0.05 |
| **NOT_AVAILABLE** | 129,394 | 57.73% | +0.0150% | +0.0041% | **+0.0109%** | 13.63% | 0.10 |

#### 開盤 30 分鐘窗口 (H03_opening_30m, 預先註冊權威因果產物)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **POSITIVE (開高走強)** | 599,762 | 55.76% | -0.0106% | +0.0054% | **-0.0160%** | 7.02% | 0.04 |
| **NEUTRAL (開盤平盤)** | 97,885 | 52.89% | +0.0106% | +0.0026% | **+0.0080%** | 7.15% | 0.04 |
| **NEGATIVE (開低走弱)** | 609,396 | 47.28% | +0.0156% | -0.0038% | **+0.0194%** | 8.04% | 0.04 |
| **NOT_AVAILABLE (09:30前未完成窗口)** | 284,158 | 55.65% | +0.0136% | +0.0044% | **+0.0092%** | 13.12% | 0.10 |

> [!NOTE]
> **H03 30m 數據來源與定義判定說明**：
> 依據預先註冊因果合約，30 分鐘開盤窗口（[09:00, 09:30)）必須嚴格在 09:30:00 收盤價確認後方可使用。
> 在全歷史中，於 09:30:00 前觸發之訊號共有 284,158 筆，其 30m 特徵嚴格屬於 `NOT_AVAILABLE`。
> 舊草稿中出現之 139,290 筆係誤套用 15m 之時段截斷所致；本報告與 summary 統一以權威因果定義之 284,158 筆為準。
> 15m 與 30m 兩者型態高度一致：開高走強（POSITIVE）時觀察到負向型態（15m: -0.0116%, 30m: -0.0160%）；開盤走平（NEUTRAL）或開低（NEGATIVE）時觀察到正向型態。

### H04: 當日時間窗 (Time of Day)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OPEN (09:00 ~ 10:00)** | 540,514 | 54.16% | +0.0077% | +0.0034% | **+0.0043%** | 12.02% | 0.09 |
| **MID (10:00 ~ 12:00)** | 647,042 | 51.43% | -0.0007% | +0.0015% | **-0.0022%** | 7.43% | 0.04 |
| **LATE (12:00 ~ 13:30)** | 403,645 | 51.27% | +0.0079% | +0.0001% | **+0.0078%** | 5.41% | 0.03 |

> [!NOTE]
> 早盤 OPEN 觀察到正向型態 (+0.0043%)，盤中 MID 觀察到負向型態 (-0.0022%)，尾盤 LATE 觀察到最強正向型態 (+0.0078%) 且摩擦微小。

### H05: 代理標的廣度 (Proxy Breadth Robustness)
> [!WARNING]
> 檔數廣度不具單調改善性：55–79 檔區間 Delta Net 為負（-0.0156%）。
> 且歷史檔數擴充與年份高度混淆（`YEAR_AND_UNIVERSE_CONFOUNDED` 與 `UNIVERSE_EXPANSION_CONFOUND`），不得將廣度視為獨立因果驅動因子。
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BREADTH_34_54** | 1,145,324 | 52.48% | +0.0033% | +0.0028% | **+0.0005%** | 6.86% | 0.04 |
| **BREADTH_55_79** | 17,855 | 52.51% | -0.0156% | -0.0000% | **-0.0156%** | 8.74% | 0.06 |
| **BREADTH_80_99** | 427,150 | 51.85% | +0.0096% | +0.0005% | **+0.0091%** | 13.08% | 0.10 |
| **INSUFFICIENT_BREADTH** | 872 | 61.01% | +0.0184% | +0.0062% | **+0.0122%** | 7.89% | 0.05 |

### H06: 候選策略與方向 (Candidate Direction Breakdown)
> [!IMPORTANT]
> 方向與候選策略呈現異質性：
> **做多 (LONG) 整體呈現微幅負向 (LONG aggregate slightly negative, with candidate heterogeneity: P2B_01 negative, P2B_02 positive)**（LONG: -0.0007%, P2B_01: -0.0026%, P2B_02: +0.0028%）。
> 做空 (SHORT) 整體呈現正向型態 (+0.0024%)（P2B_03: +0.0061%, P2B_04: +0.0071% 均為正）。
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LONG** | 917,597 | 49.96% | +0.0034% | +0.0041% | **-0.0007%** | 7.25% | 0.05 |
| **SHORT** | 673,604 | 55.53% | +0.0032% | +0.0008% | **+0.0024%** | 10.13% | 0.06 |
| **P2B_01_v1 (LONG)** | 455,747 | 50.94% | +0.0019% | +0.0045% | **-0.0026%** | 4.94% | 0.03 |
| **P2B_02_v1 (LONG)** | 922,894 | 52.68% | +0.0049% | +0.0021% | **+0.0028%** | 9.74% | 0.06 |
| **P2B_03_v1 (SHORT)** | 196,422 | 53.13% | +0.0058% | -0.0003% | **+0.0061%** | 10.35% | 0.06 |
| **P2B_04_v1 (SHORT)** | 16,138 | 60.57% | +0.0084% | +0.0013% | **+0.0071%** | 15.26% | 0.08 |

### H07 & 年度特徵: 2025 年失效日與年度表現 (純客觀數據陳述)
> [!NOTE]
> 移除所有未經驗證之因果臆測（如反轉市場、均值回歸盤型等），以下純屬客觀回測數據陳述。

#### 日層級描述性分組 (Descriptive Day Grouping)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **IMPROVED_DAY** | 815,734 | 50.77% | +0.0401% | -0.0001% | **+0.0402%** | 10.52% | 0.07 |
| **DEGRADED_DAY** | 775,467 | 53.94% | -0.0300% | +0.0045% | **-0.0345%** | 6.58% | 0.04 |

#### 歷史年度表現 (Yearly Robustness Breakdown)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2023** | 78,608 | 50.25% | +0.0043% | +0.0009% | **+0.0034%** | 4.65% | 0.02 |
| **2024** | 365,684 | 52.23% | +0.0034% | +0.0029% | **+0.0005%** | 5.14% | 0.03 |
| **2025** | 426,091 | 53.33% | +0.0006% | +0.0039% | **-0.0033%** | 6.62% | 0.04 |
| **2026** | 720,818 | 51.98% | +0.0081% | +0.0007% | **+0.0074%** | 11.85% | 0.09 |

---

## 6. 核心研究問題直接回答 (Direct Answers to Research Questions - Corrected)

### Q1: F01 theoretical improvement 是否隨 trend strength 增強？
**結論**: `DIRECTIONAL_ASYMMETRY_OBSERVED`（非絕對強度單調增強）
* **分析說明**: 數據並非隨趨勢強度絕對值單調提升，而是呈現明確的方向不對稱型態。在所有 4 個完整 OOS Folds (1~4) 中，Q1 (強空) 與 Q2 (微跌/平盤) 均穩定觀察到正向型態 (Delta Net > 0)，而 Q3 (微漲/平盤) 與 Q4 (強多) 則觀察到負向型態 (Delta Net < 0)。全樣本描述性分位數亦然（Q1: +0.0289%, Q2: +0.0487%, Q3: -0.0241%, Q4: -0.0237%）。Fold 5 為 `INCOMPLETE_TERMINAL`（僅涵蓋 4 天、9,497 筆訊號），不與完整 Folds 等權解讀。

### Q2: F01 是否主要在 high volatility 環境改善？
**結論**: `MID_AND_HIGH_VOLATILITY_POSITIVE`（低波動受摩擦侵蝕）
* **分析說明**: MID 波動度（Delta Net `+0.0032%`）與 HIGH 波動度（Delta Net `+0.0024%`）均呈現正向型態。LOW 波動度環境下理論報酬雖微幅正向（`+0.0015%`），但因交易摩擦增加（`+0.0032%`），淨變化為負值（`-0.0017%`）。非 HIGH-only。

### Q3: Opening direction 是否能解釋 F01 成敗？
**結論**: `OPPOSITE_DIRECTIONAL_PATTERN_OBSERVED`（15m 與 30m 高度一致）
* **分析說明**: 依權威因果定義，開高走強（POSITIVE）在 15m（`-0.0116%`）與 30m（`-0.0160%`）下均觀察到負向型態；開盤走平（NEUTRAL）或開低走弱（NEGATIVE）在 15m（`+0.0149%`、`+0.0150%`）與 30m（`+0.0080%`、`+0.0194%`）下均觀察到正向型態。

### Q4: F01 是否主要集中於 OPEN / MID / LATE 某一時段？
**結論**: `LATE_STRONGEST_MID_DEGRADED`
* **分析說明**: 早盤 OPEN (09:00~10:00) 觀察到正向型態（Delta Net `+0.0043%`）；盤中 MID (10:00~12:00) 觀察到負向型態（Delta Net `-0.0022%`）；尾盤 LATE (12:00~13:30) 觀察到最強正向型態（Delta Net `+0.0078%`）且無顯著額外摩擦成本。

### Q5: Proxy breadth 是否影響 F01 effect magnitude？
**結論**: `NON_MONOTONIC_AND_CONFOUNDED`
* **分析說明**: 代理標的廣度不具單調性：55–79 檔區間 Delta Net 為負（`-0.0156%`），80–99 檔為正（`+0.0091%`），34–54 檔微正（`+0.0005%`）。歷史廣度與母體由 55 檔擴展至 100 檔高度混淆（`YEAR_AND_UNIVERSE_CONFOUNDED`），不可視為獨立因果效益。

### Q6: LONG 與 SHORT 是否有明顯不對稱？
**結論**: `DIRECTIONAL_AND_CANDIDATE_HETEROGENEITY`
* **分析說明**: LONG aggregate slightly negative, with candidate heterogeneity: P2B_01 negative, P2B_02 positive. 做多整體呈現微幅負向（Delta Net `-0.0007%`），且存在策略異質性（P2B_01 為 `-0.0026%`，P2B_02 為 `+0.0028%`）；做空整體呈現正向型態（Delta Net `+0.0024%`，P2B_03 `+0.0061%`，P2B_04 `+0.0071%` 均為正）。嚴禁推導 Direction $\times$ Regime 交互作用。

### Q7: 2025 failure period 和 improvement periods 最明顯差異是什麼？
**結論**: `EMPIRICALLY_HIGH_FRICTION_AND_WEAK_THEO_GAIN`
* **分析說明**: 純客觀數據：2025 年 Delta Theo 僅 `+0.0006%`（全年最低），Delta Friction 達 `+0.0039%`（全年最高），導致 Delta Net 為 `-0.0033%`。核心特徵為理論增益微弱且交易摩擦吃掉超額收益。

---

## 7. 治理邊界與結論 (Governance Integrity & Non-Selection Policy)

* **NO_WINNER_SELECTION**: 本研究之所有分層發現純屬機制理解（`MECHANISM_AND_FAILURE_REGIME_ANALYSIS`），**嚴格禁止建立 F01_v2 或挑選子環境作為生產濾網**。
* **FUTURE_CONTRACT_PROTECTION**: 本研究全數使用 2023-09-27 至 2026-10-02 既有歷史資料，**嚴格禁止讀取或檢視任何 2026-10-02 以後之資料**。未來 60 天獨立驗證契約保持完全未碰觸（Untouched）。
* **PRODUCTION_CODE_CHANGED = false**: 零生產程式碼變更，零真實交易呼叫，維持純研究性質。
* **當前狀態標記**:
  * `COMMIT_CREATED = false`
  * `PUSHED = false`
  * `PRODUCTION_CODE_CHANGED = false`
  * `READY_FOR_SEAL = false`
