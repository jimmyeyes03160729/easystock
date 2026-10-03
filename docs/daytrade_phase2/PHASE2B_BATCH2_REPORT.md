# EasyStock Phase 2B — Batch 2 研究報告
## Context / Regime / Relative Strength Filter Integrity & Smoke Validation Report

---

## 1. 執行摘要與治理邊界

本階段完成 **Phase 2B Batch 2（情境／市場狀態／相對強弱過濾條件研究）** 在啟動全量歷史回測前的 **完整數據審計、Leave-One-Out 市場代理修正、Signal Funnel 會計防護與小樣本煙霧驗證**。

### 核心原則與邊界：
* **RESEARCH_ONLY = true, INERT_BY_DEFAULT = true**
* **FILTER EXISTING SIGNALS**：本階段**完全不新增任何 Entry Pattern**，亦不修改 Batch 1 已識別的訊號特徵或時間戳。核心問題聚焦於：「在什麼市場環境下，Batch 1 已存在的訊號才值得保留？」
* **LEAVE-ONE-OUT PROXY**：市場代理指標（`RESEARCH_PROXY=true, OFFICIAL_INDEX=false`）在評估標的 $S$ 時，**嚴格自同儕截面中排除 $S$ 本身**，杜絕自身包含偏差（Self-Inclusion Bias）。
* **MISSING CONSTITUENT POLICY**：若某成分股在時間戳 $t$ 無成交 K 棒，政策為 `EXCLUDE_FROM_CURRENT_CROSS_SECTION`，嚴禁未來數據填補或未收盤 forward-fill。
* **SIGNAL FUNNEL ACCOUNTING**：建立明確訊號漏斗，保證 `RAW == SIMULATED + SUM(DROP_REASONS)` 恆等式 100% 成立，杜絕任何隱蔽拋棄（No Silent Drop）。
* **DUAL-UNIT & EFFECT DECOMPOSITION**：同時產出 R 乘數、百分比報酬率（`theoretical_return_pct`, `cost_pct`, `net_return_pct`）及 Initial Risk  ticks/pct 分佈，精準識別過濾效果屬於 `SIGNAL_EDGE_IMPROVEMENT`、`LOWER_FRICTION_SELECTION` 或 `LARGER_R_DENOMINATOR_SELECTION`。
* **本階段狀態**：所有 Blocker 全數排除，單元測試全面綠燈，狀態標定為 `IMPLEMENTATION_STATUS=VERIFIED, PERFORMANCE_STATUS=NOT_EVALUATED, READY_FOR_FULL_BATCH2_RUN=false`（等待 Full Run Plan 審查核可）。

---

## 2. 歷史成交量實體單位審計 (Historical Volume Unit Audit)

依據指示，對 raw 歷史檔案進行跨價格區間、跨年份之抽樣審計（10 檔個股、10 個交易日、共 26,139 筆成交 1 分 K）：

### 審計實證數據：
* `HISTORICAL_VOLUME_UNIT`: **LOTS**（張，即 1,000 股）
* `VOLUME_UNIT_EVIDENCE`:
  * 在 26,139 筆非零成交 K 棒中，`reported_Amount / (Close * Volume)` 之**中位數精確等於 1000.0000**。
  * `reported_Amount / (Close * Volume * 1000.0)` 之**中位數精確等於 1.000000**。
  * 抽樣實例（1101 於 2023-09-27）：`Close=32.95, Volume=445 張, Amount=14,682,350.0 TWD`，`Amount / (Close * Volume * 1000) = 1.001337`（微小偏差為分內逐筆撮合之微結構 VWAP 權重）。
* `TRADED_VALUE_SOURCE`: **ARCHIVE_AMOUNT_PRIMARY**
  * Raw archive 中自帶官方 `Amount`（成交金額 TWD）欄位，因此優先直接讀取 archive `Amount` 作為成交金額。
* `APPROXIMATED_TRADED_VALUE`: **false**（因直接使用官方 archive Amount 欄位）。

---

## 3. Leave-One-Out 市場代理與情境語意定義

* **代理指標性質**：
  * `market_proxy_type`: `UNIVERSE_EQUAL_WEIGHTED_MARKET_PROXY`
  * `is_proxy`: `true`
  * `is_official_index`: `false`
  * 嚴格禁止在報告或代碼中暗示為加權指數（TAIEX）或櫃買指數（OTC Index）。
* **Leave-One-Out 實作**：
  * 對任一標的 $S$ 計算市場參考時，同儕截面池嚴格排除 $S$。
  * 缺失值政策：若某同儕於時間戳 $t$ 無成交，即自該分鐘截面排除（`EXCLUDE_FROM_CURRENT_CROSS_SECTION`），並記錄 `constituent_count_at_t`。
* **移除模糊 VWAP 語意**：
  * 移除未具備微結構定義之「MARKET_VWAP」名稱。
  * F01 定名為純粹無歧義之 `UNIVERSE_PROXY_INTRADAY_DIRECTION`（LONG 要求同儕累積截面報酬 >= 0，SHORT 要求 <= 0）與 `UNIVERSE_PROXY_TREND_ALIGNMENT`。

---

## 4. 訊號漏斗會計審計 (Signal Funnel Accounting)

在包含高流動性與中低流動性股票（1101, 2317, 1802, 2834）跨 8 交易日之煙霧驗證中：

```
RAW_SIGNAL (541)
  │
  ├── [DROP: 36] INVALID_INITIAL_RISK (止損價與進場價相同，R分母為0)
  ├── [DROP:  1] STOP_LOSS_VIOLATION (多頭止損價高於進場價或空頭低於進場價)
  └── [DROP:  1] NO_LEGAL_EXECUTION (盤末無後續撮合棒線)
  │
SIMULATED TRADES (503)
```

* **漏斗恆等式檢驗**：
  $$\text{Raw Signals (541)} = \text{Simulated Trades (503)} + \text{Dropped Signals (38)}$$
* **恆等式狀態**：`SIGNAL_FUNNEL_IDENTITY_PASS = true`
* **隱蔽拋棄檢查**：`SILENT_DROP_COUNT = 0`，每一筆未成交訊號均保存 `signal_event_id`、`drop_stage` 與 `drop_reason`。

---

## 5. 小樣本煙霧驗證數據與效果歸因 (Smoke Sample Results)

### 驗證設定：
* **標的清單**：`1101`（水泥）、`2317`（鴻海）、`1802`（台玻，低流動性傳產）、`2834`（臺企銀，金融）共 4 檔。
* **歷史日期**：`2023-09-27` 至 `2023-10-11` 共 8 個交易日。
* **原始訊號**：541 筆（P2B_01: 384, P2B_02: 133, P2B_03: 23, P2B_04: 1），模擬成交 503 筆。

### 比較成果匯總表：

| Filter ID | Filter Family | 測試條件 | 留存率 | 留存筆數 | Delta Net R | Delta Gross R | Delta Net % | Delta Cost % | 效果歸因 (Attribution) | 狀態 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |
| **基準 (Unfiltered)** | - | 無過濾基準 | **100.00%** | 503 | `0.0000` | `0.0000` | `0.0000%` | `0.0000%` | BASELINE (Net R=-2.44, Net%=-0.92%) | BASELINE |
| **F01_REGIME** | F01_MARKET_REGIME | LOO 同儕當日累積報酬順勢 | **46.58%** | 236 | **+0.0096** | +0.0470 | **+0.0492%** | -0.0180% | `SIGNAL_EDGE_IMPROVEMENT` | VERIFIED (NOT_EVALUATED) |
| **F02_RS_15M** | F02_RELATIVE_STRENGTH | LOO 15m RS 順向/非逆向 | **70.61%** | 355 | **+0.1123** | -0.0142 | **-0.0241%** | -0.0105% | `NEUTRAL_OR_DEGRADED` | VERIFIED (NOT_EVALUATED) |
| **F03_SECTOR** | F03_SECTOR_STRENGTH | 類股強弱審計 | **100.00%** | 503 | `0.0000` | `0.0000` | `0.0000%` | `0.0000%` | `DATA_INSUFFICIENT` | NOT_EVALUATED_DATA_INSUFFICIENT |
| **F04_HTF_5M** | F04_HIGHER_TIMEFRAME | 前根 5m 閉合棒順勢 | **83.18%** | 416 | **-0.0733** | -0.0061 | **-0.0097%** | +0.0095% | `NEUTRAL_OR_DEGRADED` | VERIFIED (NOT_EVALUATED) |
| **F05_LIQUIDITY** | F05_LIQUIDITY_POOL | 滾動 30m 成交額 >= 10M | **87.06%** | 445 | **+0.0561** | -0.0091 | **+0.0239%** | -0.0270% | `NEUTRAL_OR_DEGRADED` | VERIFIED (NOT_EVALUATED) |

> [!IMPORTANT]
> **F05 區分度實證（Discrimination Observed）**：
> 加入中低流動性標的後，F05 留存率降至 **87.06%**，同時觀察到明確的 `KEEP` 與 `DROP`，證實流動性門檻過濾路徑真實起效（`F05_FILTER_DISCRIMINATION_OBSERVED = true`）。
> 
> **F01 訊號邊際改善（Signal Edge Improvement）**：
> Leave-One-Out 同儕方向過濾將訊號收斂至 **46.58%**（落在 50% 階梯），其 Theoretical Gross R（+0.0470）與 Net Return %（+0.0492%）均同步增長，歸因為 `SIGNAL_EDGE_IMPROVEMENT`。
> 
> **效能術語鎖定**：
> 煙霧驗證僅證明 Pipeline 正確，所有過濾條件之效能狀態嚴格標定為 `PERFORMANCE_STATUS = NOT_EVALUATED`，絕不推論為生產環境 Alpha。

---

## 6. 事前全量回測規劃凍結與範疇治理 (Full Run Pre-Registration & Scope Freeze)

已於 `docs/daytrade_phase2/PHASE2B_BATCH2_FULL_RUN_PLAN.yaml` 及 `docs/daytrade_phase2/phase2b_batch2_filter_registry.yaml` 完成最後審計並全面凍結：
* **BASELINE_SHA**: `b351e6b2c32ad9f19c8375d99c19423ab31a0ee8`
* **FINAL_FULL_RUN_PLAN_HASH**: `7c5999c2ca9992670dcafd8cb1caaf3c70642d9502435fffd732640855e9fda5`
* **FINAL_FILTER_REGISTRY_HASH**: `7bcd2e113b28f6c0bb8dd08d37f952289c992f3a05ade5fa441179571b272b60`
* **FREEZE**: `true`（YAML 內部已徹底移除自我引用 Hash 欄位，徹底杜絕自循環依賴）

### 統計治理範疇明確宣告 (Scope Governance Declaration)：
1. **CONFIRMATORY_SCOPE**（驗證性統計範疇）：
   * 單一過濾器：`F01_MARKET_REGIME`、`F02_RELATIVE_STRENGTH`、`F04_HIGHER_TIMEFRAME_CONTEXT`、`F05_LIQUIDITY_CANDIDATE_POOL`。
   * 此四項為正式歷史全量回測中具備排名與檢定資格之候選者。
2. **DATA_INSUFFICIENT_SCOPE**（數據不足範疇）：
   * `F03_SECTOR_STRENGTH`：因缺乏 Point-in-time 歷史類股映射與類股指數時序，不具備排名與 promotion 資格，回測中保留 unfiltered baseline。
3. **PAIRWISE_SCOPE: EXPLORATORY_POST_SMOKE**（探索性統計範疇）：
   * 包含事前登記之 4 組配對：`PAIR_01_F01_F02`、`PAIR_02_F01_F04`、`PAIR_03_F01_F05`、`PAIR_04_F02_F05`。
   * **嚴格統計反挑選規則（Anti-Cherry-Picking Mandate）**：
     * 配對過濾器僅為探索性研究性質，**不得與單一過濾器視為同等 Confirmatory**。
     * 若單一過濾器在全量回測中評估均為負向（Negative Edge），**嚴格禁止利用配對組合挑選局部結果作為策略晉級（Strategy Promotion）或生產化（Production）之理由**。
4. **禁止事項（Prohibitions）**：
   * 嚴禁五大 Filter 笛卡兒積搜尋（Cartesian Product Mining）。
   * 嚴禁事前未註冊過濾條件挖掘（Unregistered Filter Mining）。
   * 嚴禁樣本外調參（OOS Tuning）。
   * 嚴禁推廣至生產環境（Promote to Production）。

---

## 7. 百分比報酬與交易摩擦會計恆等式 (Percentage Return Accounting Identity)

為確保 Trade-level 與 Aggregate 維度的績效計算具備嚴格的加總封閉性（Linear Accounting Identity），已於 `batch2_filter_runner.py` 與測試套件中落實精確拆解：

### 會計恆等式定義：
1. **交易層級（Trade-Level）**：
   $$\text{net\_return\_pct} = \text{theoretical\_return\_pct} - \text{total\_trading\_friction\_pct}$$
   其中交易摩擦（Round-Trip Trading Friction）嚴格拆解為三大組成：
   $$\text{total\_trading\_friction\_pct} = \text{slippage\_pct} + \text{commission\_pct} + \text{tax\_pct}$$
   每一筆 Trade 均在程式內透過 `assert abs(friction_pct - (slip_pct + comm_pct + tx_pct)) < 1e-7` 與 `assert abs(net_pct - (theo_pct - friction_pct)) < 1e-7` 進行動態即時斷言。
2. **群體比較層級（Filter Delta Level）**：
   在相同樣本空間比對 Unfiltered 與 Filtered 之差異時，變動量亦嚴格滿足：
   $$\Delta \text{net\_return\_pct} = \Delta \text{theoretical\_return\_pct} - \Delta \text{total\_trading\_friction\_pct}$$
   $$\Delta \text{total\_trading\_friction\_pct} = \Delta \text{slippage\_pct} + \Delta \text{commission\_pct} + \Delta \text{tax\_pct}$$
3. **回歸測試覆蓋**：
   `TestPercentageReturnAccountingIdentity` 包含多頭、空頭與過濾 Delta 之驗證，全數通過。

---

## 8. Git 狀態與本機／VM 檔案一致性審計 (Git State & Worktree Verification)

針對先前報告「Clean / Uncommitted」語意進行精準釐清：
* 由於 Batch 2 為未封版之研究檔案，尚未執行 `git commit` 與 `git push`，因此 Worktree 存在未暫存（uncommitted）變更乃正常預期狀態。
* **精準工作目錄狀態**：
  * `LOCAL_HEAD`: `b351e6b2c32ad9f19c8375d99c19423ab31a0ee8` (main)
  * `VM_HEAD`: `b351e6b2c32ad9f19c8375d99c19423ab31a0ee8` (main)
  * `LOCAL_WORKTREE_STATUS`: `UNCOMMITTED_CHANGES_PRESENT`（1 modified: `__init__.py`, 10 untracked batch 2 files）
  * `VM_WORKTREE_STATUS`: `UNCOMMITTED_CHANGES_PRESENT`（與本地完全同步鏡像）
* **測試套件狀態**：
  * 本地 Phase 2B Batch 2 測試：**13 passed**
  * 本地 Phase 2 + Phase 1 核心測試：**84 passed, 13 subtests passed**
  * CI / VM 全量回歸測試：**300 passed, 48 subtests passed**
  * **當前狀態**：未 commit、未 push、未啟動 Full Run，待最後審查授權。

