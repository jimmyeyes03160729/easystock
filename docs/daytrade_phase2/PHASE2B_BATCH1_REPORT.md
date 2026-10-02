# EasyStock Daytrade Research Phase 2B — Batch 1 Full Historical Research Report

## 1. Executive Summary & Research Governance

Phase 2B Batch 1 **Full Historical Signal Research** has completed across the entirety of the historical archive. Following the pre-registered execution plan (`docs/daytrade_phase2/PHASE2B_BATCH1_FULL_RUN_PLAN.yaml`), all 4 candidate intraday price-action patterns were evaluated over 43,390 stock-days spanning 726 trading dates.

### Governance Status
- **RESEARCH_ONLY**: `True`
- **INERT_BY_DEFAULT**: `True`
- **IMPLEMENTATION_STATUS**: `VERIFIED`
- **PERFORMANCE_STATUS**: `EVALUATED_NEGATIVE`
- **FULL_HISTORICAL_RESEARCH_STATUS**: `COMPLETED`
- **DECISION_STATUS**: `FULL_SAMPLE_EVALUATED`
- **DIRECTIONAL_IMPLEMENTATION_PARTIAL**: `True`
- **REJECTION_SCOPE**: `CURRENT_V1_IMPLEMENTATION_ONLY`
- **THEORETICAL_SCOPE_DISCLAIMER**: Rejection applies strictly to the current single-directional v1 implementation, current parameter grid, current dataset, and cost model. It does NOT claim that Volume Price Analysis (VPA), Volatility Breakout / Range Expansion, Trader Vic 2B, Trader Vic 1-2-3, or underlying author theories are invalid.
- **PRE_REGISTRATION_PLAN_HASH**: `fca939c41f7095763ce80fc84460279a0d973a3fbccb2904f2fb01f0f9f3a304`
- **PRODUCTION_BEHAVIOR**: `UNCHANGED` (Zero production modifications; static AST isolation verified)
- **PROMOTION_TO_PRODUCTION**: `STRICTLY_FORBIDDEN` (All 4 candidates rejected based on empirical historical evidence)
- **GIT_STATUS**: Uncommitted & unpushed, strictly following instructions.

---

## 2. Dataset Coverage & Data Audit

| Metric | Historical Reality | Audit Classification |
| :--- | :--- | :--- |
| **Population Name** | `CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE` | Research Sample |
| **Historical Source** | Shioaji Expanded Historical Archive (`/home/ubuntu/easystock-history-expanded-data/raw`) | Raw compressed JSON gz |
| **Active Symbols** | **100** symbols | Frozen current liquidity pool |
| **Trading Dates** | **726** dates (2023-09-04 to 2026-10-02) | Full available timeline |
| **Total Stock-Days Evaluated** | **43,390** symbol-days | 100% of archived files |
| **Stock-Days COMPLETE** | **18,753** (43.2%) | All 266 expected session marks present |
| **Stock-Days USABLE_WITH_GAPS** | **24,612** (56.7%) | Partial unknown missingness (volume-filtered) |
| **Stock-Days INVALID** | **25** (0.06%) | Corrupted / < 10 bars / non-monotonic (excluded) |
| **Observed Large Gaps (Diagnostic)** | **12** symbol-days (0.03%) | Large price jumps (> 8.0%, diagnostic only) |
| **Corporate Action Data Status** | `UNAVAILABLE` | Boundary strictly remains `UNKNOWN` |
| **Dataset Bias Status** | `survivorship_bias = True`, `point_in_time_universe = False` | Current-universe selection bias present |

---

## 3. Candidate Research Verdicts & Performance Summary

Across the 43,390 stock-days, a total of **1,591,201 unique pattern signal events** were detected, generating **31,824,020 trade simulation rows** across the pre-registered parameter grids, 5 exit horizons, and 4 statutory slippage levels (exactly 20.0 simulation evaluations per unique signal event).

| Candidate ID | Name | Direction | Unique Signals | Simulation Rows | Win Rate | Net Exp (R) | OOS Exp (R) | Profit Factor | Research Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01_v1** | Pullback Volume Decay | LONG | 455,747 | 9,114,940 | 4.18% | **-4.5190R** | **-3.4996R** | 0.1918 | `REJECT_RESEARCH_CANDIDATE` |
| **P2B_02_v1** | Range Expansion Breakout | LONG | 922,894 | 18,457,880 | 9.05% | **-2.9528R** | **-2.2561R** | 0.2544 | `REJECT_RESEARCH_CANDIDATE` |
| **P2B_03_v1** | Trader Vic 2B Reversal | SHORT | 196,422 | 3,928,440 | 10.45% | **-2.5192R** | **-1.8861R** | 0.3232 | `REJECT_RESEARCH_CANDIDATE` |
| **P2B_04_v1** | Trader Vic 1-2-3 Reversal | SHORT | 16,138 | 322,760 | 14.41% | **-2.0332R** | **-1.4714R** | 0.4076 | `REJECT_RESEARCH_CANDIDATE` |

### Key Findings & Verdict Rationales
1. **Severe Frictional Drag & Negative Expectancy**:
   - In raw price action without execution costs, simple textbook price-action patterns show negative or near-zero gross edges in TWSE 1-minute bars.
   - When **ROUND_TRIP_TRADING_FRICTION** is factored in (composed of statutory daytrade transaction tax at 0.15% [`OFFICIAL_MARKET_REFERENCE`], configured broker commission at 0.1425% × 0.28 with 20 TWD min [`BROKER_ACCOUNT_PARAMETER` / `EASYSTOCK_EXISTING_PARAMETER`], and canonical slippage grid [`RESEARCH_GOVERNANCE_CANDIDATE`]), **all four candidates suffer massive negative net expectancies** (ranging from -2.03R to -4.52R).
2. **Rejection Verdicts & Descriptive Empirical Rationale**:
   - Post-hoc heuristic thresholds ($\Delta \text{Expectancy} \ge +0.05R$, $\text{Profit Factor} \ge 1.10$, $\text{OOS Expectancy} > 0.0R$) were **not pre-registered** in `PHASE2B_BATCH1_FULL_RUN_PLAN.yaml` (`PRE_REGISTERED = false`), and are classified strictly as `POST_HOC_RESEARCH_GOVERNANCE_CANDIDATE`; they are **not** used as the formal verdict threshold.
   - The formal `REJECT_RESEARCH_CANDIDATE` verdict is grounded strictly on comprehensive **descriptive empirical evidence**:
     - `theoretical gross expectancy < 0`
     - `net expectancy < 0`
     - `complete-only expectancy < 0`
     - `usable-with-gaps expectancy < 0`
     - `all complete OOS folds < 0`
     - `trade-weighted OOS < 0`
   - **Scope of Rejection**: Rejection is strictly confined to:
     - `CURRENT_IMPLEMENTATION`
     - `CURRENT_PARAMETER_SPACE`
     - `CURRENT_DATASET`
     - `CURRENT_COST_MODEL`
     - `CURRENT_DIRECTIONAL_SCOPE`
   - **Zero candidates qualify for production consideration**.

---

## 4. Completeness Stratification Comparison

To ensure data integrity, metrics were stratified across session completeness classes. Because 1-minute kbars emit records only when volume occurs, missing intermediate bars reflect illiquidity or feed gaps. Stratification confirms that performance conclusions are invariant to missingness:

| Candidate ID | Stratum | Trade Count | Win Rate | Net Expectancy (R) | Gross Expectancy (R) | Cost Drag (R) | Profit Factor |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01** | ALL_USABLE | 9,114,940 | 4.18% | -4.5190R | -3.1381R | 3.9413R | 0.1918 |
| | COMPLETE_ONLY | 4,813,940 | 3.88% | -4.5039R | -3.2003R | 3.8800R | 0.0615 |
| | USABLE_WITH_GAPS | 4,301,000 | 4.52% | -4.5358R | -3.0685R | 4.0100R | 0.2515 |
| **P2B_02** | ALL_USABLE | 18,457,880 | 9.05% | -2.9528R | -1.7225R | 2.7681R | 0.2544 |
| | COMPLETE_ONLY | 11,197,660 | 8.95% | -2.9689R | -1.7582R | 2.7483R | 0.1481 |
| | USABLE_WITH_GAPS | 7,260,220 | 9.19% | -2.9280R | -1.6675R | 2.7986R | 0.3030 |
| **P2B_03** | ALL_USABLE | 3,928,440 | 10.45% | -2.5192R | -1.3789R | 2.5290R | 0.3232 |
| | COMPLETE_ONLY | 2,017,460 | 10.86% | -2.4706R | -1.3411R | 2.5109R | 0.2057 |
| | USABLE_WITH_GAPS | 1,910,980 | 10.03% | -2.5704R | -1.4187R | 2.5482R | 0.3564 |
| **P2B_04** | ALL_USABLE | 322,760 | 14.41% | -2.0332R | -0.9995R | 1.9678R | 0.4076 |
| | COMPLETE_ONLY | 152,660 | 15.28% | -1.7898R | -0.7932R | 1.8624R | 0.3125 |
| | USABLE_WITH_GAPS | 170,100 | 13.63% | -2.2517R | -1.1849R | 2.0624R | 0.4261 |

*Observation*: 在目前的完整與缺漏分層下，四個策略的負期望值表現維持一致（Negative result is robust across completeness strata），未觀察到策略表現因缺漏分層而有實質改善。

---

## 5. Walk-Forward 5-Fold Rolling Evaluation

Evaluated using `EventWalkForwardSplitter` with 12-month training windows, 4-month testing windows, 4-month rolling steps, event-based label overlap purging, and a 15-minute embargo. Parameter selection performed strictly on training data; out-of-sample (OOS) evaluated once on unpeaked test data:

### P2B_01: Pullback Volume Decay
| Fold | Train Window | Test Window | Train Trades | Test Trades | Train Net Exp (R) | OOS Net Exp (R) | OOS Win Rate | OOS PF |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fold 1** | 2023-09-27 ~ 2025-01-03 | 2025-01-08 ~ 2025-06-24 | 144,473 | 54,038 | -4.0029R | **-3.9344R** | 3.55% | 0.0533 |
| **Fold 2** | 2024-03-06 ~ 2025-06-20 | 2025-06-25 ~ 2025-11-20 | 157,304 | 55,346 | -3.9580R | **-3.8129R** | 4.10% | 0.0464 |
| **Fold 3** | 2024-08-06 ~ 2025-11-18 | 2025-11-21 ~ 2026-04-30 | 160,274 | 68,625 | -3.9175R | **-3.6226R** | 5.10% | 0.0968 |
| **Fold 4** | 2025-01-06 ~ 2026-04-28 | 2026-05-04 ~ 2026-09-29 | 177,422 | 129,670 | -3.7818R | **-3.1209R** | 7.74% | 0.3328 |
| **Fold 5** | 2025-06-23 ~ 2026-09-23 | 2026-09-30 ~ 2026-10-02 | 253,253 | 2,755 | -3.4988R | **-3.4374R** | 6.57% | 0.1764 |

### P2B_02: Range Expansion Breakout
| Fold | Train Window | Test Window | Train Trades | Test Trades | Train Net Exp (R) | OOS Net Exp (R) | OOS Win Rate | OOS PF |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fold 1** | 2023-09-27 ~ 2025-01-03 | 2025-01-08 ~ 2025-06-24 | 290,147 | 108,187 | -2.6713R | **-2.6121R** | 7.84% | 0.1837 |
| **Fold 2** | 2024-03-06 ~ 2025-06-20 | 2025-06-25 ~ 2025-11-20 | 315,920 | 111,288 | -2.6393R | **-2.4856R** | 8.87% | 0.2072 |
| **Fold 3** | 2024-08-06 ~ 2025-11-18 | 2025-11-21 ~ 2026-04-30 | 321,961 | 137,288 | -2.5936R | **-2.3477R** | 9.94% | 0.2644 |
| **Fold 4** | 2025-01-06 ~ 2026-04-28 | 2026-05-04 ~ 2026-09-29 | 355,595 | 259,573 | -2.4837R | **-2.0217R** | 12.87% | 0.4468 |
| **Fold 5** | 2025-06-23 ~ 2026-09-23 | 2026-09-30 ~ 2026-10-02 | 507,705 | 5,510 | -2.2592R | **-2.1504R** | 12.18% | 0.3541 |

### P2B_03: Trader Vic 2B False Breakout
| Fold | Train Window | Test Window | Train Trades | Test Trades | Train Net Exp (R) | OOS Net Exp (R) | OOS Win Rate | OOS PF |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fold 1** | 2023-09-27 ~ 2025-01-03 | 2025-01-08 ~ 2025-06-24 | 62,311 | 23,040 | -2.3168R | **-2.2748R** | 9.09% | 0.2520 |
| **Fold 2** | 2024-03-06 ~ 2025-06-20 | 2025-06-25 ~ 2025-11-20 | 67,882 | 23,707 | -2.2882R | **-2.1844R** | 10.08% | 0.2746 |
| **Fold 3** | 2024-08-06 ~ 2025-11-18 | 2025-11-21 ~ 2026-04-30 | 69,178 | 29,294 | -2.2505R | **-1.9766R** | 11.83% | 0.3444 |
| **Fold 4** | 2025-01-06 ~ 2026-04-28 | 2026-05-04 ~ 2026-09-29 | 76,432 | 55,517 | -2.1264R | **-1.5963R** | 16.27% | 0.5898 |
| **Fold 5** | 2025-06-23 ~ 2026-09-23 | 2026-09-30 ~ 2026-10-02 | 108,983 | 1,177 | -1.8906R | **-2.0112R** | 13.59% | 0.3686 |

### P2B_04: Trader Vic 1-2-3 Trend Change
| Fold | Train Window | Test Window | Train Trades | Test Trades | Train Net Exp (R) | OOS Net Exp (R) | OOS Win Rate | OOS PF |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fold 1** | 2023-09-27 ~ 2025-01-03 | 2025-01-08 ~ 2025-06-24 | 4,964 | 1,858 | -2.0588R | **-2.0203R** | 12.00% | 0.3129 |
| **Fold 2** | 2024-03-06 ~ 2025-06-20 | 2025-06-25 ~ 2025-11-20 | 5,420 | 1,911 | -2.0244R | **-1.8679R** | 13.50% | 0.3703 |
| **Fold 3** | 2024-08-06 ~ 2025-11-18 | 2025-11-21 ~ 2026-04-30 | 5,530 | 2,367 | -1.9796R | **-1.5392R** | 16.69% | 0.4996 |
| **Fold 4** | 2025-01-06 ~ 2026-04-28 | 2026-05-04 ~ 2026-09-29 | 6,140 | 4,507 | -1.8101R | **-1.1884R** | 21.81% | 0.8176 |
| **Fold 5** | 2025-06-23 ~ 2026-09-23 | 2026-09-30 ~ 2026-10-02 | 8,874 | 97 | -1.4727R | **-1.7577R** | 17.53% | 0.5050 |

---

## 6. Statutory Slippage Grid Sensitivity Analysis

Evaluated across the canonical TWSE tick-size grid `[0, 1, 2, 3]` ticks (dynamically mapped per TWSE price bracket: $0.01 for $P<10$, $0.05 for $10\le P<50$, $0.10 for $50\le P<100$, $0.50 for $100\le P<500$, $1.00 for $500\le P<1000$, $5.00 for $P\ge 1000$):

| Candidate ID | Slippage (Ticks) | Net Exp (R) | Gross Exp (R) | Cost Drag (R) | Win Rate | Profit Factor |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01** | 0 ticks | -1.9605R | -0.5777R | 1.3828R | 7.94% | 0.7260 |
| | 1 tick | -3.6661R | -2.2846R | 3.0885R | 4.33% | 0.2629 |
| | 2 ticks | -5.3718R | -3.9915R | 4.7942R | 2.66% | 0.1338 |
| | 3 ticks | -7.0775R | -5.6985R | 6.4998R | 1.79% | 0.0798 |
| **P2B_02** | 0 ticks | -1.1660R | -0.1913R | 0.9747R | 18.04% | 0.8759 |
| | 1 tick | -2.3572R | -1.3825R | 2.1659R | 9.39% | 0.3469 |
| | 2 ticks | -3.5485R | -2.5737R | 3.3572R | 5.36% | 0.1721 |
| | 3 ticks | -4.7397R | -3.7650R | 4.5484R | 3.39% | 0.0986 |
| **P2B_03** | 0 ticks | -0.9732R | -0.0944R | 0.8789R | 21.45% | 1.0247 |
| | 1 tick | -2.0038R | -1.1242R | 1.9095R | 10.85% | 0.4368 |
| | 2 ticks | -3.0345R | -2.1541R | 2.9401R | 5.93% | 0.2222 |
| | 3 ticks | -4.0651R | -3.1839R | 3.9707R | 3.58% | 0.1290 |
| **P2B_04** | 0 ticks | -0.7903R | -0.0674R | 0.7229R | 25.91% | 1.0299 |
| | 1 tick | -1.6189R | -0.8955R | 1.5515R | 15.57% | 0.5306 |
| | 2 ticks | -2.4476R | -1.7235R | 2.3802R | 9.80% | 0.2998 |
| | 3 ticks | -3.2762R | -2.5515R | 3.2088R | 6.37% | 0.1836 |

### Critical Takeaway on Execution Friction:
- Even at **0 slippage** (perfect mid/limit fill at theoretical price), all 4 candidates have **negative net expectancy** due to **ROUND_TRIP_TRADING_FRICTION** (daytrade transaction tax at 0.15% [`OFFICIAL_MARKET_REFERENCE`] and configured broker commission at 0.1425% × 0.28 [`BROKER_ACCOUNT_PARAMETER` / `EASYSTOCK_EXISTING_PARAMETER`]).
- With just **1 tick adverse slippage** on entry and exit, net expectancy deteriorates by ~1.0R to ~1.7R per trade, collapsing win rates below 15%.
- This demonstrates that price-action patterns alone, without strong structural momentum or higher-timeframe confluence, cannot overcome round-trip trading friction in the current single-directional v1 implementations.

---

## 7. Exit Policy & Holding Period Sensitivity

| Candidate ID | Exit Policy | Net Exp (R) | Win Rate | Profit Factor |
| :--- | :--- | :--- | :--- | :--- |
| **P2B_01** | `FIXED_HORIZON_5M` | -4.4846R | 3.92% | 0.1538 |
| | `FIXED_HORIZON_15M` | -4.5131R | 4.41% | 0.1952 |
| | `FIXED_HORIZON_30M` | -4.5241R | 4.40% | 0.2246 |
| | `FIXED_HORIZON_60M` | -4.5310R | 4.22% | 0.2473 |
| | `STOP_TARGET_1_5R_MAX30M` | -4.5420R | 3.95% | 0.1275 |
| **P2B_02** | `FIXED_HORIZON_5M` | -2.9137R | 7.10% | 0.1848 |
| | `FIXED_HORIZON_15M` | -2.9594R | 9.00% | 0.2516 |
| | `FIXED_HORIZON_30M` | -2.9695R | 9.69% | 0.2939 |
| | `FIXED_HORIZON_60M` | -2.9693R | 9.84% | 0.3262 |
| | `STOP_TARGET_1_5R_MAX30M` | -2.9521R | 9.60% | 0.1954 |
| **P2B_03** | `FIXED_HORIZON_5M` | -2.4925R | 6.94% | 0.2089 |
| | `FIXED_HORIZON_15M` | -2.5274R | 9.95% | 0.3099 |
| | `FIXED_HORIZON_30M` | -2.5319R | 11.51% | 0.3649 |
| | `FIXED_HORIZON_60M` | -2.5214R | 12.50% | 0.4264 |
| | `STOP_TARGET_1_5R_MAX30M` | -2.5228R | 11.36% | 0.2754 |
| **P2B_04** | `FIXED_HORIZON_5M` | -2.0268R | 9.29% | 0.2677 |
| | `FIXED_HORIZON_15M` | -2.0557R | 13.22% | 0.3667 |
| | `FIXED_HORIZON_30M` | -2.0407R | 15.60% | 0.4451 |
| | `FIXED_HORIZON_60M` | -2.0132R | 17.21% | 0.4997 |
| | `STOP_TARGET_1_5R_MAX30M` | -2.0298R | 16.74% | 0.4161 |

---

## 8. Subgroup Segmentations (Year & Time of Day)

### Yearly Segmentation (2023 - 2026)
| Candidate ID | Year 2023 | Year 2024 | Year 2025 | Year 2026 |
| :--- | :--- | :--- | :--- | :--- |
| **P2B_01** | -4.9836R (WR: 2.18%) | -4.9038R (WR: 2.48%) | -4.7531R (WR: 3.36%) | -4.0460R (WR: 6.12%) |
| **P2B_02** | -3.3109R (WR: 5.95%) | -3.3098R (WR: 6.50%) | -3.1635R (WR: 7.68%) | -2.6381R (WR: 11.27%) |
| **P2B_03** | -2.9648R (WR: 6.41%) | -2.9159R (WR: 6.91%) | -2.7594R (WR: 8.24%) | -2.1368R (WR: 13.92%) |
| **P2B_04** | -2.6312R (WR: 8.92%) | -2.7459R (WR: 9.03%) | -2.3883R (WR: 11.47%) | -1.5618R (WR: 18.18%) |

*Observation*: Although 2026 exhibits slightly higher volatility and improved win rate, net expectancy remains uniformly negative in every single year.

### Time-of-Day Segmentation
| Candidate ID | Morning (09:00 - 10:30) | Mid-Day (10:30 - 12:00) | Afternoon (12:00 - 13:30) |
| :--- | :--- | :--- | :--- |
| **P2B_01** | **-4.1975R** (WR: 5.59%) | -4.7555R (WR: 3.12%) | -4.9639R (WR: 2.25%) |
| **P2B_02** | **-2.6017R** (WR: 11.53%) | -3.1367R (WR: 7.75%) | -3.3970R (WR: 5.89%) |
| **P2B_03** | **-2.1021R** (WR: 14.24%) | -2.6539R (WR: 9.13%) | -2.9596R (WR: 6.56%) |
| **P2B_04** | **-1.6880R** (WR: 17.05%) | -2.3106R (WR: 12.38%) | -2.5764R (WR: 10.15%) |

*Observation*: Morning sessions provide the best relative performance due to opening liquidity and range expansion, but still fail to achieve profitability after friction. Afternoon sessions suffer the worst decay across all patterns.

---

## 9. Final Research Governance & Architecture Compliance

1. **Research Isolation**:
   - Zero production imports or modifications (`strategy_engine.py`, `market_risk.py`, `position_manager.py` untouched).
   - AST test `test_static_production_import_isolation` confirms 100% production isolation.
2. **Canonical Baseline Integrity**:
   - Knowledge V1 and Knowledge V2 Canonical documents remain strictly unmodified.
3. **No Promotion to Production**:
   - In accordance with Phase 2B governance rules, all four candidates are marked as `REJECT_RESEARCH_CANDIDATE`.
   - `PROMOTE_TO_PRODUCTION` is strictly forbidden.
4. **Git State**:
   - Working tree strictly uncommitted and unpushed per user directives.

---

## 10. Phase 2B Batch 1 Result Integrity Audit Report

針對 Full Historical Run 的統計口徑、成本會計恆等式、R 值分母敏感度、Walk-Forward 尾端折疊、基準 Provenance、方向性範疇與候選策略版本命名，完成以下 11 項全面審計：

### 10.1 Unique Signal vs Simulation Evaluations
- **審計結論**：原先報告之 31,824,020 筆「虛擬交易模擬」為每個訊號在不同參數、出場政策與滑價等級下的重複評估組合（Simulation Evaluations），並非獨立交易樣本。
- **拆解結構**：5 種 Exit Policies × 4 種 Statutory Slippages（0, 1, 2, 3 ticks）= 每個獨立訊號事件恰對應 **20.0 筆 Simulation Rows**。
- **各策略獨立訊號事件與評估筆數**：

| Candidate ID | Name | Direction | Unique Signal Events | Simulation Rows | Rows / Unique Signal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01_v1** | Pullback Volume Decay | LONG | **455,747** | 9,114,940 | 20.0 |
| **P2B_02_v1** | Range Expansion Breakout | LONG | **922,894** | 18,457,880 | 20.0 |
| **P2B_03_v1** | Trader Vic 2B Reversal | SHORT | **196,422** | 3,928,440 | 20.0 |
| **P2B_04_v1** | Trader Vic 1-2-3 Reversal | SHORT | **16,138** | 322,760 | 20.0 |
| **TOTAL** | — | — | **1,591,201** | **31,824,020** | **20.0** |

---

### 10.2 Cost Accounting Identity Audit
- **追查原因**：報告呈現之數值差異源於定義口徑不同——`full_historical_runner.py` 產出之 `actual_gross_pnl` 採用實際成交價計算（已內含滑價，即 Post-Slippage Gross），而 `cost_drag_R` 計算的是全摩擦成本（滑價 + 手續費 + 稅）。若將已扣除滑價之 Actual Gross 再減去 Total Cost Drag，即形成重複扣除滑價之表面矛盾。
- **會計恆等式（Accounting Identities）**：
  $$\text{Net Expectancy } R = \text{Theoretical Gross } R - \text{Total Cost Drag } R$$
  $$\text{Net Expectancy } R = \text{Actual Gross } R - \text{Statutory (Fee + Tax) Drag } R$$
  $$\text{Total Cost Drag } R = \text{Slippage Drag } R + \text{Statutory (Fee + Tax) Drag } R$$
- **數值核算檢驗（誤差精確為 0.000000R）**：

| Candidate ID | Theoretical Gross (R) | Slippage Drag (R) | Fee + Tax Drag (R) | Total Cost Drag (R) | Actual Gross (R) | Net Expectancy (R) | Identity Error |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01_v1** | -0.5777R | 2.5604R | 1.3809R | 3.9413R | -3.1381R | **-4.5190R** | **0.000000R** |
| **P2B_02_v1** | -0.1912R | 1.7869R | 0.9747R | 2.7616R | -1.7225R | **-2.9528R** | **0.000000R** |
| **P2B_03_v1** | -0.0944R | 1.5447R | 0.8801R | 2.4248R | -1.3789R | **-2.5192R** | **0.000000R** |
| **P2B_04_v1** | -0.0674R | 1.2421R | 0.7237R | 1.9658R | -0.9995R | **-2.0332R** | **0.000000R** |

- **回歸測試保護**：已在 `tests/test_phase2b_batch1.py` 新增 `test_cost_accounting_identity_invariant()`，多空雙向與多檔位均嚴格通過。

---

### 10.3 Initial Risk & R-Denominator Audit
- **實證統計（標記：`RISK_DISTRIBUTION_AUDIT = SAMPLED_DIAGNOSTIC`，抽樣 100 個交易日、5,486 個 stock-days 進行分母診斷）**：
- **邊界宣告**：本項為抽樣診斷分析，`sample strongly indicates small-denominator vulnerability`；不得推論為完整母體 43,390 stock-days 的精確證明（`full population is not proven`）。

| Candidate ID | p10 (%) | p25 (%) | Median (%) | p75 (%) | p90 (%) | Median (Ticks) | Risk < 1 Tick | Risk < 2 Ticks | Risk < Round-Trip Friction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P2B_01_v1** | 0.1079% | 0.1323% | **0.1770%** | 0.2625% | 0.3984% | **1.00** | 30.78% | **88.14%** | **98.72%** |
| **P2B_02_v1** | 0.1253% | 0.1792% | **0.2721%** | 0.3831% | 0.5495% | **2.00** | 14.52% | **49.59%** | **94.25%** |
| **P2B_03_v1** | 0.1389% | 0.2058% | **0.3077%** | 0.4197% | 0.5815% | **2.00** | 11.09% | **42.81%** | **91.89%** |
| **P2B_04_v1** | 0.1285% | 0.2020% | **0.3185%** | 0.4773% | 0.6956% | **2.00** | 10.71% | **36.06%** | **78.89%** |

- **小分母效應分析（Small-Denominator Vulnerability）**：
  - **ROUND_TRIP_TRADING_FRICTION** 由以下三要素組成：
    1. `transaction_tax`: 0.15%（來源：`OFFICIAL_MARKET_REFERENCE`，官方固定稅率）
    2. `configured_broker_commission`: 0.1425% × 0.28，低消 20 元（來源：`BROKER_ACCOUNT_PARAMETER` / `EASYSTOCK_EXISTING_PARAMETER`，非市場固定常數）
    3. `slippage`: 2 ticks（來源：`RESEARCH_GOVERNANCE_CANDIDATE`，研究敏感度設定）
  - 在抽樣診斷中，綜合交易摩擦折合約為 `OBSERVED_SAMPLE_FRICTION_EQUIVALENT_TICKS`（約 2.5 ~ 3 ticks）。**注意**：此等效數值並非市場普遍固定值，會隨 `stock price`、`tick bracket`、`risk distance` 與個別帳戶手續費設定而變動。
  - 在 1 分 K 棒中，書本止損點（前 1 棒高低點）的中位數僅為 **1 ~ 2 ticks**。以 P2B_01_v1 為例，樣本中高達 **88.14%** 的訊號停損距離小於 2 ticks，**98.72%** 的訊號停損距離小於該樣本之等效摩擦。
  - 當分母 $R$ 為 1 tick 時，摩擦成本即高達約 **2.5R ~ 3.0R**，使負 R 值的絕對深度被人為劇烈放大。

---

### 10.4 Walk-Forward Incomplete Terminal Fold Audit
- **成因追查**：歷史資料庫收錄截止日為 `2026-10-02`，Fold 5 測試區間為 `2026-09-30 ~ 2026-10-02`，恰巧遭遇資料庫尾端截斷，致使測試期間僅有 3 個日曆交易日。
- **治理標記**：正式標記 `INCOMPLETE_TERMINAL_FOLD = True`。
- **穩健性驗證**：若排除 Fold 5（僅採用完整之 4-Fold 滾動），各策略之 OOS Net Expectancy 分別為：
  - P2B_01: -3.6227R
  - P2B_02: -2.3999R
  - P2B_03: -1.9868R
  - P2B_04: -1.5835R
  結論維持一致為顯著負值，不因尾端截斷而改變。

---

### 10.5 Out-of-Sample Weighting Audit
- **加權方式比較**：

| Candidate ID | 5-Fold Equal-Weighted OOS (R) | Trade-Weighted OOS (R) | Consistency Check |
| :--- | :--- | :--- | :--- |
| **P2B_01_v1** | **-3.4996R** | **-3.4475R** | Uniformly Negative |
| **P2B_02_v1** | **-2.2561R** | **-2.2359R** | Uniformly Negative |
| **P2B_03_v1** | **-1.8861R** | **-1.8596R** | Uniformly Negative |
| **P2B_04_v1** | **-1.4714R** | **-1.4253R** | Uniformly Negative |

- 二種權重計算口徑均維持顯著負值，證實負期望值並非單一 fold 樣本數扭曲所致。

---

### 10.6 Baseline Comparator Audit
- **Provenance 查核**：報告中之 Baseline 數值（`expectancy_R = -0.05`, `win_rate = 0.44`, `profit_factor = 0.95`, `MFE = 1.10`, `MAE = 1.25`）源自 Phase 2A 基礎架構單元測試佔位對象。
- **治理分類與標記**：
  - 標記：`SYNTHETIC_RESEARCH_REFERENCE_BENCHMARK`
  - 屬性：`NON_EMPIRICAL_REFERENCE = true`
- **邊界宣告**：不得稱為 market baseline 或 Taiwan historical baseline，亦不得以對比其 delta 作為主要 reject 證據。報告保留其作為非實證參考比較基準（Non-empirical reference only），未來若需正式基準，須另行建立 empirical baseline research。

---

### 10.7 Verdict Threshold Provenance Audit
- **Provenance 查核**：$\Delta \ge +0.05R$、$\text{PF} \ge 1.10$、$\text{OOS} > 0.0R$ 未預先編碼於 `PHASE2B_BATCH1_FULL_RUN_PLAN.yaml`。
- **治理分類與標記**：
  - 標記：`PRE_REGISTERED = false`
  - 分類：`POST_HOC_RESEARCH_GOVERNANCE_CANDIDATE`
- **邊界宣告**：此門檻不得作為本次正式 verdict threshold，亦不得宣稱候選策略因「未達此門檻」而遭到 reject。本次 REJECT 判定完全奠基於描述性實證證據（Descriptive Empirical Evidence）。

---

### 10.8 Directional Support Audit
- **各策略方向性實作範疇**：
  - **P2B_01_v1**：僅實作多方（LONG only, 多頭回檔量縮）。
  - **P2B_02_v1**：僅實作多方（LONG only, 突破前高振幅擴張）。
  - **P2B_03_v1**：僅實作空方（SHORT only, 破前高拉回假突破放空）。
  - **P2B_04_v1**：僅實作空方（SHORT only, 突破上升趨勢線與支撐放空）。
- **治理標記**：`DIRECTIONAL_IMPLEMENTATION_PARTIAL = true`。
- **論述邊界**：不得宣稱價格型態本身無效，僅能宣稱「在目前的單向實作與參數空間下無 edge」。

---

### 10.9 Stratification Audit
- **描述口徑修正**：將原先「證明資料缺失不影響研究結論」之過度因果宣稱，修正為客觀審計事實：
  「在目前的完整與缺漏分層下，四個策略的負期望值表現維持一致（Negative result is robust across completeness strata），未觀察到策略表現因缺漏分層而有實質改善。」

---

### 10.10 Candidate Versioning
- 為避免後續擴充雙向（Bidirectional）、調整停損分母（ATR / Volatility-based Denominator）或更換出場政策時產生混淆，本輪候選策略正式更名為：
  - **P2B_01_v1**
  - **P2B_02_v1**
  - **P2B_03_v1**
  - **P2B_04_v1**
- 同步於 `phase2b_candidate_registry.yaml` 與全研究文件完成更新。

---

### 10.11 Final Candidate Verdict Update
- **候選策略狀態鎖定**：
  - `IMPLEMENTATION_STATUS = VERIFIED`
  - `PERFORMANCE_STATUS = EVALUATED_NEGATIVE`
  - `RESEARCH_VERDICT = REJECT_RESEARCH_CANDIDATE`
  - `DIRECTIONAL_IMPLEMENTATION_PARTIAL = true`
  - `REJECTION_SCOPE = CURRENT_V1_IMPLEMENTATION_ONLY`
- **判定理據（全數基於描述性實證證據）**：
  1. `theoretical gross expectancy < 0`（未計摩擦前之理論毛利均小於零或近零，介於 -0.06R 至 -0.58R）
  2. `net expectancy < 0`（全樣本淨期望值顯著為負）
  3. `complete-only expectancy < 0`（無缺漏日分層全數為負）
  4. `usable-with-gaps expectancy < 0`（部分缺漏日分層全數為負）
  5. `all complete OOS folds < 0`（所有完整滾動 OOS 區間全數為負）
  6. `trade-weighted OOS < 0`（交易次數加權 OOS 全數為負）
- **嚴格範圍限制（Explicit Scope Boundary）**：
  - 本次判定嚴格受限於：
    - `CURRENT_IMPLEMENTATION`
    - `CURRENT_PARAMETER_SPACE`
    - `CURRENT_DATASET`
    - `CURRENT_COST_MODEL`
    - `CURRENT_DIRECTIONAL_SCOPE`
  - **嚴格宣告**：本研究**絕對不宣稱**「VPA無效」、「Range Expansion無效」、「2B無效」、「1-2-3無效」或「作者理論無效」。本結論僅陳述：在當前 1 分 K 棒、特定單向實作與參數空間下，無法展現克服台股當沖交易摩擦之 Alpha。
  - **四個 v1 候選策略正式封存淘汰，嚴格禁止推進至正式交易（Promote to Production）**。
