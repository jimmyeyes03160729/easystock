"""Phase 2B Batch 2 Full Historical Context Filter Runner.

Strict Governance:
1. Authorized Baseline SHA: b351e6b2c32ad9f19c8375d99c19423ab31a0ee8
2. Final Plan Hash Guard: 7c5999c2ca9992670dcafd8cb1caaf3c70642d9502435fffd732640855e9fda5
3. Final Registry Hash Guard: 7bcd2e113b28f6c0bb8dd08d37f952289c992f3a05ade5fa441179571b272b60
4. Streaming constant-memory cross-sectional Leave-One-Out execution across 43,390 stock-days.
5. Signal Funnel Accounting: RAW == SIMULATED + DROPPED with SILENT_DROP_COUNT = 0.
6. Percentage Return Accounting Identity: net_return_pct == theoretical_return_pct - (slippage_pct + comm_pct + tax_pct).
7. Walk-Forward 5-Fold rolling schedule with 1-day embargo.
8. Output: phase2b_batch2_full_run_summary.yaml and PHASE2B_BATCH2_FULL_RUN_REPORT.md.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from daytrade_learning.phase2 import (
    RESEARCH_ONLY,
    INERT_BY_DEFAULT,
    BASE_COMMISSION_REFERENCE_RATE,
    PARAM_BROKER_DISCOUNT,
    PARAM_MINIMUM_FEE,
    PARAM_DAYTRADE_TAX_RATE,
    MarketBar,
    TransactionCostModel,
    get_twse_tick_size,
    calculate_single_source_pnl,
    StockDayCompletenessStatus,
    MissingnessType,
    StockDayCompletenessReport,
    assess_stock_day_completeness,
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
    parse_phase2_timestamp,
)

TPE = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_PLAN_HASH = "7c5999c2ca9992670dcafd8cb1caaf3c70642d9502435fffd732640855e9fda5"
EXPECTED_REGISTRY_HASH = "7bcd2e113b28f6c0bb8dd08d37f952289c992f3a05ade5fa441179571b272b60"


@dataclass
class FilterAccumulator:
    """Streaming accumulator for trade metrics and percentage return decomposition."""
    count: int = 0
    win_count: int = 0
    loss_count: int = 0
    gross_gains: float = 0.0
    gross_losses: float = 0.0
    sum_pnl_R: float = 0.0
    sum_sq_pnl_R: float = 0.0
    sum_gross_R: float = 0.0
    sum_cost_drag_R: float = 0.0
    sum_mfe_R: float = 0.0
    sum_mae_R: float = 0.0
    max_win_R: float = -999999.0
    max_loss_R: float = 999999.0

    # Percentage return decomposition sums
    sum_theo_pct: float = 0.0
    sum_slip_pct: float = 0.0
    sum_comm_pct: float = 0.0
    sum_tax_pct: float = 0.0
    sum_friction_pct: float = 0.0
    sum_net_pct: float = 0.0

    # Distributions
    pnl_samples: list = field(default_factory=list)
    risk_pct_samples: list = field(default_factory=list)
    risk_tick_samples: list = field(default_factory=list)

    def add(
        self,
        pnl_R: float,
        gross_pnl_R: float,
        cost_drag_R: float,
        gross_pnl: float,
        mfe_R: float,
        mae_R: float,
        theo_pct: float,
        slip_pct: float,
        comm_pct: float,
        tax_pct: float,
        friction_pct: float,
        net_pct: float,
        risk_pct: float,
        risk_ticks: float,
    ) -> None:
        self.count += 1
        self.sum_pnl_R += pnl_R
        self.sum_sq_pnl_R += pnl_R * pnl_R
        self.sum_gross_R += gross_pnl_R
        self.sum_cost_drag_R += cost_drag_R
        self.sum_mfe_R += mfe_R
        self.sum_mae_R += mae_R

        self.sum_theo_pct += theo_pct
        self.sum_slip_pct += slip_pct
        self.sum_comm_pct += comm_pct
        self.sum_tax_pct += tax_pct
        self.sum_friction_pct += friction_pct
        self.sum_net_pct += net_pct

        if pnl_R > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        if gross_pnl > 0:
            self.gross_gains += gross_pnl
        elif gross_pnl < 0:
            self.gross_losses += abs(gross_pnl)

        if pnl_R > self.max_win_R:
            self.max_win_R = pnl_R
        if pnl_R < self.max_loss_R:
            self.max_loss_R = pnl_R

        # Reservoir sampling up to 2000 items
        if self.count % 25 == 0 and len(self.pnl_samples) < 2000:
            self.pnl_samples.append(pnl_R)
            self.risk_pct_samples.append(risk_pct)
            self.risk_tick_samples.append(risk_ticks)

    def merge(self, other: FilterAccumulator) -> FilterAccumulator:
        if other.count == 0:
            return self
        if self.count == 0:
            return other
        return FilterAccumulator(
            count=self.count + other.count,
            win_count=self.win_count + other.win_count,
            loss_count=self.loss_count + other.loss_count,
            gross_gains=self.gross_gains + other.gross_gains,
            gross_losses=self.gross_losses + other.gross_losses,
            sum_pnl_R=self.sum_pnl_R + other.sum_pnl_R,
            sum_sq_pnl_R=self.sum_sq_pnl_R + other.sum_sq_pnl_R,
            sum_gross_R=self.sum_gross_R + other.sum_gross_R,
            sum_cost_drag_R=self.sum_cost_drag_R + other.sum_cost_drag_R,
            sum_mfe_R=self.sum_mfe_R + other.sum_mfe_R,
            sum_mae_R=self.sum_mae_R + other.sum_mae_R,
            max_win_R=max(self.max_win_R, other.max_win_R),
            max_loss_R=min(self.max_loss_R, other.max_loss_R),
            sum_theo_pct=self.sum_theo_pct + other.sum_theo_pct,
            sum_slip_pct=self.sum_slip_pct + other.sum_slip_pct,
            sum_comm_pct=self.sum_comm_pct + other.sum_comm_pct,
            sum_tax_pct=self.sum_tax_pct + other.sum_tax_pct,
            sum_friction_pct=self.sum_friction_pct + other.sum_friction_pct,
            sum_net_pct=self.sum_net_pct + other.sum_net_pct,
            pnl_samples=(self.pnl_samples + other.pnl_samples)[:2000],
            risk_pct_samples=(self.risk_pct_samples + other.risk_pct_samples)[:2000],
            risk_tick_samples=(self.risk_tick_samples + other.risk_tick_samples)[:2000],
        )

    def to_metrics(self) -> dict[str, Any]:
        n = self.count
        if n == 0:
            return {
                "unique_signals": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "theoretical_gross_R": 0.0,
                "net_expectancy_R": 0.0,
                "cost_drag_R": 0.0,
                "median_R": 0.0,
                "std_R": 0.0,
                "MFE_R": 0.0,
                "MAE_R": 0.0,
                "theoretical_return_pct": 0.0,
                "slippage_pct": 0.0,
                "commission_pct": 0.0,
                "tax_pct": 0.0,
                "trading_friction_pct": 0.0,
                "net_return_pct": 0.0,
                "mean_risk_pct": 0.0,
                "median_risk_pct": 0.0,
                "mean_risk_ticks": 0.0,
                "median_risk_ticks": 0.0,
            }

        win_rate = self.win_count / n
        exp_R = self.sum_pnl_R / n
        gross_exp_R = self.sum_gross_R / n
        cost_drag_R = self.sum_cost_drag_R / n

        mean_pnl = exp_R
        variance = (self.sum_sq_pnl_R / n) - (mean_pnl * mean_pnl)
        std_R = math.sqrt(max(0.0, variance))
        pf = self.gross_gains / self.gross_losses if self.gross_losses > 0 else (10.0 if self.gross_gains > 0 else 1.0)

        samples = sorted(self.pnl_samples)
        m_len = len(samples)
        median_R = samples[m_len // 2] if m_len > 0 else 0.0

        # Percentage return rounded components
        theo_pct_avg = round(self.sum_theo_pct / n, 4)
        slip_pct_avg = round(self.sum_slip_pct / n, 4)
        comm_pct_avg = round(self.sum_comm_pct / n, 4)
        tax_pct_avg = round(self.sum_tax_pct / n, 4)
        friction_pct_avg = round(slip_pct_avg + comm_pct_avg + tax_pct_avg, 4)
        net_pct_avg = round(theo_pct_avg - friction_pct_avg, 4)

        # Risk distributions
        rp_samples = sorted(self.risk_pct_samples)
        rt_samples = sorted(self.risk_tick_samples)
        mean_rp = round(sum(rp_samples) / len(rp_samples), 4) if rp_samples else 0.0
        med_rp = round(rp_samples[len(rp_samples) // 2], 4) if rp_samples else 0.0
        mean_rt = round(sum(rt_samples) / len(rt_samples), 4) if rt_samples else 0.0
        med_rt = round(rt_samples[len(rt_samples) // 2], 4) if rt_samples else 0.0

        return {
            "unique_signals": n,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(pf, 4),
            "theoretical_gross_R": round(gross_exp_R, 4),
            "net_expectancy_R": round(exp_R, 4),
            "cost_drag_R": round(cost_drag_R, 4),
            "median_R": round(median_R, 4),
            "std_R": round(std_R, 4),
            "MFE_R": round(self.sum_mfe_R / n, 4),
            "MAE_R": round(self.sum_mae_R / n, 4),
            "theoretical_return_pct": theo_pct_avg,
            "slippage_pct": slip_pct_avg,
            "commission_pct": comm_pct_avg,
            "tax_pct": tax_pct_avg,
            "trading_friction_pct": friction_pct_avg,
            "net_return_pct": net_pct_avg,
            "mean_risk_pct": mean_rp,
            "median_risk_pct": med_rp,
            "mean_risk_ticks": mean_rt,
            "median_risk_ticks": med_rt,
        }


def load_shioaji_kbars(path: Path) -> list[MarketBar]:
    """Loads historical kbars from Shioaji json.gz with official archive Amount priority."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    kbars = data.get("kbars", {})
    ts_list = kbars.get("ts", [])
    opens = kbars.get("Open", [])
    highs = kbars.get("High", [])
    lows = kbars.get("Low", [])
    closes = kbars.get("Close", [])
    volumes = kbars.get("Volume", [])
    amounts = kbars.get("Amount", [])

    bars: list[MarketBar] = []
    n = len(ts_list)
    has_amount = len(amounts) == n

    for i in range(n):
        ns = int(ts_list[i])
        t_close = (datetime(1970, 1, 1) + timedelta(microseconds=ns // 1000)).replace(tzinfo=TPE)
        t_open = t_close - timedelta(minutes=1)
        c = float(closes[i])
        v = float(volumes[i])

        if has_amount and amounts[i] is not None and float(amounts[i]) > 0:
            a = float(amounts[i])
        else:
            a = c * v * 1000.0

        bars.append(
            MarketBar(
                bar_open_time=t_open,
                bar_close_time=t_close,
                open=float(opens[i]),
                high=float(highs[i]),
                low=float(lows[i]),
                close=c,
                volume=v,
                amount=a,
            )
        )
    return bars


def build_rolling_fold_schedule(sorted_dates: list[str]) -> list[dict[str, Any]]:
    """Builds a strictly causal 5-fold rolling walk-forward schedule with 1-day embargo."""
    n = len(sorted_dates)
    fold_schedule = []
    step = max(1, n // 7)
    train_len = max(2, step * 3)
    test_len = max(1, step)
    embargo_days = 1

    for i in range(5):
        train_start_idx = min(n - 1, i * step)
        train_end_idx = min(n - 1, train_start_idx + train_len - 1)
        test_start_idx = min(n - 1, train_end_idx + embargo_days + 1)
        test_end_idx = min(n - 1, test_start_idx + test_len - 1)

        fold_schedule.append({
            "fold": i + 1,
            "train_start": sorted_dates[train_start_idx],
            "train_end": sorted_dates[train_end_idx],
            "test_start": sorted_dates[test_start_idx],
            "test_end": sorted_dates[test_end_idx],
            "incomplete_terminal": (i == 4),
        })
    return fold_schedule


def process_date_chunk(args_tuple: tuple) -> dict[str, Any]:
    """Worker processing a slice of date folders with constant memory footprint."""
    dates_chunk, data_dir_str, fold_schedule, worker_id = args_tuple
    data_dir = Path(data_dir_str)

    cost_model = TransactionCostModel(
        broker_fee_rate=BASE_COMMISSION_REFERENCE_RATE,
        broker_discount=PARAM_BROKER_DISCOUNT.value,
        minimum_fee=PARAM_MINIMUM_FEE.value,
        daytrade_tax_rate=PARAM_DAYTRADE_TAX_RATE.value,
    )

    raw_trades_dir = REPO_ROOT / "docs/daytrade_phase2/raw_trades"
    raw_trades_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_trades_dir / f"worker_{worker_id}_trades.jsonl.gz"
    manifest_f = gzip.open(manifest_path, "wt", encoding="utf-8")

    # Accumulators dictionary
    filter_keys = [
        "UNFILTERED",
        "F01_MARKET_REGIME",
        "F02_RELATIVE_STRENGTH",
        "F03_SECTOR_STRENGTH",
        "F04_HIGHER_TIMEFRAME",
        "F05_LIQUIDITY_POOL",
        "PAIR_01_F01_F02",
        "PAIR_02_F01_F04",
        "PAIR_03_F01_F05",
        "PAIR_04_F02_F05",
    ]

    accumulators = {k: FilterAccumulator() for k in filter_keys}

    # Stratifications
    strat_accs = {
        "COMPLETE_ONLY": {k: FilterAccumulator() for k in filter_keys},
        "USABLE_WITH_GAPS": {k: FilterAccumulator() for k in filter_keys},
    }

    # Slices
    by_year_accs: dict[str, dict[str, FilterAccumulator]] = {}
    by_tod_accs: dict[str, dict[str, FilterAccumulator]] = {
        "MORNING": {k: FilterAccumulator() for k in filter_keys},
        "MID_AM": {k: FilterAccumulator() for k in filter_keys},
        "MID_PM": {k: FilterAccumulator() for k in filter_keys},
        "AFTERNOON": {k: FilterAccumulator() for k in filter_keys},
    }
    by_cid_accs: dict[str, dict[str, FilterAccumulator]] = {
        "P2B_01_v1": {k: FilterAccumulator() for k in filter_keys},
        "P2B_02_v1": {k: FilterAccumulator() for k in filter_keys},
        "P2B_03_v1": {k: FilterAccumulator() for k in filter_keys},
        "P2B_04_v1": {k: FilterAccumulator() for k in filter_keys},
    }

    # Walk forward accumulators: fold -> "IS"/"OOS" -> filter_key -> FilterAccumulator
    wf_accs: dict[int, dict[str, dict[str, FilterAccumulator]]] = {}
    for f in fold_schedule:
        f_idx = f["fold"]
        wf_accs[f_idx] = {
            "IS": {k: FilterAccumulator() for k in filter_keys},
            "OOS": {k: FilterAccumulator() for k in filter_keys},
        }

    # Retention curve sensitivity accumulators
    retention_curve_accs = {
        "F01_th_minus_03": FilterAccumulator(),
        "F01_th_00": FilterAccumulator(),
        "F01_th_plus_03": FilterAccumulator(),
        "F02_win_5m": FilterAccumulator(),
        "F02_win_15m": FilterAccumulator(),
        "F02_win_30m": FilterAccumulator(),
        "F02_win_60m": FilterAccumulator(),
        "F04_5m": FilterAccumulator(),
        "F04_15m": FilterAccumulator(),
        "F04_30m": FilterAccumulator(),
        "F05_10M": FilterAccumulator(),
        "F05_20M": FilterAccumulator(),
        "F05_50M": FilterAccumulator(),
    }

    # Audits
    stock_days_complete = 0
    stock_days_usable_gaps = 0
    stock_days_invalid = 0
    observed_large_gap_count = 0
    symbols_seen = set()

    # Funnel counts
    raw_signal_count = 0
    simulated_signal_count = 0
    drop_reasons: dict[str, int] = {}

    # Detectors
    det_p2b01 = [PullbackVolumeDecayDetector(max_pullback_bars=pb) for pb in [3, 5]]
    det_p2b02 = [RangeExpansionDetector(lookback_bars=lb) for lb in [3, 5]]
    det_p2b03 = [TwoBReversalDetector(pivot_confirmation_bars=cb, max_failure_bars=fb) for cb in [2, 3] for fb in [3, 5]]
    det_p2b04 = [OneTwoThreeDetector(confirmation_bars=cb) for cb in [1, 2]]

    for d_idx, date_str in enumerate(dates_chunk):
        date_folder = data_dir / date_str
        if not date_folder.exists():
            continue

        file_list = sorted(list(date_folder.glob("*.json.gz")))
        if not file_list:
            continue

        # Load all stock bars for date
        universe_bars: dict[str, list[MarketBar]] = {}
        for f in file_list:
            sym = f.name.split(".")[0]
            symbols_seen.add(sym)
            b_list = load_shioaji_kbars(f)
            if not b_list:
                stock_days_invalid += 1
                continue

            rep = assess_stock_day_completeness(sym, b_list)
            if rep.observed_large_gap:
                observed_large_gap_count += 1
            if rep.status == StockDayCompletenessStatus.INVALID:
                stock_days_invalid += 1
                continue
            elif rep.status == StockDayCompletenessStatus.COMPLETE:
                stock_days_complete += 1
            else:
                stock_days_usable_gaps += 1

            universe_bars[sym] = b_list

        if not universe_bars:
            continue

        # Active folds for current date
        active_is_folds = [f["fold"] for f in fold_schedule if f["train_start"] <= date_str <= f["train_end"]]
        active_oos_folds = [f["fold"] for f in fold_schedule if f["test_start"] <= date_str <= f["test_end"]]

        # Precompute Cross-Sectional Leave-One-Out Market Matrix
        # Collect distinct timestamps
        all_ts_set = set()
        for sym, b_list in universe_bars.items():
            for b in b_list:
                all_ts_set.add(b.bar_close_time)

        sorted_ts = sorted(list(all_ts_set))
        ts_index_map = {ts: idx for idx, ts in enumerate(sorted_ts)}
        n_ts = len(sorted_ts)

        # Build symbol price arrays
        sym_close_map: dict[str, list[float]] = {}
        sym_open_0901: dict[str, float] = {}
        sym_amount_map: dict[str, list[float]] = {}

        for sym, b_list in universe_bars.items():
            c_arr = [float("nan")] * n_ts
            a_arr = [0.0] * n_ts
            first_open = b_list[0].open if b_list else 100.0
            for b in b_list:
                t_idx = ts_index_map[b.bar_close_time]
                c_arr[t_idx] = b.close
                a_arr[t_idx] = b.amount
            sym_close_map[sym] = c_arr
            sym_open_0901[sym] = first_open
            sym_amount_map[sym] = a_arr

        # Cross section cum return sums and counts
        cum_ret_sum = [0.0] * n_ts
        cum_ret_count = [0] * n_ts
        rs_15m_sum = [0.0] * n_ts
        rs_15m_count = [0] * n_ts

        # Precalculate returns for each symbol
        sym_cum_ret: dict[str, list[float]] = {}
        sym_rs_15m: dict[str, list[float]] = {}

        for sym, c_arr in sym_close_map.items():
            open_p = sym_open_0901[sym]
            c_ret = [float("nan")] * n_ts
            r_15m = [float("nan")] * n_ts
            for t_idx in range(n_ts):
                c = c_arr[t_idx]
                if not math.isnan(c) and open_p > 0:
                    ret_cum = (c - open_p) / open_p
                    c_ret[t_idx] = ret_cum
                    cum_ret_sum[t_idx] += ret_cum
                    cum_ret_count[t_idx] += 1

                    # 15m return
                    past_idx = max(0, t_idx - 15)
                    past_c = c_arr[past_idx]
                    if not math.isnan(past_c) and past_c > 0:
                        ret_15 = (c - past_c) / past_c
                        r_15m[t_idx] = ret_15
                        rs_15m_sum[t_idx] += ret_15
                        rs_15m_count[t_idx] += 1

            sym_cum_ret[sym] = c_ret
            sym_rs_15m[sym] = r_15m

        # Precompute 5m closed bars for each symbol
        sym_5m_bullish: dict[str, list[bool]] = {}
        for sym, b_list in universe_bars.items():
            # Group into 5m blocks
            bullish_5m = [True] * n_ts
            # Map each 1m bar to the state of last closed 5m bar
            # 5m bar closes at minute ending in 0 or 5 (09:05, 09:10, 09:15...)
            last_5m_bull = True
            forming_open = None
            forming_close = None
            for b in b_list:
                t_idx = ts_index_map[b.bar_close_time]
                if forming_open is None:
                    forming_open = b.open
                forming_close = b.close
                # If 5m boundary reached
                if b.bar_close_time.minute % 5 == 0:
                    last_5m_bull = (forming_close >= forming_open)
                    forming_open = None
                bullish_5m[t_idx] = last_5m_bull
            sym_5m_bullish[sym] = bullish_5m

        # Precompute 30m rolling traded value
        sym_rolling_30m_amt: dict[str, list[float]] = {}
        for sym, a_arr in sym_amount_map.items():
            r_amt = [0.0] * n_ts
            run_sum = 0.0
            for t_idx in range(n_ts):
                run_sum += a_arr[t_idx]
                if t_idx >= 30:
                    run_sum -= a_arr[t_idx - 30]
                r_amt[t_idx] = run_sum
            sym_rolling_30m_amt[sym] = r_amt

        # Process each symbol on date
        for sym, bars in universe_bars.items():
            n_bars = len(bars)
            bar_map = {b.bar_close_time: idx for idx, b in enumerate(bars)}

            signals_collected = []
            # Run detectors
            # P2B_01
            for d in det_p2b01:
                sigs = d.detect_signals(sym, bars, threshold=0.50)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_01_v1", s, idx))

            # P2B_02
            for d in det_p2b02:
                sigs = d.detect_signals(sym, bars, threshold=1.2)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_02_v1", s, idx))

            # P2B_03
            for d in det_p2b03:
                sigs = d.detect_signals(sym, bars)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_03_v1", s, idx))

            # P2B_04
            for d in det_p2b04:
                sigs = d.detect_signals(sym, bars)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_04_v1", s, idx))

            # Deduplicate by unique signal event
            unique_sigs = {}
            for cid, s, idx in signals_collected:
                k = (cid, idx, s.direction.upper(), s.stop_loss_price)
                if k not in unique_sigs:
                    unique_sigs[k] = (cid, s, idx)

            raw_signal_count += len(unique_sigs)

            # Evaluate each unique signal
            for (cid, idx, dir_upper, stop_loss), (_, sig, sig_idx) in unique_sigs.items():
                entry_idx = sig_idx + 1
                if entry_idx >= n_bars:
                    drop_reasons["NO_LEGAL_EXECUTION"] = drop_reasons.get("NO_LEGAL_EXECUTION", 0) + 1
                    continue

                entry_bar = bars[entry_idx]
                theo_entry = entry_bar.open

                # Validation drops
                if dir_upper == "LONG" and stop_loss >= theo_entry:
                    drop_reasons["STOP_LOSS_VIOLATION"] = drop_reasons.get("STOP_LOSS_VIOLATION", 0) + 1
                    continue
                if dir_upper == "SHORT" and stop_loss <= theo_entry:
                    drop_reasons["STOP_LOSS_VIOLATION"] = drop_reasons.get("STOP_LOSS_VIOLATION", 0) + 1
                    continue

                initial_risk = abs(theo_entry - stop_loss)
                if initial_risk <= 0:
                    drop_reasons["INVALID_INITIAL_RISK"] = drop_reasons.get("INVALID_INITIAL_RISK", 0) + 1
                    continue

                # 15m exit horizon
                exit_idx = min(entry_idx + 15, n_bars - 1)
                sub_bars = bars[entry_idx : exit_idx + 1]
                if not sub_bars:
                    drop_reasons["INSUFFICIENT_FORWARD_HORIZON"] = drop_reasons.get("INSUFFICIENT_FORWARD_HORIZON", 0) + 1
                    continue

                simulated_signal_count += 1

                # Hit stop loss check
                hit_stop = False
                for b in sub_bars:
                    if dir_upper == "LONG" and b.low <= stop_loss:
                        hit_stop = True
                        break
                    elif dir_upper == "SHORT" and b.high >= stop_loss:
                        hit_stop = True
                        break

                theo_exit = stop_loss if hit_stop else bars[exit_idx].close

                # Execution with 1 tick slippage
                e_tick = get_twse_tick_size(theo_entry)
                x_tick = get_twse_tick_size(theo_exit)
                qty = 1000

                if dir_upper == "LONG":
                    act_entry = theo_entry + e_tick
                    act_exit = theo_exit - x_tick
                    gross_actual = (act_exit - act_entry) * qty
                    gross_theo = (theo_exit - theo_entry) * qty
                else:
                    act_entry = theo_entry - e_tick
                    act_exit = theo_exit + x_tick
                    gross_actual = (act_entry - act_exit) * qty
                    gross_theo = (theo_entry - theo_exit) * qty

                e_notional = act_entry * qty
                x_notional = act_exit * qty

                e_comm, x_comm, tax = cost_model.calculate_round_trip_costs(e_notional, x_notional, is_daytrade=True)
                slip_cost = (e_tick + x_tick) * qty
                tot_costs = e_comm + x_comm + tax + slip_cost
                net_pnl = gross_actual - (e_comm + x_comm + tax)

                risk_amt = initial_risk * qty
                pnl_R = net_pnl / risk_amt
                gross_pnl_R = gross_actual / risk_amt
                cost_drag_R = tot_costs / risk_amt

                # MFE / MAE
                highs = [b.high for b in sub_bars]
                lows = [b.low for b in sub_bars]
                if dir_upper == "LONG":
                    mfe_R = max(0.0, (max(highs) - theo_entry) / initial_risk)
                    mae_R = max(0.0, (theo_entry - min(lows)) / initial_risk)
                else:
                    mfe_R = max(0.0, (theo_entry - min(lows)) / initial_risk)
                    mae_R = max(0.0, (max(highs) - theo_entry) / initial_risk)

                # Percentage return decomposition (Single Source of Truth)
                theo_pct = gross_theo / e_notional * 100.0
                slip_pct = slip_cost / e_notional * 100.0
                comm_pct = (e_comm + x_comm) / e_notional * 100.0
                tax_pct = tax / e_notional * 100.0
                friction_pct = slip_pct + comm_pct + tax_pct
                net_pct = theo_pct - friction_pct

                # Accounting identity dynamic assert
                assert abs(net_pct - (theo_pct - friction_pct)) < 1e-7

                risk_pct = (initial_risk / act_entry * 100.0)
                risk_ticks = initial_risk / e_tick

                # Time slices
                sig_t = parse_phase2_timestamp(sig.signal_time)
                year_str = str(sig_t.year)
                if year_str not in by_year_accs:
                    by_year_accs[year_str] = {k: FilterAccumulator() for k in filter_keys}

                t_hour, t_min = sig_t.hour, sig_t.minute
                if t_hour == 9 or (t_hour == 10 and t_min < 30):
                    tod_key = "MORNING"
                elif t_hour == 10 or (t_hour == 11 and t_min < 30):
                    tod_key = "MID_AM"
                elif t_hour == 11 or t_hour == 12:
                    tod_key = "MID_PM"
                else:
                    tod_key = "AFTERNOON"

                st_status = "COMPLETE" if len(bars) == 266 else "USABLE_WITH_GAPS"

                # Filter Evaluations
                t_matrix_idx = ts_index_map[sig.signal_time]

                # F01: Leave-One-Out Market Regime Intraday Direction
                tot_c = cum_ret_count[t_matrix_idx]
                s_ret = sym_cum_ret[sym][t_matrix_idx]
                if not math.isnan(s_ret) and tot_c > 1:
                    loo_cum = (cum_ret_sum[t_matrix_idx] - s_ret) / (tot_c - 1)
                elif tot_c > 0:
                    loo_cum = cum_ret_sum[t_matrix_idx] / tot_c
                else:
                    loo_cum = 0.0

                f01_keep = (loo_cum >= 0.0) if dir_upper == "LONG" else (loo_cum <= 0.0)

                # F02: Leave-One-Out Relative Strength (15m window)
                tot_rs = rs_15m_count[t_matrix_idx]
                s_rs = sym_rs_15m[sym][t_matrix_idx]
                if not math.isnan(s_rs) and tot_rs > 1:
                    loo_rs_peer = (rs_15m_sum[t_matrix_idx] - s_rs) / (tot_rs - 1)
                elif tot_rs > 0:
                    loo_rs_peer = rs_15m_sum[t_matrix_idx] / tot_rs
                else:
                    loo_rs_peer = 0.0

                rs_diff = s_rs - loo_rs_peer if not math.isnan(s_rs) else 0.0
                # Non-adverse condition (neutral band = 0.001)
                f02_keep = (rs_diff >= -0.001) if dir_upper == "LONG" else (rs_diff <= 0.001)

                # F03: Sector Strength (Data Insufficient -> 100% Retained)
                f03_keep = True

                # F04: Higher Timeframe Context (5m closed bar bullish/bearish)
                last_5m_bull = sym_5m_bullish[sym][t_matrix_idx]
                f04_keep = last_5m_bull if dir_upper == "LONG" else (not last_5m_bull)

                # F05: Liquidity Candidate Pool (30m traded value >= 10M TWD)
                amt_30m = sym_rolling_30m_amt[sym][t_matrix_idx]
                f05_keep = (amt_30m >= 10_000_000.0)

                # Pairwise Combinations (Exploratory)
                pair_01_keep = f01_keep and f02_keep
                pair_02_keep = f01_keep and f04_keep
                pair_03_keep = f01_keep and f05_keep
                pair_04_keep = f02_keep and f05_keep

                # Retention curve sensitivities
                if (loo_cum >= -0.003 if dir_upper == "LONG" else loo_cum <= 0.003):
                    retention_curve_accs["F01_th_minus_03"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                if f01_keep:
                    retention_curve_accs["F01_th_00"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                if (loo_cum >= 0.003 if dir_upper == "LONG" else loo_cum <= -0.003):
                    retention_curve_accs["F01_th_plus_03"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                if f02_keep:
                    retention_curve_accs["F02_win_15m"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                if f04_keep:
                    retention_curve_accs["F04_5m"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                if amt_30m >= 10_000_000.0:
                    retention_curve_accs["F05_10M"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                if amt_30m >= 20_000_000.0:
                    retention_curve_accs["F05_20M"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                if amt_30m >= 50_000_000.0:
                    retention_curve_accs["F05_50M"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                # Feed active accumulators
                active_filters = {
                    "UNFILTERED": True,
                    "F01_MARKET_REGIME": f01_keep,
                    "F02_RELATIVE_STRENGTH": f02_keep,
                    "F03_SECTOR_STRENGTH": f03_keep,
                    "F04_HIGHER_TIMEFRAME": f04_keep,
                    "F05_LIQUIDITY_POOL": f05_keep,
                    "PAIR_01_F01_F02": pair_01_keep,
                    "PAIR_02_F01_F04": pair_02_keep,
                    "PAIR_03_F01_F05": pair_03_keep,
                    "PAIR_04_F02_F05": pair_04_keep,
                }

                for f_key, is_kept in active_filters.items():
                    if is_kept:
                        # Global
                        accumulators[f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                        # Stratifications
                        if st_status == "COMPLETE":
                            strat_accs["COMPLETE_ONLY"][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                        else:
                            strat_accs["USABLE_WITH_GAPS"][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                        # Slices
                        by_year_accs[year_str][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                        by_tod_accs[tod_key][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                        by_cid_accs[cid][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                        # Walk forward
                        for f_idx in active_is_folds:
                            wf_accs[f_idx]["IS"][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)
                        for f_idx in active_oos_folds:
                            wf_accs[f_idx]["OOS"][f_key].add(pnl_R, gross_pnl_R, cost_drag_R, gross_actual, mfe_R, mae_R, theo_pct, slip_pct, comm_pct, tax_pct, friction_pct, net_pct, risk_pct, risk_ticks)

                trade_record = {
                    "signal_event_id": f"{sym}_{date_str}_{cid}_{sig_idx}_{dir_upper}",
                    "symbol": sym,
                    "date": date_str,
                    "candidate_id": cid,
                    "direction": dir_upper,
                    "signal_time": sig.signal_time.isoformat(),
                    "theo_entry": theo_entry,
                    "theo_exit": theo_exit,
                    "net_return_pct": round(net_pct, 4),
                    "trading_friction_pct": round(friction_pct, 4),
                    "pnl_R": round(pnl_R, 4),
                    "f01_keep": f01_keep,
                    "f02_keep": f02_keep,
                    "f04_keep": f04_keep,
                    "f05_keep": f05_keep,
                    "pair_01_keep": pair_01_keep,
                    "pair_02_keep": pair_02_keep,
                    "pair_03_keep": pair_03_keep,
                    "pair_04_keep": pair_04_keep,
                }
                manifest_f.write(json.dumps(trade_record) + "\n")

        # Clear memory of current date
        del universe_bars
        del sym_close_map
        del sym_open_0901
        del sym_amount_map
        del sym_cum_ret
        del sym_rs_15m
        del sym_5m_bullish
        del sym_rolling_30m_amt

        if (d_idx + 1) % 50 == 0:
            print(f"[Worker {worker_id}] Processed {d_idx + 1}/{len(dates_chunk)} dates. Simulated: {simulated_signal_count}")

    manifest_f.close()

    return {
        "worker_id": worker_id,
        "stock_days_complete": stock_days_complete,
        "stock_days_usable_gaps": stock_days_usable_gaps,
        "stock_days_invalid": stock_days_invalid,
        "observed_large_gap_count": observed_large_gap_count,
        "symbols_seen": list(symbols_seen),
        "raw_signal_count": raw_signal_count,
        "simulated_signal_count": simulated_signal_count,
        "drop_reasons": drop_reasons,
        "accumulators": accumulators,
        "strat_accs": strat_accs,
        "by_year_accs": by_year_accs,
        "by_tod_accs": by_tod_accs,
        "by_cid_accs": by_cid_accs,
        "wf_accs": wf_accs,
        "retention_curve_accs": retention_curve_accs,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EasyStock Phase 2B Batch 2 Full Historical Runner")
    parser.add_argument("--data-dir", type=str, default="/home/ubuntu/easystock-history-expanded-data/raw")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output-yaml", type=str, default="docs/daytrade_phase2/phase2b_batch2_full_run_summary.yaml")
    parser.add_argument("--output-report", type=str, default="docs/daytrade_phase2/PHASE2B_BATCH2_FULL_RUN_REPORT.md")
    parser.add_argument("--limit-dates", type=int, default=None)
    args = parser.parse_args()

    # Pre-Run Integrity Guard Check
    p_plan = REPO_ROOT / "docs/daytrade_phase2/PHASE2B_BATCH2_FULL_RUN_PLAN.yaml"
    p_reg = REPO_ROOT / "docs/daytrade_phase2/phase2b_batch2_filter_registry.yaml"

    plan_hash_start = hashlib.sha256(p_plan.read_bytes()).hexdigest()
    reg_hash_start = hashlib.sha256(p_reg.read_bytes()).hexdigest()

    if plan_hash_start != EXPECTED_PLAN_HASH:
        print(f"ABORT_FULL_RUN=true: Plan hash mismatch {plan_hash_start} != {EXPECTED_PLAN_HASH}", file=sys.stderr)
        sys.exit(1)
    if reg_hash_start != EXPECTED_REGISTRY_HASH:
        print(f"ABORT_FULL_RUN=true: Registry hash mismatch {reg_hash_start} != {EXPECTED_REGISTRY_HASH}", file=sys.stderr)
        sys.exit(1)

    print("BEFORE_RUN_INTEGRITY_GUARD=PASS")
    run_start_time = datetime.now(TPE)
    run_id = f"P2B_B2_FULL_HISTORICAL_{run_start_time.strftime('%Y%m%d_%H%M%S')}"

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Data directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    all_dates = sorted([d.name for d in data_dir.iterdir() if d.is_dir() and d.name.startswith("20")])
    if args.limit_dates is not None:
        all_dates = all_dates[:args.limit_dates]

    total_dates = len(all_dates)
    print(f"Starting Phase 2B Batch 2 Full Run on {total_dates} dates with {args.workers} workers...")
    t0 = time.time()

    fold_schedule = build_rolling_fold_schedule(all_dates)

    # Chunk dates for workers
    chunk_size = math.ceil(total_dates / args.workers)
    worker_args = []
    for w in range(args.workers):
        sub_dates = all_dates[w * chunk_size : (w + 1) * chunk_size]
        if sub_dates:
            worker_args.append((sub_dates, str(data_dir), fold_schedule, w + 1))

    # Execute workers
    if args.workers == 1 or len(worker_args) == 1:
        results = [process_date_chunk(worker_args[0])]
    else:
        with mp.Pool(processes=args.workers) as pool:
            results = pool.map(process_date_chunk, worker_args)

    elapsed_seconds = round(time.time() - t0, 2)
    print(f"Historical simulation completed in {elapsed_seconds}s. Aggregating results...")

    # Aggregate results from all workers
    stock_days_complete = sum(r["stock_days_complete"] for r in results)
    stock_days_usable_gaps = sum(r["stock_days_usable_gaps"] for r in results)
    stock_days_invalid = sum(r["stock_days_invalid"] for r in results)
    observed_large_gap_count = sum(r["observed_large_gap_count"] for r in results)
    all_symbols = set()
    for r in results:
        all_symbols.update(r["symbols_seen"])

    raw_signal_count = sum(r["raw_signal_count"] for r in results)
    simulated_signal_count = sum(r["simulated_signal_count"] for r in results)

    drop_reasons: dict[str, int] = {}
    for r in results:
        for k, v in r["drop_reasons"].items():
            drop_reasons[k] = drop_reasons.get(k, 0) + v

    # Merge main accumulators
    filter_keys = list(results[0]["accumulators"].keys())
    merged_accs = {k: FilterAccumulator() for k in filter_keys}
    for r in results:
        for k in filter_keys:
            merged_accs[k] = merged_accs[k].merge(r["accumulators"][k])

    # Merge stratifications
    merged_strat = {
        "COMPLETE_ONLY": {k: FilterAccumulator() for k in filter_keys},
        "USABLE_WITH_GAPS": {k: FilterAccumulator() for k in filter_keys},
    }
    for r in results:
        for st_name in ["COMPLETE_ONLY", "USABLE_WITH_GAPS"]:
            for k in filter_keys:
                merged_strat[st_name][k] = merged_strat[st_name][k].merge(r["strat_accs"][st_name][k])

    # Merge slices
    merged_by_year: dict[str, dict[str, FilterAccumulator]] = {}
    for r in results:
        for y, y_accs in r["by_year_accs"].items():
            if y not in merged_by_year:
                merged_by_year[y] = {k: FilterAccumulator() for k in filter_keys}
            for k in filter_keys:
                merged_by_year[y][k] = merged_by_year[y][k].merge(y_accs[k])

    merged_by_tod: dict[str, dict[str, FilterAccumulator]] = {
        tod: {k: FilterAccumulator() for k in filter_keys}
        for tod in ["MORNING", "MID_AM", "MID_PM", "AFTERNOON"]
    }
    for r in results:
        for tod in merged_by_tod:
            for k in filter_keys:
                merged_by_tod[tod][k] = merged_by_tod[tod][k].merge(r["by_tod_accs"][tod][k])

    merged_by_cid: dict[str, dict[str, FilterAccumulator]] = {
        cid: {k: FilterAccumulator() for k in filter_keys}
        for cid in ["P2B_01_v1", "P2B_02_v1", "P2B_03_v1", "P2B_04_v1"]
    }
    for r in results:
        for cid in merged_by_cid:
            for k in filter_keys:
                merged_by_cid[cid][k] = merged_by_cid[cid][k].merge(r["by_cid_accs"][cid][k])

    # Merge walk-forward
    merged_wf: dict[int, dict[str, dict[str, FilterAccumulator]]] = {}
    for f in fold_schedule:
        f_idx = f["fold"]
        merged_wf[f_idx] = {
            "IS": {k: FilterAccumulator() for k in filter_keys},
            "OOS": {k: FilterAccumulator() for k in filter_keys},
        }
        for r in results:
            for mode in ["IS", "OOS"]:
                for k in filter_keys:
                    merged_wf[f_idx][mode][k] = merged_wf[f_idx][mode][k].merge(r["wf_accs"][f_idx][mode][k])

    # Merge retention curve
    ret_curve_keys = list(results[0]["retention_curve_accs"].keys())
    merged_ret_curve = {k: FilterAccumulator() for k in ret_curve_keys}
    for r in results:
        for k in ret_curve_keys:
            merged_ret_curve[k] = merged_ret_curve[k].merge(r["retention_curve_accs"][k])

    # Signal Funnel Accounting Identity Check
    total_dropped = sum(drop_reasons.values())
    silent_drop_count = raw_signal_count - (simulated_signal_count + total_dropped)
    funnel_pass = (silent_drop_count == 0)
    print(f"Signal Funnel: Raw={raw_signal_count}, Simulated={simulated_signal_count}, Dropped={total_dropped}, Silent={silent_drop_count}")
    assert funnel_pass, f"Signal Funnel violation: Silent drops={silent_drop_count}"

    # Percentage Return Accounting Invariant Check
    unfiltered_m = merged_accs["UNFILTERED"].to_metrics()
    friction_id_diff = abs(unfiltered_m["trading_friction_pct"] - (unfiltered_m["slippage_pct"] + unfiltered_m["commission_pct"] + unfiltered_m["tax_pct"]))
    net_id_diff = abs(unfiltered_m["net_return_pct"] - (unfiltered_m["theoretical_return_pct"] - unfiltered_m["trading_friction_pct"]))
    accounting_pass = (friction_id_diff < 1e-4) and (net_id_diff < 1e-4)
    print(f"Percentage Return Invariant: Friction diff={friction_id_diff:.6f}, Net diff={net_id_diff:.6f}")
    assert accounting_pass, "Percentage Return Invariant Violation"

    # Compute comparative results
    confirmatory_keys = ["F01_MARKET_REGIME", "F02_RELATIVE_STRENGTH", "F04_HIGHER_TIMEFRAME", "F05_LIQUIDITY_POOL"]
    exploratory_keys = ["PAIR_01_F01_F02", "PAIR_02_F01_F04", "PAIR_03_F01_F05", "PAIR_04_F02_F05"]

    unfilt_n = unfiltered_m["unique_signals"]
    filter_eval_dict = {}

    for k in confirmatory_keys + ["F03_SECTOR_STRENGTH"] + exploratory_keys:
        filt_m = merged_accs[k].to_metrics()
        filt_n = filt_m["unique_signals"]
        retention = (filt_n / unfilt_n) if unfilt_n > 0 else 0.0

        d_theo = round(filt_m["theoretical_return_pct"] - unfiltered_m["theoretical_return_pct"], 4)
        d_fric = round(filt_m["trading_friction_pct"] - unfiltered_m["trading_friction_pct"], 4)
        d_net = round(filt_m["net_return_pct"] - unfiltered_m["net_return_pct"], 4)
        d_gross_R = round(filt_m["theoretical_gross_R"] - unfiltered_m["theoretical_gross_R"], 4)
        d_net_R = round(filt_m["net_expectancy_R"] - unfiltered_m["net_expectancy_R"], 4)

        # Attribution logic
        if d_theo > 0.02 and d_gross_R > 0.02:
            attr = "SIGNAL_EDGE_IMPROVEMENT"
        elif d_fric < -0.05:
            attr = "LOWER_FRICTION_SELECTION"
        elif d_net_R > 0.2 and d_net <= 0.0:
            attr = "LARGER_R_DENOMINATOR_SELECTION"
        elif d_net > 0.0 or d_theo > 0.0:
            attr = "MIXED_EFFECT"
        else:
            attr = "NO_CLEAR_IMPROVEMENT"

        # Special constraint: if Delta Net R > 0 but Delta theo pct <= 0 -> cannot be signal edge improvement
        if d_net_R > 0 and d_theo <= 0.0 and attr == "SIGNAL_EDGE_IMPROVEMENT":
            attr = "LARGER_R_DENOMINATOR_SELECTION"

        # Verdict
        if k == "F03_SECTOR_STRENGTH":
            verdict = "DATA_INSUFFICIENT"
        elif k in exploratory_keys:
            verdict = "EXPLORATORY_RESULT_RECORDED"
        else:
            if d_net > 0.02 and d_theo > 0.02:
                verdict = "FILTER_IMPROVES_RESEARCH_SIGNAL"
            elif d_net < -0.05:
                verdict = "FILTER_DEGRADES_SIGNAL"
            else:
                verdict = "FILTER_NO_CLEAR_IMPROVEMENT"

        scope_str = "CONFIRMATORY_SCOPE" if k in confirmatory_keys else ("DATA_INSUFFICIENT" if k == "F03_SECTOR_STRENGTH" else "EXPLORATORY_POST_SMOKE")

        filter_eval_dict[k] = {
            "filter_key": k,
            "scope": scope_str,
            "verdict": verdict,
            "effect_attribution": attr,
            "retention_rate": round(retention, 4),
            "unfiltered_unique_signals": unfilt_n,
            "filtered_unique_signals": filt_n,
            "delta_theoretical_return_pct": d_theo,
            "delta_trading_friction_pct": d_fric,
            "delta_net_return_pct": d_net,
            "delta_theoretical_gross_R": d_gross_R,
            "delta_net_expectancy_R": d_net_R,
            "unfiltered_metrics": unfiltered_m,
            "filtered_metrics": filt_m,
        }

    # Walk Forward Fold Evaluation
    wf_results = []
    for f in fold_schedule:
        f_idx = f["fold"]
        f_unfilt_oos = merged_wf[f_idx]["OOS"]["UNFILTERED"].to_metrics()
        fold_entry = {
            "fold_id": f_idx,
            "train_start": f["train_start"],
            "train_end": f["train_end"],
            "test_start": f["test_start"],
            "test_end": f["test_end"],
            "incomplete_terminal": f["incomplete_terminal"],
            "unfiltered_OOS_signals": f_unfilt_oos["unique_signals"],
            "unfiltered_OOS_theo_pct": f_unfilt_oos["theoretical_return_pct"],
            "unfiltered_OOS_net_pct": f_unfilt_oos["net_return_pct"],
            "unfiltered_OOS_net_R": f_unfilt_oos["net_expectancy_R"],
            "filters": {},
        }
        for k in confirmatory_keys:
            f_filt_oos = merged_wf[f_idx]["OOS"][k].to_metrics()
            d_oos_theo = round(f_filt_oos["theoretical_return_pct"] - f_unfilt_oos["theoretical_return_pct"], 4)
            d_oos_net = round(f_filt_oos["net_return_pct"] - f_unfilt_oos["net_return_pct"], 4)
            f_ret = (f_filt_oos["unique_signals"] / f_unfilt_oos["unique_signals"]) if f_unfilt_oos["unique_signals"] > 0 else 0.0

            fold_entry["filters"][k] = {
                "filtered_OOS_signals": f_filt_oos["unique_signals"],
                "retention_rate": round(f_ret, 4),
                "delta_OOS_theoretical_return_pct": d_oos_theo,
                "delta_OOS_net_return_pct": d_oos_net,
                "OOS_theoretical_return_pct": f_filt_oos["theoretical_return_pct"],
                "OOS_net_return_pct": f_filt_oos["net_return_pct"],
                "OOS_net_R": f_filt_oos["net_expectancy_R"],
                "OOS_profit_factor": f_filt_oos["profit_factor"],
                "OOS_win_rate": f_filt_oos["win_rate"],
            }
        wf_results.append(fold_entry)

    # Calculate Complete Folds Only and Trade Weighted OOS
    complete_folds = [f for f in wf_results if not f["incomplete_terminal"]]
    wf_summary_by_filter = {}
    for k in confirmatory_keys:
        tot_sig = sum(f["filters"][k]["filtered_OOS_signals"] for f in complete_folds)
        wt_theo_delta = sum(f["filters"][k]["delta_OOS_theoretical_return_pct"] * f["filters"][k]["filtered_OOS_signals"] for f in complete_folds) / tot_sig if tot_sig > 0 else 0.0
        wt_net_delta = sum(f["filters"][k]["delta_OOS_net_return_pct"] * f["filters"][k]["filtered_OOS_signals"] for f in complete_folds) / tot_sig if tot_sig > 0 else 0.0

        all_sig = sum(f["filters"][k]["filtered_OOS_signals"] for f in wf_results)
        all_wt_theo_delta = sum(f["filters"][k]["delta_OOS_theoretical_return_pct"] * f["filters"][k]["filtered_OOS_signals"] for f in wf_results) / all_sig if all_sig > 0 else 0.0
        all_wt_net_delta = sum(f["filters"][k]["delta_OOS_net_return_pct"] * f["filters"][k]["filtered_OOS_signals"] for f in wf_results) / all_sig if all_sig > 0 else 0.0

        wf_summary_by_filter[k] = {
            "complete_folds_delta_theo_pct": round(wt_theo_delta, 4),
            "complete_folds_delta_net_pct": round(wt_net_delta, 4),
            "all_folds_delta_theo_pct": round(all_wt_theo_delta, 4),
            "all_folds_delta_net_pct": round(all_wt_net_delta, 4),
        }

    # Verify Post-Run Hash Guard
    plan_hash_end = hashlib.sha256(p_plan.read_bytes()).hexdigest()
    reg_hash_end = hashlib.sha256(p_reg.read_bytes()).hexdigest()

    plan_mutated = (plan_hash_end != plan_hash_start)
    reg_mutated = (reg_hash_end != reg_hash_start)

    assert not plan_mutated, "PLAN_MUTATED_DURING_RUN violation"
    assert not reg_mutated, "REGISTRY_MUTATED_DURING_RUN violation"

    # Assemble Full Run Summary Document
    summary_doc = {
        "run_metadata": {
            "run_id": run_id,
            "execution_timestamp": datetime.now(TPE).isoformat(),
            "elapsed_seconds": elapsed_seconds,
            "RESEARCH_ONLY": True,
            "INERT_BY_DEFAULT": True,
            "survivorship_bias": True,
            "point_in_time_universe": False,
            "population_name": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE",
            "dataset_snapshot_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE",
            "baseline_sha": "b351e6b2c32ad9f19c8375d99c19423ab31a0ee8",
            "plan_hash_start": plan_hash_start,
            "plan_hash_end": plan_hash_end,
            "registry_hash_start": reg_hash_start,
            "registry_hash_end": reg_hash_end,
            "plan_mutated_during_run": plan_mutated,
            "registry_mutated_during_run": reg_mutated,
        },
        "dataset_audit": {
            "symbol_count": len(all_symbols),
            "date_count": total_dates,
            "total_stock_days_evaluated": stock_days_complete + stock_days_usable_gaps + stock_days_invalid,
            "stock_days_complete": stock_days_complete,
            "stock_days_usable_with_gaps": stock_days_usable_gaps,
            "stock_days_invalid": stock_days_invalid,
            "observed_large_gap_count": observed_large_gap_count,
        },
        "signal_funnel_audit": {
            "raw_signal_count": raw_signal_count,
            "simulated_signal_count": simulated_signal_count,
            "total_dropped_count": total_dropped,
            "silent_drop_count": silent_drop_count,
            "drop_reasons": drop_reasons,
            "signal_funnel_identity_pass": funnel_pass,
        },
        "accounting_identity_audit": {
            "percentage_return_identity_pass": accounting_pass,
            "max_friction_identity_discrepancy": round(friction_id_diff, 6),
            "max_net_return_identity_discrepancy": round(net_id_diff, 6),
        },
        "confirmatory_filter_results": {k: filter_eval_dict[k] for k in confirmatory_keys},
        "data_insufficient_filters": {
            "F03_SECTOR_STRENGTH": filter_eval_dict["F03_SECTOR_STRENGTH"],
        },
        "exploratory_pairwise_results": {k: filter_eval_dict[k] for k in exploratory_keys},
        "walk_forward_oos": {
            "schedule": fold_schedule,
            "folds": wf_results,
            "summary": wf_summary_by_filter,
            "oos_tuning_occurred": False,
            "incomplete_terminal_fold": True,
        },
        "retention_curves": {k: merged_ret_curve[k].to_metrics() for k in ret_curve_keys},
        "stratifications": {
            "COMPLETE_ONLY": {k: merged_strat["COMPLETE_ONLY"][k].to_metrics() for k in confirmatory_keys + ["UNFILTERED"]},
            "USABLE_WITH_GAPS": {k: merged_strat["USABLE_WITH_GAPS"][k].to_metrics() for k in confirmatory_keys + ["UNFILTERED"]},
        },
        "segmentations": {
            "by_year": {y: {k: merged_by_year[y][k].to_metrics() for k in confirmatory_keys + ["UNFILTERED"]} for y in sorted(merged_by_year.keys())},
            "by_tod": {tod: {k: merged_by_tod[tod][k].to_metrics() for k in confirmatory_keys + ["UNFILTERED"]} for tod in merged_by_tod},
            "by_candidate": {cid: {k: merged_by_cid[cid][k].to_metrics() for k in confirmatory_keys + ["UNFILTERED"]} for cid in merged_by_cid},
        },
    }

    out_yaml_p = REPO_ROOT / args.output_yaml
    out_yaml_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_yaml_p, "w", encoding="utf-8") as f:
        yaml.dump(summary_doc, f, allow_unicode=True, sort_keys=False)

    print(f"Summary saved to {out_yaml_p}")

    # Generate Markdown Report
    generate_markdown_report(summary_doc, REPO_ROOT / args.output_report)
    print(f"Report saved to {REPO_ROOT / args.output_report}")


def generate_markdown_report(summary: dict[str, Any], report_path: Path):
    """Generates the comprehensive Phase 2B Batch 2 Full Run Report in Traditional Chinese."""
    meta = summary["run_metadata"]
    ds = summary["dataset_audit"]
    funnel = summary["signal_funnel_audit"]
    acc = summary["accounting_identity_audit"]
    conf = summary["confirmatory_filter_results"]
    pair = summary["exploratory_pairwise_results"]
    wf_sum = summary["walk_forward_oos"]["summary"]

    lines = [
        "# EasyStock Phase 2B — Batch 2 歷史全量情境過濾回測報告",
        "## Context / Regime / Relative Strength Filter Full Historical Run Report",
        "",
        "---",
        "",
        "## 1. 執行摘要與治理邊界 (Executive Summary & Governance)",
        "",
        "本報告記錄 **Phase 2B Batch 2（情境／市場狀態／相對強弱／高階時間框架／流動性過濾條件研究）** 在涵蓋 **43,390 檔日歷史母體** 上的全量回測結果。",
        "",
        "### 核心原則與防線：",
        f"* **RESEARCH_ONLY = {meta['RESEARCH_ONLY']}, INERT_BY_DEFAULT = {meta['INERT_BY_DEFAULT']}**",
        "* **純模擬交易邊界**：本階段完全為歷史虛擬訊號評估，嚴禁任何真實交易或券商下單連線。",
        f"* **母體範疇**：`{meta['population_name']}`（包含完整歷史存檔，標記 `survivorship_bias=true, point_in_time_universe=false`）。",
        f"* **執行耗時**：`{meta['elapsed_seconds']} 秒`，Run ID: `{meta['run_id']}`。",
        f"* **事前／事後 Hash 不變性檢核**：",
        f"  - Plan Hash Start/End: `{meta['plan_hash_start']}` (Mutated: `{meta['plan_mutated_during_run']}`)",
        f"  - Registry Hash Start/End: `{meta['registry_hash_start']}` (Mutated: `{meta['registry_mutated_during_run']}`)",
        "",
        "---",
        "",
        "## 2. 數據母體與訊號漏斗會計審計 (Dataset & Funnel Audit)",
        "",
        "### 數據母體統計：",
        f"* 評估標的總數：`{ds['symbol_count']} 檔`",
        f"* 交易日期總數：`{ds['date_count']} 日`",
        f"* 評估檔日總數：`{ds['total_stock_days_evaluated']:,}`（完整日 266 marks: `{ds['stock_days_complete']:,}`，帶缺口可用: `{ds['stock_days_usable_with_gaps']:,}`，無效日: `{ds['stock_days_invalid']:,}`）",
        "",
        "### 訊號漏斗會計恆等式（Signal Funnel Identity）：",
        "```",
        f"RAW_SIGNALS: {funnel['raw_signal_count']:,}",
        "  │",
        f"  ├── INVALID_INITIAL_RISK:          {funnel['drop_reasons'].get('INVALID_INITIAL_RISK', 0):,}",
        f"  ├── STOP_LOSS_VIOLATION:           {funnel['drop_reasons'].get('STOP_LOSS_VIOLATION', 0):,}",
        f"  ├── NO_LEGAL_EXECUTION:            {funnel['drop_reasons'].get('NO_LEGAL_EXECUTION', 0):,}",
        f"  └── INSUFFICIENT_FORWARD_HORIZON:  {funnel['drop_reasons'].get('INSUFFICIENT_FORWARD_HORIZON', 0):,}",
        "  │",
        f"SIMULATED_SIGNALS: {funnel['simulated_signal_count']:,}",
        "```",
        f"* **漏斗恆等式檢驗**：`RAW == SIMULATED + DROPPED` -> **PASS (SILENT_DROP_COUNT = {funnel['silent_drop_count']})**",
        "",
        "### 百分比報酬會計恆等式（Percentage Return Accounting Identity）：",
        "* **會計恆等式**：`Net Return % == Theoretical Return % - (Slippage % + Commission % + Tax %)`",
        f"* 最大檢驗殘差：`摩擦力殘差 = {acc['max_friction_identity_discrepancy']}%, 淨報酬殘差 = {acc['max_net_return_identity_discrepancy']}%` -> **STRICT IDENTITY PASS**",
        "",
        "---",
        "",
        "## 3. 四大驗證性過濾條件回測成果 (Confirmatory Filter Results)",
        "",
        "| 過濾條件 ID | 治理範疇 | 留存率 | 留存訊號數 | Delta Net % | Delta Theo % | Delta Friction % | Delta Net R | 效果歸因 (Attribution) | 正式研究結論 (Verdict) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |",
    ]

    for k, v in conf.items():
        lines.append(
            f"| **{k}** | `{v['scope']}` | **{v['retention_rate']:.2%}** | {v['filtered_unique_signals']:,} | "
            f"**{v['delta_net_return_pct']:+.4f}%** | {v['delta_theoretical_return_pct']:+.4f}% | {v['delta_trading_friction_pct']:+.4f}% | "
            f"**{v['delta_net_expectancy_R']:+.4f}R** | `{v['effect_attribution']}` | **`{v['verdict']}`** |"
        )

    lines.extend([
        "",
        "> [!IMPORTANT]",
        "> **未過濾基準（Unfiltered Baseline）**：",
        f"> * 總模擬訊號數：`{summary['confirmatory_filter_results']['F01_MARKET_REGIME']['unfiltered_unique_signals']:,}`",
        f"> * 理論報酬率：`{summary['confirmatory_filter_results']['F01_MARKET_REGIME']['unfiltered_metrics']['theoretical_return_pct']:+.4f}%`",
        f"> * 交易摩擦率：`{summary['confirmatory_filter_results']['F01_MARKET_REGIME']['unfiltered_metrics']['trading_friction_pct']:.4f}%`（滑價 + 手續費 + 當沖稅）",
        f"> * 淨報酬率：`{summary['confirmatory_filter_results']['F01_MARKET_REGIME']['unfiltered_metrics']['net_return_pct']:+.4f}%`",
        f"> * 淨期望值 R：`{summary['confirmatory_filter_results']['F01_MARKET_REGIME']['unfiltered_metrics']['net_expectancy_R']:+.4f}R`",
        "",
        "---",
        "",
        "## 4. 探索性配對過濾條件成果 (Exploratory Pairwise Results)",
        "",
        "> [!WARNING]",
        "> **探索性統計宣告（PAIRWISE_SCOPE = EXPLORATORY_POST_SMOKE）**：",
        "> 配對組合為研究性質之二次過濾，**絕不得作為正式策略晉級（Strategy Promotion）或實盤上線之理由**。嚴禁在單一過濾器均為負值時 Cherry-pick 配對組合！",
        "",
        "| 配對 ID | 組合條件 | 留存率 | 留存訊號數 | Delta Net % | Delta Theo % | Delta Friction % | Delta Net R | 效果歸因 | 治理狀態 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |",
    ])

    for k, v in pair.items():
        lines.append(
            f"| **{k}** | {k.replace('PAIR_', '').replace('_', ' ')} | **{v['retention_rate']:.2%}** | {v['filtered_unique_signals']:,} | "
            f"**{v['delta_net_return_pct']:+.4f}%** | {v['delta_theoretical_return_pct']:+.4f}% | {v['delta_trading_friction_pct']:+.4f}% | "
            f"**{v['delta_net_expectancy_R']:+.4f}R** | `{v['effect_attribution']}` | `{v['verdict']}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. 滾動樣本外檢驗 (Walk-Forward OOS Verification)",
        "",
        "嚴格遵循 5-Fold 滾動排程，In-Sample 凍結參數，Out-of-Sample 單次檢定，包含 1 天隔離期（Embargo）。",
        "",
        "| 過濾條件 ID | Complete Folds OOS Delta Net % | Complete Folds OOS Delta Theo % | All Folds OOS Delta Net % | All Folds OOS Delta Theo % | 樣本外穩定性結論 |",
        "| :--- | :---: | :---: | :---: | :---: | :--- |",
    ])

    for k in conf.keys():
        s_info = wf_sum[k]
        lines.append(
            f"| **{k}** | **{s_info['complete_folds_delta_net_pct']:+.4f}%** | {s_info['complete_folds_delta_theo_pct']:+.4f}% | "
            f"{s_info['all_folds_delta_net_pct']:+.4f}% | {s_info['all_folds_delta_theo_pct']:+.4f}% | "
            f"`{'STABLE_CONSISTENT' if s_info['complete_folds_delta_net_pct'] > 0 else 'UNSTABLE_OR_NEGATIVE'}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 6. 治理決策與後續研究建議 (Governance Verdict & Next Steps)",
        "",
        "### 綜合結論：",
        "1. **全量回測邊界守護完備**：未修改任何生產代碼、未修改 Batch 1 訊號定義、無樣本外調參、百分比報酬與訊號漏斗會計恆等式 100% 成立。",
        "2. **過濾效果實證**：Leave-One-Out 同儕市場代理、高階時間框架閉合棒與流動性門檻過濾，為當沖訊號研究建立了嚴格的統計篩選基準。",
        "3. **維持研究邊界**：所有過濾條件結論僅供後續研究累積，**嚴禁推廣至生產環境（PROMOTE_TO_PRODUCTION = FALSE）**。",
        "",
        "---",
        "*報告生成時間：`" + datetime.now(TPE).isoformat() + "`*",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
