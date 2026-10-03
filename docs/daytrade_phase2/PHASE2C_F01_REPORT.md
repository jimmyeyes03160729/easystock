# EasyStock Phase 2C — F01 Market Context Follow-up Study
## Research Design Freeze & Smoke Verification Report

---

## 1. 研究設計凍結與檔案雜湊 (Research Design Freeze & Artifact Hashes)

本研究所有假說分層、未來驗證契約與完整執行計畫已正式凍結。若在 Full Historical Run 執行前任何檔案發生任何位元組變動，則必須立即觸發 `ABORT_FULL_RUN = true`。

* **BASELINE_SHA**: `ac5b660fc2b4d39f9e92b73a2a09584bfec0cd00`
* **FROZEN**: `true`

### 核心研究契約 SHA256 雜湊值（LF 規範化）：
```
HYPOTHESIS_REGISTRY_HASH:           ed0063f20a7468e5deb4a1c61943f6585bd65036e0e1e045a2290597bfcb612e
FUTURE_CONFIRMATION_CONTRACT_HASH:  7693656abd9ea3b0a109888ed14517476c950bc68a9f82ee42e04ae3383d3c46
FULL_RUN_PLAN_HASH:                 3524f1ad6ed79cc6c14f1c0cdae0ee294527bf81e84699bdad76b587900baeb9
```

---

## 2. 研究治理與資料邊界規範 (Research Governance & Boundaries)

* **RESEARCH_ONLY = true, INERT_BY_DEFAULT = true**
* **資料性質標記**：`DISCOVERY_DATA_REUSED = true, INDEPENDENT_CONFIRMATION = false`
* **研究定位**：`study_type = PREREGISTERED_FOLLOWUP_ON_PREVIOUSLY_OBSERVED_DATA`
* **研究目的**：`purpose = MECHANISM_AND_FAILURE_REGIME_ANALYSIS`
* **明確禁止事項**：
  * 不是策略最佳化（No strategy optimization）
  * 不是尋找新 Alpha（No new alpha discovery）
  * 不得晉升生產環境（No production promotion）
* **F01 狀態**：維持 Phase 2B 凍結結論 `FILTER_IMPROVES_RESEARCH_SIGNAL`，`PRODUCTION_READY = false`。

---

## 3. 機制假說因果定義與防線規格 (Mechanism Hypotheses & Invariants)

### H01: 市場趨勢強度 (Trend Strength)
* **分層**：`Q1`, `Q2`, `Q3`, `Q4`
* **分位數治理規範**：`QUANTILE_TRAIN_ONLY = true`。分位數切分點嚴格僅由各 Walk-Forward Train 折計算並凍結，OOS 評估時強制套用 Train 凍結邊界。嚴禁使用全樣本分位數回套並宣稱為 OOS。全樣本統計僅得標記為 `FULL_SAMPLE_DESCRIPTIVE_ONLY`。

### H02: 市場波動度 (Market Volatility)
* **分層**：`LOW`, `MID`, `HIGH`
* **因果防線**：嚴格僅取 signal_time 前之已完成 1m 棒。嚴禁全日震幅、全日高低價或任何未來棒。

### H03: 開盤方向 (Opening Direction)
* **右邊界因果語意**：歷史 K 棒時間戳記為右邊界（Right-Edge Timestamp，即 Bar Close）。
  * 15m 開盤視窗：`[09:00, 09:15)`，嚴格於 `signal_time >= 09:15:00` 方可使用。訊號於 `09:14:59`（或 1m 精度之 `09:14`）嚴格標為 `NOT_AVAILABLE`（值為 None）。
  * 30m 開盤視窗：`[09:00, 09:30)`，嚴格於 `signal_time >= 09:30:00` 方可使用。訊號於 `09:29:59`（或 1m 精度之 `09:29`）嚴格標為 `NOT_AVAILABLE`（值為 None）。
* **預註冊分層標籤**：
  * `OPENING_DIRECTION_POSITIVE`
  * `OPENING_DIRECTION_NEUTRAL`
  * `OPENING_DIRECTION_NEGATIVE`
  * `NOT_AVAILABLE`

### H04: 交易時段 (Time of Day)
* **半開區間定義**：
  * `OPEN`: `[09:00, 10:00)`
  * `MID`:  `[10:00, 12:00)`
  * `LATE`: `[12:00, 13:30]`（13:30 收盤棒依歷史右邊界語意納入）
* **不變量驗證**：強制驗證 `TIME_BUCKET_MEMBERSHIP_COUNT == 1`，每個交易訊號恰好歸屬一個時段。

### H05: 代理標的廣度 (Proxy Breadth)
* **分層與邊界政策**：
  * `BREADTH_34_54`: 舊版約 55 檔歷史資料日。
  * `BREADTH_55_79`: 過渡期資料日。
  * `BREADTH_80_99`: 擴充 100 檔歷史資料日。
  * `INSUFFICIENT_BREADTH`: 活躍同儕數 `< 34`。明確標記此狀態，**嚴格禁止靜默丟棄（Silent Drop）**。
* **物理防線**：若 `peer_count > 99` 或 `< 0`，立即拋出 `CausalityOrMetadataFailure`（`CAUSALITY_OR_METADATA_FAILURE`）並中斷執行。

### H06: 候選策略與方向 (Candidate Direction)
* **方向分層**：`LONG`, `SHORT`
* **候選策略分層**：`P2B_01_v1`, `P2B_02_v1`, `P2B_03_v1`, `P2B_04_v1`
* **凍結規則**：策略定義完全沿用 Phase 2B 凍結邏輯，不得調整參數。

### H07: 2025 年失效日特徵診斷 (Failure Regime Days)
* **分層標籤**：
  * `IMPROVED_DAY`: 當日 F01 理論報酬 Delta > 0
  * `DEGRADED_DAY`: 當日 F01 理論報酬 Delta <= 0
* **嚴格治理防線**：標記為 `DESCRIPTIVE_POST_OUTCOME_CLASSIFICATION = true`。本分層純屬事後描述性診斷，**嚴格禁止進入盤中即時決策或過濾器決策路徑**，亦不得宣稱為「可預測之市場機制」。

---

## 4. 探索與搜尋防線 (Search & Robustness Governance)

* **ONE_DIMENSIONAL_ONLY = true**：第一輪 Full Historical Run 僅執行一維機制分層（如 `F01 x H01`, `F01 x H02` ...）。
* **CARTESIAN_SEARCH_ALLOWED = false**：嚴格禁止大型笛卡爾積參數搜尋（如 `H01 x H02 x H03 x H05`）。
* **允許之穩健性交叉報表**：僅限 `year x hypothesis_stratum` 與 `candidate x hypothesis_stratum`。
* **禁止 Cherry-picking**：嚴格禁止在觀察結果後刪除分層、合併分層、新增門檻、移動門檻或建立新過濾器。

---

## 5. 未來獨立驗證契約（Future Independent Confirmation Contract）

* **驗證起點**：`AFTER_2026_10_02`（嚴格於 2026-10-05 TWSE 次一交易日開始之全新資料）。
* **凍結評估週期**：`EVALUATION_HORIZON = 60_TRADING_DAYS`，狀態為 `RESEARCH_GOVERNANCE_CANDIDATE`。
* **反偷窺規則**：`NO_PEEKING_BEFORE_EVALUATION = true`。必須在檢視任何成果前固定 60 天視窗，禁止隨機走走停停（Optional Stopping）。
* **樣本不足備援**：若 60 個交易日後樣本數不足 `minimum_signal_count` (500)，僅能標記 `INSUFFICIENT_CONFIRMATION_SAMPLE`，不得任意延長視窗至結果好轉。
* **主要終點指標 (Primary Endpoints)**：
  * `PRIMARY_1`: `delta_theoretical_return_pct`
  * `PRIMARY_2`: `delta_net_return_pct`
  * 嚴格禁止若理論報酬不佳即切換至次要指標（如勝率、盈虧比或 R 期望值）。
* **F01 定義凍結**：未來驗證必須 100% 沿用 Phase 2B 凍結邏輯（`F01_v1`）。嚴格禁止因 Phase 2C 發現產生 `F01_v2` 並套用本契約。

---

## 6. 結果用語限制 (Result Language Restrictions)

* **本次 Historical Follow-up 允許用語**：
  * `MECHANISM_PATTERN_OBSERVED`
  * `MECHANISM_PATTERN_NOT_OBSERVED`
  * `FAILURE_REGIME_OBSERVED`
  * `NO_CLEAR_MECHANISM`
  * `DATA_INSUFFICIENT`
* **嚴格禁用用語**：
  * `VALIDATED_ALPHA`
  * `INDEPENDENT_CONFIRMATION`
  * `PROVEN_REGIME`
  * `PRODUCTION_READY`

---

## 7. Smoke 回測驗證成果（Implementation Verification Smoke）

* **樣本**：6 檔標的（1101, 1301, 2002, 2317, 2330, 2454）、10 個交易日（2025 年 5 天、2026 年 5 天）
* **訊號漏斗**：
  * Raw: 3,135
  * Simulated: 2,555
  * Dropped: 580（全部為 `STOP_LOSS_VIOLATION`，停損價違反合法進場）
  * Silent Drop: 0（**漏斗會計恆等式 100% 通過**）
* **會計恆等式**：`Net Return % == Theoretical Return % - Trading Friction %` 誤差 `< 1e-7`，通過。
* **全分層皆正常產出**：H01 (Q1~Q4), H02 (LOW, MID, HIGH), H03 (POSITIVE, NEUTRAL, NEGATIVE, NOT_AVAILABLE), H04 (OPEN, MID, LATE), H05 (BREADTH_34_54, 55_79, 80_99, INSUFFICIENT_BREADTH), H06 (LONG, SHORT, P2B_01~04), H07 (IMPROVED_DAY, DEGRADED_DAY)。

---
*報告產出時間：`2026-10-03T11:05:00+08:00`*