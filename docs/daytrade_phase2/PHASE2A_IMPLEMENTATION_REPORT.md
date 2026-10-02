# EasyStock Daytrade Research Phase 2A — Implementation Report

## 1. Executive Summary

Phase 2A establishes the **Research Foundation** for EasyStock day-trading research. It provides rigorous mathematical, causal, and accounting primitives required for research evaluation without altering or enabling any live or paper trading functionality.

- **RESEARCH_ONLY**: `True`
- **INERT_BY_DEFAULT**: `True`
- **Production Impact**: `UNCHANGED` (Zero production imports or modifications)

---

## 2. Resolution of 4 Major Cross-Review Issues

### Major 1: Slippage Single Source of Truth
- **Problem**: Previously, `ExecutionClock` incorporated slippage into fill prices, while transaction cost models independently subtracted slippage, causing double counting.
- **Resolution**:
  - `actual_entry_price` and `actual_exit_price` embody actual simulated execution fills.
  - `slippage_cost` is explicitly derived as `(actual_entry - theoretical_entry) * qty + (theoretical_exit - actual_exit) * qty` (for long).
  - Gross PnL from actual execution is `(actual_exit - actual_entry) * qty`.
  - Net PnL is `Gross PnL (actual) - commission - tax`.
  - Mathematical identity verified: `Net PnL == Gross PnL (theoretical) - slippage_cost - commission - tax`.
  - Slippage is strictly never deducted twice.

### Major 2: Full Causal Order Enforcement
- **Problem**: Prior implementation only checked `feature_time <= decision_time`, allowing ordering anomalies between signal time, decision readiness, and execution.
- **Resolution**:
  - Full strict chronological ordering is enforced:
    $$\text{feature\_timestamp} \le \text{signal\_time} \le \text{decision\_available\_time} < \text{execution\_time}$$
  - Dedicated exception `CausalityViolationError` is thrown on any anomaly:
    - `feature_after_signal_rejected`
    - `signal_after_decision_rejected`
    - `execution_equal_decision_rejected`
    - `execution_before_decision_rejected`

### Major 3: Strict Bar Time Semantics
- **Problem**: Conflation of bar start, bar end, and tick timestamps. Evaluating legality at bar close while filling at that bar's open price.
- **Resolution**:
  - `MarketBar` requires explicit `bar_open_time` and `bar_close_time` (`bar_open_time < bar_close_time`).
  - Bar open execution requires `bar_open_time >= earliest_legal_execution_time`.
  - Checking legality at `bar_close_time` and executing at `bar.open` of that same bar is strictly rejected.
  - Tick-level data is encapsulated in a distinct `TickExecutionPoint`.
  - Tested: Signal at 09:30:00 (+2s) executes on 09:31:00 open; signal at 09:30:59 (+2s = 09:31:01) has crossed the minute boundary and must wait for 09:32:00 open.

### Major 4: Event-Based Purge & Embargo
- **Problem**: Index-based walk-forward splitting fails to prevent forward-label overlap between train and test windows.
- **Resolution**:
  - Legacy index splitter renamed to `IndexWalkForwardSplitter` with explicit attribute `NOT_SAFE_FOR_OVERLAPPING_FORWARD_LABELS = True`.
  - Created `EventWalkForwardSplitter`:
    - Tracks `sample_time`, `label_start_time`, and `label_end_time`.
    - Purges any training sample whose label extends into the test interval (`label_end_time >= test_start_time`).
    - Enforces temporal quarantine `embargo_duration` for samples post-test.

---

## 3. Dataset Semantics & Risk Integrity

- **Explicit Sizing**:
  - Position size is recorded via `quantity` (shares) rather than arbitrary defaults.
  - Pre-trade risk recorded via `initial_risk_per_share` and `initial_risk_amount`.
  - Zero-risk trades (`initial_risk_per_share <= 0`) are strictly rejected.
  - Inconsistent stop losses (Long stop $\ge$ entry; Short stop $\le$ entry) are strictly rejected.
- **MFE / MAE Decomposed**:
  - `mfe_price`, `mae_price` (TWD)
  - `mfe_pct`, `mae_pct` (%)
  - `mfe_R`, `mae_R` (R-multiples)

---

## 4. Parameter Provenance & Cost Governance

- **Canonical V2 Sealed**:
  - No new authors or unverified texts introduced.
  - `PARAM_PB_VOL_DECAY` correctly attributed to Anna Coulling, Chapter 7 (Chapter 5 rejected).
  - Research grids `[0.35, 0.45, 0.50]` and `[1.2, 1.5, 1.8]` categorized as `AI_QUANTIZED` with origin `Knowledge V2 Research Parameter Candidate`.
- **Cost Parameter Governance**:
  - `broker_fee_rate` (0.001425) & `daytrade_tax_rate` (0.0015): `SOURCE_PARAMETER`
  - `broker_discount` (0.28) & `minimum_fee` (20 TWD): `EASYSTOCK_EXISTING_PARAMETER`
  - `slippage_grid`: `RESEARCH_GOVERNANCE_CANDIDATE`

---

## 5. Metrics & Research-Only Verdicts

- **SQN (System Quality Number)**:
  - Calculated strictly as an exploratory metric: $\text{SQN} = \sqrt{N} \cdot \frac{\text{Expectancy}_R}{\text{Std}_R}$.
  - Rules like `SQN > 2 = PASS` are strictly forbidden.
- **Research Verdicts**:
  - Only allowed verdicts: `KEEP_FOR_MORE_RESEARCH`, `REJECT_RESEARCH_CANDIDATE`, `DATA_INSUFFICIENT`, `CAUSALITY_FAILURE`, `EXECUTION_INVALID`.
  - `PROMOTE_TO_PRODUCTION` is forbidden and raises an exception.
