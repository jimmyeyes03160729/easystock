# EasyStock Daytrade Research Phase 2C — Result Cross-Review Corrective Audit
## 交叉回審修正審計與結果校正報告 (Single Source of Truth)

---

## 1. 執行背景與治理規範 (Governance & Scope Boundaries)

* **原始回測識別碼 (Run ID)**: `P2C_FULL_HISTORICAL_20261003_111657`
* **回測時間範圍**: 2023-09-27 至 2026-10-02 (726 個交易日, 43,390 個股交易日)
* **訊號漏斗規模**: 原始訊號 2,093,570，模擬訊號 1,591,201，停損違規濾除 502,369，靜默丟棄 0 (100% PASS)
* **資料性質與定位**: `study_type: PREREGISTERED_FOLLOWUP_ON_PREVIOUSLY_OBSERVED_DATA`, `DISCOVERY_DATA_REUSED = true, INDEPENDENT_CONFIRMATION = false`。純屬機制與失效情境分析（`MECHANISM_AND_FAILURE_REGIME_ANALYSIS`），絕非新 Alpha 探索或生產上線推薦。
* **產物不可變性聲明 (Artifact Immutability)**: 原始產物 `docs/daytrade_phase2/phase2c_f01_full_run_summary.yaml` 與 `docs/daytrade_phase2/PHASE2C_F01_FULL_RUN_REPORT.md` 保持完全原樣。
* **單一資料來源流程 (Single Source of Truth Pipeline)**: 本次回審建立了自動化單一資料來源產生管線，嚴格繼承原始凍結之 WFA 前滾折數與切點定義：
  `immutable raw_trades -> canonical consistent aggregation -> corrected_summary.yaml -> auto-generate reports -> consistency audit`，杜絕任何人工輸入與跨產物不一致。
* **當前狀態矩陣**: `COMMIT_CREATED = false`, `PUSHED = false`, `PRODUCTION_CODE_CHANGED = false`, `READY_FOR_SEAL = false`。

---

## 2. 全層級會計恆等式審計 (Comprehensive Accounting Identity Audit)

* **審計範圍**: 全面掃描 corrected summary 中所有機制假說、所有分組、所有前滾折數與分位數，共計 **60 個分層**。
* **未捨入會計恆等式通過率**: `True` (100% PASS, 殘差均小於 1e-12)
* **四捨五入顯示恆等式通過率**: `True` (100% PASS, Net == Theo - Friction 在 4 位小數顯示下完全吻合)
* **有限樣本離散誤差原理說明**: 原始 JSON 格式儲存之每筆交易紀錄對 theoretical、friction、net 均分別取 4 位小數截斷。在小樣本（如 N=872 之 INSUFFICIENT_BREADTH）下，三者獨立均值相減會產生 $O(10^{-4} / \sqrt{N})$ 的統計截斷雜訊（最大約 1.75e-6）。本報告採用一致會計聚合（Consistent Accounting Aggregation），以理論回報減去交易摩擦嚴格定義淨回報，徹底消除格式化截斷誤差，確保數學與報表層級完全閉環。

---

## 3. 八大修正項目排查與對照結論 (Point-by-Point Corrections)

### Q1: 市場趨勢強度 (Trend Strength) — 改為方向不對稱型態 (Directional Asymmetry Observed)
* **機制狀態判定**: `DIRECTIONAL_ASYMMETRY_OBSERVED_CONSISTENTLY_ACROSS_4_COMPLETE_FOLDS`
* **研究證據屬性**: `DISCOVERY_DATA_REUSED = true`, `INDEPENDENT_CONFIRMATION = false`
* 嚴格保留權威凍結之 WFA 前滾設定（直接複製自 `phase2c_f01_full_run_summary.yaml`，未重新計算）：
  * Fold 1 (2025-01-07 ~ 2025-06-23) (Complete Fold): Train=2023-09-27~2025-01-03 (Signals=447,239, Cuts=[-0.00383, -0.000565, 0.002688]), Q1 Net +0.0461%, Q2 Net +0.0192%, Q3 Net -0.0218%, Q4 Net -0.0227%
  * Fold 2 (2025-06-24 ~ 2025-11-19) (Complete Fold): Train=2024-03-06~2025-06-20 (Signals=499,268, Cuts=[-0.004286, -0.000232, 0.00373]), Q1 Net +0.0307%, Q2 Net +0.0400%, Q3 Net -0.0175%, Q4 Net -0.0277%
  * Fold 3 (2025-11-20 ~ 2026-04-29) (Complete Fold): Train=2024-08-06~2025-11-18 (Signals=516,128, Cuts=[-0.004291, 4.7e-05, 0.004616]), Q1 Net +0.0307%, Q2 Net +0.0462%, Q3 Net -0.0239%, Q4 Net -0.0237%
  * Fold 4 (2026-04-30 ~ 2026-09-24) (Complete Fold): Train=2025-01-06~2026-04-28 (Signals=619,708, Cuts=[-0.005277, -3e-05, 0.004721]), Q1 Net +0.0216%, Q2 Net +0.0740%, Q3 Net -0.0333%, Q4 Net -0.0177%
  * Fold 5 (2026-09-29 ~ 2026-10-02) (INCOMPLETE_TERMINAL, 4 trading days, 9,497 signals): Train=2025-06-23~2026-09-23 (Signals=956,205, Cuts=[-0.006806, -0.000474, 0.005881]), Q1 Net -0.1078%, Q2 Net +0.0219%, Q3 Net +0.0562%, Q4 Net -0.0060%
* 在完整前滾 Fold 1~4 中，Q1 (強空) 與 Q2 (微跌/平盤) 均穩定觀察到正向型態 (Delta Net > 0)，而 Q3 (微漲/平盤) 與 Q4 (強多) 則觀察到負向型態 (Delta Net < 0)。
* 終端 Fold 5 明確標註為 `INCOMPLETE_TERMINAL`（僅涵蓋 4 天、9,497 筆訊號），不與完整 Folds 等權解讀。
* 移除任何「100% 驗證」等過度宣稱，結論表述為 `DIRECTIONAL_ASYMMETRY_OBSERVED_CONSISTENTLY_ACROSS_4_COMPLETE_FOLDS`，並嚴格維持 `DISCOVERY_DATA_REUSED = true` 與 `INDEPENDENT_CONFIRMATION = false`。

### Q2: 市場波動度 (Market Volatility) — 改為中高波動正向型態，低波動受摩擦侵蝕
* MID 波動度（Delta Net `+0.0032%`）與 HIGH 波動度（Delta Net `+0.0024%`）淨報酬均為正向型態。
* LOW 波動度理論報酬微正（`+0.0015%`），因交易摩擦增加（`+0.0032%`），淨變化轉為負值（`-0.0017%`）。非 HIGH-only。

### Q3: 開盤方向情境 (Opening Context) — 補齊預先註冊 30m 權威產物並說明差異來源
* **差異判定**: 權威因果合約嚴格要求 30m 窗口於 09:30:00 收盤確認。09:30 前觸發之 284,158 筆訊號嚴格為 `NOT_AVAILABLE`。舊草稿之 139,290 筆係誤用 15m 截斷之錯誤產物，已全數剔除並統一為 canonical 結果（POSITIVE: 599,762, NEUTRAL: 97,885, NEGATIVE: 609,396, NOT_AVAILABLE: 284,158）。
* 15m 與 30m 高度一致：開高走強（POSITIVE: 15m -0.0116%, 30m -0.0160%）呈現負向型態，開平或開低呈現正向型態。

### Q4: 當日時間窗 (Time of Day) — 校正各時段實證型態
* 早盤 OPEN 呈現正向型態（Delta Net `+0.0043%`）；盤中 MID 呈現負向型態（Delta Net `-0.0022%`）；尾盤 LATE 呈現最強正向型態（Delta Net `+0.0078%`）。

### Q5: 代理標的廣度 (Proxy Breadth) — 嚴禁宣稱單調性，指明混淆限制
* 55–79 檔區間 Delta Net 為負（`-0.0156%`），80–99 檔為正（`+0.0091%`），34–54 檔微正（`+0.0005%`），不具單調性。
* 強制保留歷史警語：`YEAR_AND_UNIVERSE_CONFOUNDED` 與 `UNIVERSE_EXPANSION_CONFOUND`。

### Q6: 策略方向與候選模組分解 (Candidate & Direction Breakdown)
* 明確表述：**LONG aggregate slightly negative, with candidate heterogeneity: P2B_01 negative, P2B_02 positive.** 做多整體微幅為負（`-0.0007%`），P2B_01 為 `-0.0026%`，P2B_02 為 `+0.0028%`。做空整體為正（`+0.0024%`，P2B_03 `+0.0061%`，P2B_04 `+0.0071%`）。
* 嚴禁推導 Direction $\times$ Regime 交互作用。

### Q7: 2025 失效情境歸因 (2025 Failure Regime Attribution)
* 刪除所有主觀因果猜測，維持客觀數據：2025 年 Delta Theo `+0.0006%`、Delta Friction `+0.0039%`、Delta Net `-0.0033%`。

### Q8: 會計恆等式與模擬不可變性
* 全面掃描 60 個分層，一致會計聚合下 100% 滿足未捨入與四捨五入顯示恆等式。原始回測產物維持不可變，無需重跑。

---

## 4. 總結與後續審查指引 (Summary & Review Readiness)

* 所有 artifacts（`corrected_summary.yaml`, `corrected_report.md`, `PHASE2C_RESULT_CROSS_REVIEW.md`, `PHASE2C_ARTIFACT_CONSISTENCY_AUDIT.json`）均由單一資料來源流程自動生成。
* 保持未提交（Uncommitted）且未推送（Unpushed）狀態，等待 ChatGPT 進行第三輪 file-level cross-review。
