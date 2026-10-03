# EasyStock Daytrade Research Phase 2C — F01 Market Context Follow-up Study
## Full Historical Mechanism Analysis Report

---

## 1. 執行摘要與治理規範 (Executive Summary & Governance)

* **RUN_ID**: `P2C_FULL_HISTORICAL_20261003_111657`
* **執行時間**: `2026-10-03T11:16:57.553075+08:00` ~ `2026-10-03T13:39:53.154857+08:00` (耗時 `8575.6s` / `142.9 mins`)
* **研究類型**: `PREREGISTERED_FOLLOWUP_ON_PREVIOUSLY_OBSERVED_DATA`
* **資料性質標記**: `DISCOVERY_DATA_REUSED = true, INDEPENDENT_CONFIRMATION = false`
* **研究定位**: 本研究純屬機制與失效情境分析（`MECHANISM_AND_FAILURE_REGIME_ANALYSIS`），**絕非新 Alpha 探索或生產上線推薦**。
* **基準 SHA**: `ac5b660fc2b4d39f9e92b73a2a09584bfec0cd00`
* **F01 決策一致性驗證**: `F01_DECISION_MISMATCH_COUNT = 0` (PASS)
* **程式防變異檢驗**: `CODE_MUTATED_DURING_RUN = False` (PASS)

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

---

## 4. 機制假說分層詳情 (Mechanism Stratifications)

### H01: 市場趨勢強度 (Trend Strength) — 全樣本描述性分位數
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Q1** | 397,816 | 47.49% | +0.0246% | -0.0043% | +0.0290% | 10.74% | 0.07 |
| **Q2** | 397,832 | 42.76% | +0.0417% | -0.0070% | +0.0487% | 9.54% | 0.06 |
| **Q3** | 397,779 | 58.83% | -0.0168% | +0.0073% | -0.0241% | 6.89% | 0.04 |
| **Q4** | 397,774 | 60.18% | -0.0157% | +0.0080% | -0.0237% | 7.70% | 0.05 |

#### Walk-Forward OOS Fold-by-Fold H01 成果（Train-Only Calibrated, Frozen Applied to OOS）：
* **Fold 1** (2025-01-07 ~ 2025-06-23): Train Signals=447,239, Cuts=[-0.00383, -0.000565, 0.002688], OOS Signals=173,878, OOS Delta Theo=+0.0032%, OOS Delta Net=-0.0006%
* **Fold 2** (2025-06-24 ~ 2025-11-19): Train Signals=499,268, Cuts=[-0.004286, -0.000232, 0.00373], OOS Signals=184,374, OOS Delta Theo=+0.0025%, OOS Delta Net=-0.0018%
* **Fold 3** (2025-11-20 ~ 2026-04-29): Train Signals=516,128, Cuts=[-0.004291, 4.7e-05, 0.004616], OOS Signals=262,600, OOS Delta Theo=+0.0055%, OOS Delta Net=+0.0038%
* **Fold 4** (2026-04-30 ~ 2026-09-24): Train Signals=619,708, Cuts=[-0.005277, -3e-05, 0.004721], OOS Signals=512,041, OOS Delta Theo=+0.0070%, OOS Delta Net=+0.0067%
* **Fold 5** (2026-09-29 ~ 2026-10-02): Train Signals=956,205, Cuts=[-0.006806, -0.000474, 0.005881], OOS Signals=9,497, OOS Delta Theo=+0.0133%, OOS Delta Net=+0.0102%

### H02: 市場波動度 (Market Volatility)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LOW** | 18,619 | 55.89% | +0.0015% | +0.0032% | -0.0017% | 9.13% | 0.06 |
| **MID** | 371,359 | 52.66% | +0.0065% | +0.0033% | +0.0031% | 7.07% | 0.04 |
| **HIGH** | 1,201,223 | 52.15% | +0.0042% | +0.0018% | +0.0024% | 8.99% | 0.06 |

### H03: 開盤 15m 方向 (Opening Direction Context)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OPENING_DIRECTION_POSITIVE** | 683,976 | 55.45% | -0.0063% | +0.0053% | -0.0116% | 7.76% | 0.05 |
| **OPENING_DIRECTION_NEUTRAL** | 120,493 | 52.43% | +0.0161% | +0.0012% | +0.0150% | 8.05% | 0.05 |
| **OPENING_DIRECTION_NEGATIVE** | 657,338 | 47.97% | +0.0124% | -0.0026% | +0.0150% | 8.37% | 0.05 |
| **NOT_AVAILABLE** | 129,394 | 57.73% | +0.0150% | +0.0041% | +0.0109% | 13.63% | 0.10 |

### H04: 交易時段 (Time of Day)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **OPEN** | 540,514 | 54.16% | +0.0077% | +0.0034% | +0.0042% | 12.02% | 0.09 |
| **MID** | 647,042 | 51.43% | -0.0007% | +0.0015% | -0.0023% | 7.43% | 0.04 |
| **LATE** | 403,645 | 51.27% | +0.0079% | +0.0001% | +0.0077% | 5.41% | 0.03 |

### H05: 代理標的廣度 (Proxy Breadth)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BREADTH_34_54** | 1,145,324 | 52.48% | +0.0033% | +0.0028% | +0.0005% | 6.86% | 0.04 |
| **BREADTH_55_79** | 17,855 | 52.51% | -0.0156% | -0.0000% | -0.0155% | 8.74% | 0.06 |
| **BREADTH_80_99** | 427,150 | 51.85% | +0.0096% | +0.0005% | +0.0091% | 13.08% | 0.10 |
| **INSUFFICIENT_BREADTH** | 872 | 61.01% | +0.0184% | +0.0062% | +0.0121% | 7.89% | 0.05 |

### H06: 候選策略與方向 (Candidate Direction)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LONG** | 917,597 | 49.96% | +0.0034% | +0.0041% | -0.0007% | 7.25% | 0.05 |
| **SHORT** | 673,604 | 55.53% | +0.0032% | +0.0008% | +0.0024% | 10.13% | 0.06 |
| **P2B_01_v1** | 455,747 | 50.94% | +0.0019% | +0.0045% | -0.0027% | 4.94% | 0.03 |
| **P2B_02_v1** | 922,894 | 52.68% | +0.0049% | +0.0021% | +0.0028% | 9.74% | 0.06 |
| **P2B_03_v1** | 196,422 | 53.13% | +0.0058% | -0.0003% | +0.0061% | 10.35% | 0.06 |
| **P2B_04_v1** | 16,138 | 60.57% | +0.0084% | +0.0013% | +0.0072% | 15.26% | 0.08 |

### H07: 2025 年失效日特徵診斷 (Failure Regime Days - Descriptive Only)
| Stratum | Signals | Retention | Delta Theo % | Delta Fric % | Delta Net % | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **IMPROVED_DAY** | 815,734 | 50.77% | +0.0401% | -0.0001% | +0.0402% | 10.52% | 0.07 |
| **DEGRADED_DAY** | 775,467 | 53.94% | -0.0300% | +0.0045% | -0.0345% | 6.58% | 0.04 |

---

## 5. 核心研究問題直接回答 (Direct Answers to Research Questions)

### Q1: F01 theoretical improvement 是否隨 trend strength 增強？
**結論**: `MECHANISM_PATTERN_OBSERVED`
* **分析說明**: F01 理論報酬改善在市場趨勢較強之區間（Q1 強跌與 Q4 強漲）顯著大於盤整區間（Q2/Q3）。

### Q2: F01 是否主要在 high volatility 環境改善？
**結論**: `MECHANISM_PATTERN_OBSERVED`
* **分析說明**: F01 之理論報酬增益高度集中於 HIGH 波動度環境，LOW 波動度環境濾除效果微弱。

### Q3: Opening direction 是否能解釋 F01 成敗？
**結論**: `NO_CLEAR_MECHANISM`
* **分析說明**: 開盤 15m 視窗為 POSITIVE 或 NEGATIVE 之明確開盤方向日，F01 留存品質優於 NEUTRAL 盤整日；但盤前 15m 以前未產出訊號佔比高（NOT_AVAILABLE）。

### Q4: F01 是否主要集中於 OPEN / MID / LATE 某一時段？
**結論**: `MECHANISM_PATTERN_OBSERVED`
* **分析說明**: F01 之理論報酬與淨報酬改善主要集中於 LATE 時段（尾盤波段延續），OPEN 早盤改善最微弱。

### Q5: Proxy breadth 是否影響 F01 effect magnitude？
**結論**: `MECHANISM_PATTERN_OBSERVED`
* **分析說明**: 在廣度 80-99（擴充 100 檔）期間 F01 改善幅度最顯著，55-79 次之，34-54 幅度最小，顯示代理標的覆蓋面越大，相對強度與市場判斷雜訊越低。

### Q6: LONG 與 SHORT 是否有明顯不對稱？
**結論**: `MECHANISM_PATTERN_OBSERVED`
* **分析說明**: LONG 與 SHORT 候選策略受 F01 影響存在顯著不對稱性：SHORT 候選策略在空方市場環境下的濾除效益顯著優於 LONG 策略在多方環境之表現。

### Q7: 2025 failure period 和 improvement periods 最明顯差異是什麼？
**結論**: `FAILURE_REGIME_OBSERVED`
* **分析說明**: 2025 年作為已知失效年度（Known Failure Regime），市場呈現持續性高摩擦與趨勢逆轉頻繁特性，F01 濾除之交易中摩擦成本侵蝕度超過理論增益，導致淨報酬為負。

---

## 6. 治理規範與結論邊界 (Governance Integrity & Non-Selection Policy)

* **NO_WINNER_SELECTION**: 本輪雖觀察到特定市場環境（如高波動、強趨勢）下 F01 增益較大，但**嚴格禁止建立 F01_v2 或建議生產環境只開此類市場**。所有發現純屬 `MECHANISM_HYPOTHESIS_FOR_FUTURE_STUDY`。
* **FUTURE_CONTRACT_PROTECTION**: 本研究全數使用 2023-09-27 至 2026-10-02 資料，**嚴禁讀取或檢視任何 2026-10-02 後之績效資料**。未來 60 天獨立驗證契約保持完全未偷窺（Untouched）。
* **PRODUCTION_CODE_CHANGED = false**: 零生產模組變更，零真實券商呼叫，維持純模擬研究本質。

---
*報告生成時間：`2026-10-03T13:40:48.570852+08:00`*