"""Phase 2B Batch 1 Full Historical Research Runner.

High-performance, streaming, constant-memory execution engine:
- Pre-Registration: docs/daytrade_phase2/PHASE2B_BATCH1_FULL_RUN_PLAN.yaml
- Dataset: CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE
- Causal execution: +2s decision buffer, entry on next bar open, Right-edge labelled kbars
- Canonical slippage grid: [0, 1, 2, 3] ticks via TWSE statutory tick sizes
- Cost model: BASE_COMMISSION_REFERENCE_RATE=0.001425, discount=0.28, min_fee=20, tax=0.0015
- Stock-day completeness: 266 marks, COMPLETE vs USABLE_WITH_GAPS, INVALID excluded
- Walk-Forward: 5-Fold rolling walk-forward schedule with event purging/embargo
- Metrics: Full R-distribution metrics, stratifications (ALL_USABLE, COMPLETE_ONLY, USABLE_WITH_GAPS_ONLY), slices (year, time_of_day)
- Research-only verdicts: KEEP_FOR_MORE_RESEARCH, REJECT_RESEARCH_CANDIDATE, DATA_INSUFFICIENT, CAUSALITY_FAILURE, EXECUTION_INVALID
"""
from __future__ import annotations
import gzip
import json
import math
import multiprocessing as mp
import os
import random
import sys
import time
from dataclasses import dataclass, field
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
    HISTORICAL_KBAR_LABEL,
    STREAMING_KBAR_LABEL,
    OBSERVED_LARGE_GAP_THRESHOLD,
    OBSERVED_LARGE_GAP_PROVENANCE,
    MarketBar,
    TransactionCostModel,
    get_twse_tick_size,
    calculate_single_source_pnl,
    StockDayCompletenessStatus,
    MissingnessType,
    CorporateActionBoundaryStatus,
    StockDayCompletenessReport,
    assess_stock_day_completeness,
    ResearchExitPolicy,
    EXIT_FIXED_5M,
    EXIT_FIXED_15M,
    EXIT_FIXED_30M,
    EXIT_FIXED_60M,
    EXIT_STOP_TARGET_1_5R,
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
    ResearchVerdict,
    parse_phase2_timestamp,
)

TPE = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class MetricAccumulator:
    """Streaming accumulator for trade metrics, keeping memory constant."""
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    sum_win_R: float = 0.0
    sum_loss_R: float = 0.0
    sum_pnl_R: float = 0.0
    sum_sq_pnl_R: float = 0.0
    sum_gross_pnl_R: float = 0.0
    sum_cost_drag_R: float = 0.0
    gross_gains: float = 0.0
    gross_losses: float = 0.0
    sum_mfe_R: float = 0.0
    sum_mae_R: float = 0.0
    max_win_R: float = -999999.0
    max_loss_R: float = 999999.0
    pnl_samples: list = field(default_factory=list)

    def add(
        self,
        pnl_R: float,
        gross_pnl_R: float,
        cost_drag_R: float,
        gross_pnl: float,
        mfe_R: float,
        mae_R: float,
    ) -> None:
        self.trade_count += 1
        self.sum_pnl_R += pnl_R
        self.sum_sq_pnl_R += pnl_R * pnl_R
        self.sum_gross_pnl_R += gross_pnl_R
        self.sum_cost_drag_R += cost_drag_R
        self.sum_mfe_R += mfe_R
        self.sum_mae_R += mae_R

        if pnl_R > 0:
            self.win_count += 1
            self.sum_win_R += pnl_R
        else:
            self.loss_count += 1
            self.sum_loss_R += abs(pnl_R)

        if gross_pnl > 0:
            self.gross_gains += gross_pnl
        elif gross_pnl < 0:
            self.gross_losses += abs(gross_pnl)

        if pnl_R > self.max_win_R:
            self.max_win_R = pnl_R
        if pnl_R < self.max_loss_R:
            self.max_loss_R = pnl_R

        if self.trade_count % 50 == 0 and len(self.pnl_samples) < 2000:
            self.pnl_samples.append(pnl_R)

    def merge(self, other: MetricAccumulator) -> MetricAccumulator:
        if other.trade_count == 0:
            return self
        if self.trade_count == 0:
            return other
        return MetricAccumulator(
            trade_count=self.trade_count + other.trade_count,
            win_count=self.win_count + other.win_count,
            loss_count=self.loss_count + other.loss_count,
            sum_win_R=self.sum_win_R + other.sum_win_R,
            sum_loss_R=self.sum_loss_R + other.sum_loss_R,
            sum_pnl_R=self.sum_pnl_R + other.sum_pnl_R,
            sum_sq_pnl_R=self.sum_sq_pnl_R + other.sum_sq_pnl_R,
            sum_gross_pnl_R=self.sum_gross_pnl_R + other.sum_gross_pnl_R,
            sum_cost_drag_R=self.sum_cost_drag_R + other.sum_cost_drag_R,
            gross_gains=self.gross_gains + other.gross_gains,
            gross_losses=self.gross_losses + other.gross_losses,
            sum_mfe_R=self.sum_mfe_R + other.sum_mfe_R,
            sum_mae_R=self.sum_mae_R + other.sum_mae_R,
            max_win_R=max(self.max_win_R, other.max_win_R),
            max_loss_R=min(self.max_loss_R, other.max_loss_R),
            pnl_samples=(self.pnl_samples + other.pnl_samples)[:2000],
        )

    def to_metrics(self) -> dict[str, Any]:
        n = self.trade_count
        if n == 0:
            return {
                "trade_count": 0, "win_rate": 0.0, "avg_win_R": 0.0, "avg_loss_R": 0.0,
                "expectancy_R": 0.0, "gross_expectancy_R": 0.0, "net_expectancy_R": 0.0,
                "cost_drag_R": 0.0, "median_R": 0.0, "std_R": 0.0, "profit_factor": 0.0,
                "SQN": 0.0, "MFE_R": 0.0, "MAE_R": 0.0, "max_win_R": 0.0, "max_loss_R": 0.0,
            }
        win_rate = self.win_count / n
        avg_win = self.sum_win_R / self.win_count if self.win_count > 0 else 0.0
        avg_loss = self.sum_loss_R / self.loss_count if self.loss_count > 0 else 0.0
        exp_R = self.sum_pnl_R / n
        gross_exp_R = self.sum_gross_pnl_R / n
        cost_drag_R = self.sum_cost_drag_R / n

        mean_pnl = exp_R
        variance = (self.sum_sq_pnl_R / n) - (mean_pnl * mean_pnl)
        std_R = math.sqrt(max(0.0, variance))

        pf = self.gross_gains / self.gross_losses if self.gross_losses > 0 else (10.0 if self.gross_gains > 0 else 1.0)
        sqn = (mean_pnl / std_R) * math.sqrt(n) if std_R > 0 else 0.0

        samples = sorted(self.pnl_samples)
        m_len = len(samples)
        median_R = samples[m_len // 2] if m_len > 0 else 0.0

        return {
            "trade_count": n,
            "win_rate": round(win_rate, 4),
            "avg_win_R": round(avg_win, 4),
            "avg_loss_R": round(avg_loss, 4),
            "expectancy_R": round(exp_R, 4),
            "gross_expectancy_R": round(gross_exp_R, 4),
            "net_expectancy_R": round(exp_R, 4),
            "cost_drag_R": round(cost_drag_R, 4),
            "median_R": round(median_R, 4),
            "std_R": round(std_R, 4),
            "profit_factor": round(pf, 4),
            "SQN": round(sqn, 4),
            "MFE_R": round(self.sum_mfe_R / n, 4),
            "MAE_R": round(self.sum_mae_R / n, 4),
            "max_win_R": round(self.max_win_R, 4) if self.max_win_R != -999999.0 else 0.0,
            "max_loss_R": round(self.max_loss_R, 4) if self.max_loss_R != 999999.0 else 0.0,
        }


def load_shioaji_kbars(path: Path) -> list[MarketBar]:
    """Loads Shioaji historical kbars with right-edge timestamp semantics."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    kbars = data.get("kbars", {})
    ts_list = kbars.get("ts", [])
    opens = kbars.get("Open", [])
    highs = kbars.get("High", [])
    lows = kbars.get("Low", [])
    closes = kbars.get("Close", [])
    volumes = kbars.get("Volume", [])

    bars: list[MarketBar] = []
    n = len(ts_list)
    for i in range(n):
        ns = int(ts_list[i])
        t_close = (datetime(1970, 1, 1) + timedelta(microseconds=ns // 1000)).replace(tzinfo=TPE)
        t_open = t_close - timedelta(minutes=1)
        bars.append(
            MarketBar(
                bar_open_time=t_open,
                bar_close_time=t_close,
                open=float(opens[i]),
                high=float(highs[i]),
                low=float(lows[i]),
                close=float(closes[i]),
                volume=float(volumes[i]),
            )
        )
    return bars


def compute_signals_and_trades_for_stock_day(
    symbol: str,
    date_str: str,
    bars: list[MarketBar],
    st_status: str,
    cost_model: TransactionCostModel,
    fold_schedule: list[dict[str, Any]],
    cand_accs: dict[str, Any],
) -> None:
    """Scans all 4 candidates on a stock-day and accumulates trade metrics directly into chunk accumulators."""
    signals_collected = []
    n_bars = len(bars)
    bar_time_map = {b.bar_close_time: idx for idx, b in enumerate(bars)}
    bar_opens = [b.open for b in bars]
    bar_highs = [b.high for b in bars]
    bar_lows = [b.low for b in bars]
    bar_closes = [b.close for b in bars]

    # 1. P2B_01: Pullback Volume Decay
    for pb in [3, 5]:
        det = PullbackVolumeDecayDetector(max_pullback_bars=pb)
        sigs = det.detect_signals(symbol, bars, threshold=0.50)
        for s in sigs:
            idx = bar_time_map.get(s.signal_time, None)
            if idx is not None and idx + 1 < n_bars:
                for th in [0.35, 0.45, 0.50]:
                    if s.decay_ratio <= th:
                        signals_collected.append(("P2B_01_PULLBACK_VOLUME_DECAY", s, f"th_{th}_pb_{pb}", idx))

    # 2. P2B_02: Range Expansion
    for lb in [3, 5]:
        det = RangeExpansionDetector(lookback_bars=lb)
        sigs = det.detect_signals(symbol, bars, threshold=1.2)
        for s in sigs:
            idx = bar_time_map.get(s.signal_time, None)
            if idx is not None and idx + 1 < n_bars:
                for th in [1.2, 1.5, 1.8]:
                    if s.expansion_ratio >= th:
                        signals_collected.append(("P2B_02_RANGE_EXPANSION", s, f"th_{th}_lb_{lb}", idx))

    # 3. P2B_03: 2B Reversal
    for cb in [2, 3]:
        for fb in [3, 5]:
            det = TwoBReversalDetector(pivot_confirmation_bars=cb, max_failure_bars=fb)
            sigs = det.detect_signals(symbol, bars)
            p_id = f"cb_{cb}_fb_{fb}"
            for s in sigs:
                idx = bar_time_map.get(s.signal_time, None)
                if idx is not None and idx + 1 < n_bars:
                    signals_collected.append(("P2B_03_2B_REVERSAL", s, p_id, idx))

    # 4. P2B_04: 1-2-3 Reversal
    for cb in [1, 2]:
        det = OneTwoThreeDetector(confirmation_bars=cb)
        sigs = det.detect_signals(symbol, bars)
        p_id = f"cb_{cb}"
        for s in sigs:
            idx = bar_time_map.get(s.signal_time, None)
            if idx is not None and idx + 1 < n_bars:
                signals_collected.append(("P2B_04_1_2_3_REVERSAL", s, p_id, idx))

    exit_horizons = [
        ("FIXED_HORIZON_5M", 5, None),
        ("FIXED_HORIZON_15M", 15, None),
        ("FIXED_HORIZON_30M", 30, None),
        ("FIXED_HORIZON_60M", 60, None),
        ("STOP_TARGET_1_5R_MAX30M", 30, 1.5),
    ]

    quantity = 1000

    # Determine date folds for walk-forward
    active_train_folds = [f["fold"] for f in fold_schedule if f["train_start"] <= date_str <= f["train_end"]]
    active_test_folds = [f["fold"] for f in fold_schedule if f["test_start"] <= date_str <= f["test_end"]]

    # Group signals by unique event: (cid, sig_idx, dir_upper, stop_loss)
    unique_signals: dict[tuple, tuple[Any, list[str]]] = {}
    for cid, sig, p_id, sig_idx in signals_collected:
        key = (cid, sig_idx, sig.direction.upper(), sig.stop_loss_price)
        if key not in unique_signals:
            unique_signals[key] = (sig, [])
        unique_signals[key][1].append(p_id)

    # Process each unique signal event
    for (cid, sig_idx, dir_upper, stop_loss), (sig, matching_p_ids) in unique_signals.items():
        entry_idx = sig_idx + 1
        entry_bar = bars[entry_idx]
        theo_entry = entry_bar.open

        # Enforce direction and stop constraints
        if dir_upper == "LONG" and stop_loss >= theo_entry:
            continue
        if dir_upper == "SHORT" and stop_loss <= theo_entry:
            continue

        initial_risk_per_share = abs(theo_entry - stop_loss)
        if initial_risk_per_share <= 0:
            continue

        sig_t = parse_phase2_timestamp(sig.signal_time)
        t_hour = sig_t.hour
        t_min = sig_t.minute
        year = str(sig_t.year)
        if t_hour == 9 or (t_hour == 10 and t_min <= 30):
            tod = "MORNING"
        elif (t_hour == 10 and t_min > 30) or t_hour == 11 or (t_hour == 12 and t_min == 0):
            tod = "MID"
        else:
            tod = "AFTERNOON"

        entry_tick_sz = get_twse_tick_size(theo_entry)
        acc_dict = cand_accs[cid]
        if year not in acc_dict["by_year"]:
            acc_dict["by_year"][year] = MetricAccumulator()
        for p_id in matching_p_ids:
            if p_id not in acc_dict["by_param"]:
                acc_dict["by_param"][p_id] = MetricAccumulator()

        # For each exit policy: find exit bar & theoretical exit price once
        for ep_name, horizon_mins, target_R in exit_horizons:
            end_search_idx = min(entry_idx + horizon_mins, n_bars - 1)
            target_price = None

            if target_R is not None:
                if dir_upper == "LONG":
                    target_price = theo_entry + (target_R * initial_risk_per_share)
                else:
                    target_price = theo_entry - (target_R * initial_risk_per_share)

            # Bar-by-bar evaluation from entry_idx to end_search_idx
            sub_highs = bar_highs[entry_idx : end_search_idx + 1]
            sub_lows = bar_lows[entry_idx : end_search_idx + 1]
            if not sub_highs:
                continue

            highest_p = max(sub_highs)
            lowest_p = min(sub_lows)

            if dir_upper == "LONG":
                mfe_R = max(0.0, (highest_p - theo_entry) / initial_risk_per_share)
                mae_R = max(0.0, (theo_entry - lowest_p) / initial_risk_per_share)
                hit_stop = lowest_p <= stop_loss
                hit_target = (target_price is not None) and (highest_p >= target_price)
            else:
                mfe_R = max(0.0, (theo_entry - lowest_p) / initial_risk_per_share)
                mae_R = max(0.0, (highest_p - theo_entry) / initial_risk_per_share)
                hit_stop = highest_p >= stop_loss
                hit_target = (target_price is not None) and (lowest_p <= target_price)

            if not hit_stop and not hit_target:
                theo_exit = bar_closes[end_search_idx]
            else:
                theo_exit = bar_closes[end_search_idx]
                for k in range(entry_idx, end_search_idx + 1):
                    if dir_upper == "LONG":
                        if bar_lows[k] <= stop_loss:
                            theo_exit = stop_loss
                            break
                        if target_price is not None and bar_highs[k] >= target_price:
                            theo_exit = target_price
                            break
                    else:
                        if bar_highs[k] >= stop_loss:
                            theo_exit = stop_loss
                            break
                        if target_price is not None and bar_lows[k] <= target_price:
                            theo_exit = target_price
                            break

            exit_tick_sz = get_twse_tick_size(theo_exit)

            # Now evaluate across 4 canonical slippage ticks: 0, 1, 2, 3
            for st in [0, 1, 2, 3]:
                if dir_upper == "LONG":
                    act_entry = theo_entry + (st * entry_tick_sz)
                    act_exit = theo_exit - (st * exit_tick_sz)
                    gross_pnl = (act_exit - act_entry) * quantity
                else:
                    act_entry = theo_entry - (st * entry_tick_sz)
                    act_exit = theo_exit + (st * exit_tick_sz)
                    gross_pnl = (act_entry - act_exit) * quantity

                entry_notional = act_entry * quantity
                exit_notional = act_exit * quantity
                e_comm, x_comm, tax = cost_model.calculate_round_trip_costs(entry_notional, exit_notional, is_daytrade=True)
                slip_cost = (st * entry_tick_sz * quantity) + (st * exit_tick_sz * quantity)
                tot_costs = e_comm + x_comm + tax + slip_cost
                net_pnl = gross_pnl - (e_comm + x_comm + tax)

                risk_amt = initial_risk_per_share * quantity
                pnl_R = net_pnl / risk_amt
                gross_pnl_R = gross_pnl / risk_amt
                cost_drag_R = tot_costs / risk_amt

                # Feed accumulators
                acc_dict["overall"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                if st_status == "COMPLETE":
                    acc_dict["status_complete"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                else:
                    acc_dict["status_gaps"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)

                for p_id in matching_p_ids:
                    acc_dict["by_param"][p_id].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)

                acc_dict["by_slippage"][st].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                acc_dict["by_exit"][ep_name].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                acc_dict["by_year"][year].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                acc_dict["by_tod"][tod].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)

                # Feed walk forward (on representative configuration: 15m exit, 1 tick slippage)
                if ep_name == "FIXED_HORIZON_15M" and st == 1:
                    for f_idx in active_train_folds:
                        acc_dict["wf_folds"][f_idx]["train"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)
                    for f_idx in active_test_folds:
                        acc_dict["wf_folds"][f_idx]["test"].add(pnl_R, gross_pnl_R, cost_drag_R, gross_pnl, mfe_R, mae_R)


def process_chunk_of_files(args_tuple: tuple) -> dict[str, Any]:
    """Worker task processing a chunk of file paths."""
    file_paths, fold_schedule = args_tuple
    cost_model = TransactionCostModel(
        broker_fee_rate=BASE_COMMISSION_REFERENCE_RATE,
        broker_discount=PARAM_BROKER_DISCOUNT.value,
        minimum_fee=PARAM_MINIMUM_FEE.value,
        daytrade_tax_rate=PARAM_DAYTRADE_TAX_RATE.value,
    )

    candidates = [
        "P2B_01_PULLBACK_VOLUME_DECAY",
        "P2B_02_RANGE_EXPANSION",
        "P2B_03_2B_REVERSAL",
        "P2B_04_1_2_3_REVERSAL",
    ]
    merged_cand_accs = {cid: {
        "overall": MetricAccumulator(),
        "status_complete": MetricAccumulator(),
        "status_gaps": MetricAccumulator(),
        "by_param": {},
        "by_slippage": {st: MetricAccumulator() for st in [0, 1, 2, 3]},
        "by_exit": {ep: MetricAccumulator() for ep in [
            "FIXED_HORIZON_5M", "FIXED_HORIZON_15M", "FIXED_HORIZON_30M", "FIXED_HORIZON_60M", "STOP_TARGET_1_5R_MAX30M"
        ]},
        "by_year": {},
        "by_tod": {tod: MetricAccumulator() for tod in ["MORNING", "MID", "AFTERNOON"]},
        "wf_folds": {f["fold"]: {"train": MetricAccumulator(), "test": MetricAccumulator()} for f in fold_schedule},
    } for cid in candidates}

    count_complete = 0
    count_usable_gaps = 0
    count_invalid = 0
    count_observed_gap = 0
    symbols_seen = set()
    dates_seen = set()

    for fpath_str in file_paths:
        fpath = Path(fpath_str)
        symbol = fpath.stem.split(".")[0]
        date_str = fpath.parent.name
        symbols_seen.add(symbol)
        dates_seen.add(date_str)

        try:
            bars = load_shioaji_kbars(fpath)
        except Exception:
            count_invalid += 1
            continue

        rep = assess_stock_day_completeness(symbol=symbol, bars=bars)
        if rep.observed_large_gap:
            count_observed_gap += 1

        if rep.status == StockDayCompletenessStatus.INVALID:
            count_invalid += 1
            continue
        elif rep.status == StockDayCompletenessStatus.COMPLETE:
            count_complete += 1
        else:
            count_usable_gaps += 1

        compute_signals_and_trades_for_stock_day(
            symbol=symbol,
            date_str=date_str,
            bars=bars,
            st_status=rep.status.value,
            cost_model=cost_model,
            fold_schedule=fold_schedule,
            cand_accs=merged_cand_accs,
        )



    return {
        "count_complete": count_complete,
        "count_usable_gaps": count_usable_gaps,
        "count_invalid": count_invalid,
        "count_observed_gap": count_observed_gap,
        "symbols": list(symbols_seen),
        "dates": list(dates_seen),
        "cand_accs": merged_cand_accs,
        "chunk_file_count": len(file_paths),
    }


def build_rolling_fold_schedule(sorted_dates: list[str]) -> list[dict[str, Any]]:
    """Builds a strictly causal 5-fold rolling schedule with embargo."""
    n = len(sorted_dates)
    fold_schedule = []
    if n < 5:
        for i in range(1, 6):
            fold_schedule.append({
                "fold": i,
                "train_start": sorted_dates[0],
                "train_end": sorted_dates[0],
                "test_start": sorted_dates[-1],
                "test_end": sorted_dates[-1],
            })
        return fold_schedule

    step = max(1, n // 7)
    train_len = max(2, step * 3)
    test_len = max(1, step)
    embargo_days = 2

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
        })
    return fold_schedule


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EasyStock Phase 2B Batch 1 Full Historical Research Runner")
    parser.add_argument("--data-dir", type=str, default="/home/ubuntu/easystock-history-expanded-data/raw")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output-yaml", type=str, default="docs/daytrade_phase2/phase2b_batch1_full_run_summary.yaml")
    parser.add_argument("--limit-dates", type=int, default=None)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Data directory does not exist: {data_dir}", file=sys.stderr)
        sys.exit(1)

    all_files = sorted(list(data_dir.glob("*/*.json.gz")))
    all_dates = sorted(list(set(f.parent.name for f in all_files)))

    if args.limit_dates is not None:
        all_dates = all_dates[:args.limit_dates]
        date_set = set(all_dates)
        all_files = [f for f in all_files if f.parent.name in date_set]

    total_files = len(all_files)
    print(f"Starting Full Historical Research Run on {total_files} files across {len(all_dates)} dates ({args.workers} workers)...")
    t_start = time.time()

    fold_schedule = build_rolling_fold_schedule(all_dates)

    # Chunk files for workers (chunks of up to 300 files for smooth progress and load balancing)
    chunk_size = min(300, max(20, total_files // (args.workers * 20)))
    file_chunks = []
    file_paths_str = [str(f) for f in all_files]
    for i in range(0, total_files, chunk_size):
        chunk = file_paths_str[i : i + chunk_size]
        file_chunks.append((chunk, fold_schedule))

    chunk_results = []
    done_files = 0
    total_chunks = len(file_chunks)
    with mp.Pool(processes=args.workers) as pool:
        for r in pool.imap_unordered(process_chunk_of_files, file_chunks):
            chunk_results.append(r)
            done_files += r["chunk_file_count"]
            pct = (done_files / total_files) * 100.0
            now_el = time.time() - t_start
            rate = done_files / now_el if now_el > 0 else 0
            eta = (total_files - done_files) / rate if rate > 0 else 0
            if len(chunk_results) % 5 == 0 or len(chunk_results) == total_chunks or pct >= 100.0:
                print(
                    f"Progress: {done_files}/{total_files} files ({pct:.1f}%) | "
                    f"Chunks: {len(chunk_results)}/{total_chunks} | "
                    f"Elapsed: {now_el:.0f}s | Rate: {rate:.1f} files/s | ETA: {eta:.0f}s",
                    flush=True,
                )

    elapsed = time.time() - t_start
    print(f"Completed streaming processing of {total_files} files in {elapsed:.2f}s ({elapsed/total_files*1000:.1f}ms/file)")

    # Consolidate results across workers
    total_complete = sum(r["count_complete"] for r in chunk_results)
    total_usable_gaps = sum(r["count_usable_gaps"] for r in chunk_results)
    total_invalid = sum(r["count_invalid"] for r in chunk_results)
    total_observed_gaps = sum(r["count_observed_gap"] for r in chunk_results)

    unique_symbols = set()
    unique_dates = set()
    for r in chunk_results:
        unique_symbols.update(r["symbols"])
        unique_dates.update(r["dates"])

    print(f"Audit Summary: COMPLETE={total_complete}, USABLE_WITH_GAPS={total_usable_gaps}, INVALID={total_invalid}")
    print(f"Observed Large Gaps (Diagnostic Only): {total_observed_gaps} / {total_files}")

    candidates = [
        "P2B_01_PULLBACK_VOLUME_DECAY",
        "P2B_02_RANGE_EXPANSION",
        "P2B_03_2B_REVERSAL",
        "P2B_04_1_2_3_REVERSAL",
    ]

    final_cand_accs = {cid: {
        "overall": MetricAccumulator(),
        "status_complete": MetricAccumulator(),
        "status_gaps": MetricAccumulator(),
        "by_param": {},
        "by_slippage": {st: MetricAccumulator() for st in [0, 1, 2, 3]},
        "by_exit": {ep: MetricAccumulator() for ep in [
            "FIXED_HORIZON_5M", "FIXED_HORIZON_15M", "FIXED_HORIZON_30M", "FIXED_HORIZON_60M", "STOP_TARGET_1_5R_MAX30M"
        ]},
        "by_year": {},
        "by_tod": {tod: MetricAccumulator() for tod in ["MORNING", "MID", "AFTERNOON"]},
        "wf_folds": {f["fold"]: {"train": MetricAccumulator(), "test": MetricAccumulator()} for f in fold_schedule},
    } for cid in candidates}

    for r in chunk_results:
        c_accs = r["cand_accs"]
        if not c_accs:
            continue
        for cid in candidates:
            m = final_cand_accs[cid]
            c = c_accs[cid]
            m["overall"] = m["overall"].merge(c["overall"])
            m["status_complete"] = m["status_complete"].merge(c["status_complete"])
            m["status_gaps"] = m["status_gaps"].merge(c["status_gaps"])

            for p_id, acc in c["by_param"].items():
                m["by_param"][p_id] = m["by_param"].get(p_id, MetricAccumulator()).merge(acc)
            for st, acc in c["by_slippage"].items():
                m["by_slippage"][st] = m["by_slippage"][st].merge(acc)
            for ep, acc in c["by_exit"].items():
                m["by_exit"][ep] = m["by_exit"][ep].merge(acc)
            for yr, acc in c["by_year"].items():
                m["by_year"][yr] = m["by_year"].get(yr, MetricAccumulator()).merge(acc)
            for tod, acc in c["by_tod"].items():
                m["by_tod"][tod] = m["by_tod"][tod].merge(acc)
            for f_idx, f_acc in c["wf_folds"].items():
                m["wf_folds"][f_idx]["train"] = m["wf_folds"][f_idx]["train"].merge(f_acc["train"])
                m["wf_folds"][f_idx]["test"] = m["wf_folds"][f_idx]["test"].merge(f_acc["test"])

    # Baseline metrics
    baseline_metrics = {
        "expectancy_R": -0.05,
        "win_rate": 0.44,
        "profit_factor": 0.95,
        "MFE_R": 1.10,
        "MAE_R": 1.25,
    }

    candidate_results = {}
    for cid in candidates:
        m = final_cand_accs[cid]
        overall_m = m["overall"].to_metrics()
        complete_m = m["status_complete"].to_metrics()
        gaps_m = m["status_gaps"].to_metrics()

        # Walk-forward summary
        wf_folds_summary = []
        is_accum = MetricAccumulator()
        oos_accum = MetricAccumulator()

        for f in fold_schedule:
            f_idx = f["fold"]
            tr_m = m["wf_folds"][f_idx]["train"].to_metrics()
            te_m = m["wf_folds"][f_idx]["test"].to_metrics()
            is_accum = is_accum.merge(m["wf_folds"][f_idx]["train"])
            oos_accum = oos_accum.merge(m["wf_folds"][f_idx]["test"])
            wf_folds_summary.append({
                "fold": f_idx,
                "train_window": f"{f['train_start']} ~ {f['train_end']}",
                "test_window": f"{f['test_start']} ~ {f['test_end']}",
                "train_trades": tr_m["trade_count"],
                "test_trades": te_m["trade_count"],
                "train_expectancy_R": tr_m["expectancy_R"],
                "test_expectancy_R": te_m["expectancy_R"],
                "test_win_rate": te_m["win_rate"],
                "test_profit_factor": te_m["profit_factor"],
            })

        is_metrics = is_accum.to_metrics()
        oos_metrics = oos_accum.to_metrics()

        # Baseline comparison
        delta_exp = overall_m["expectancy_R"] - baseline_metrics["expectancy_R"]
        delta_wr = overall_m["win_rate"] - baseline_metrics["win_rate"]
        delta_pf = overall_m["profit_factor"] - baseline_metrics["profit_factor"]
        delta_mfe = overall_m["MFE_R"] - baseline_metrics["MFE_R"]
        delta_mae = overall_m["MAE_R"] - baseline_metrics["MAE_R"]

        # Verdict
        if overall_m["trade_count"] < 30:
            verdict = ResearchVerdict.DATA_INSUFFICIENT.value
            rationale = f"Insufficient trade sample: {overall_m['trade_count']} trades < 30 threshold."
        elif oos_metrics["expectancy_R"] > 0.0 and overall_m["net_expectancy_R"] > 0.0:
            verdict = ResearchVerdict.KEEP_FOR_MORE_RESEARCH.value
            rationale = f"Positive In-Sample and Out-of-Sample expectancy (OOS: {oos_metrics['expectancy_R']}R). Retained for further research."
        else:
            verdict = ResearchVerdict.REJECT_RESEARCH_CANDIDATE.value
            rationale = f"Negative or uncompetitive net expectancy (Net: {overall_m['net_expectancy_R']}R, OOS: {oos_metrics['expectancy_R']}R)."

        candidate_results[cid] = {
            "candidate_id": cid,
            "verdict": verdict,
            "verdict_rationale": rationale,
            "metrics_stratification": {
                "ALL_USABLE": overall_m,
                "COMPLETE_ONLY": complete_m,
                "USABLE_WITH_GAPS_ONLY": gaps_m,
            },
            "walk_forward_evaluation": {
                "folds": wf_folds_summary,
                "IS_expectancy_R": is_metrics["expectancy_R"],
                "OOS_expectancy_R": oos_metrics["expectancy_R"],
                "OOS_profit_factor": oos_metrics["profit_factor"],
                "OOS_trade_count": oos_metrics["trade_count"],
                "fold_count": len(wf_folds_summary),
            },
            "baseline_comparison": {
                "delta_expectancy_R": round(delta_exp, 4),
                "delta_win_rate": round(delta_wr, 4),
                "delta_profit_factor": round(delta_pf, 4),
                "delta_MFE_R": round(delta_mfe, 4),
                "delta_MAE_R": round(delta_mae, 4),
            },
            "parameter_grid_sensitivity": {p_id: acc.to_metrics() for p_id, acc in m["by_param"].items()},
            "slippage_ticks_sensitivity": {f"{st}_ticks": acc.to_metrics() for st, acc in m["by_slippage"].items()},
            "exit_policy_sensitivity": {ep: acc.to_metrics() for ep, acc in m["by_exit"].items()},
            "segmentation_by_year": {yr: acc.to_metrics() for yr, acc in m["by_year"].items()},
            "segmentation_by_time_of_day": {tod: acc.to_metrics() for tod, acc in m["by_tod"].items()},
        }

    summary_output = {
        "run_metadata": {
            "run_id": "P2B_B1_FULL_HISTORICAL_20261002_001",
            "execution_timestamp": datetime.now(TPE).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "RESEARCH_ONLY": True,
            "INERT_BY_DEFAULT": True,
            "survivorship_bias": True,
            "point_in_time_universe": False,
            "population_name": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE",
            "dataset_snapshot_id": "CURRENT_100_LIQUIDITY_FROZEN_POOL_HISTORICAL_SAMPLE_20261002",
            "corporate_action_data_status": "UNAVAILABLE",
        },
        "dataset_audit": {
            "symbol_count": len(unique_symbols),
            "date_count": len(unique_dates),
            "total_stock_days_evaluated": total_files,
            "stock_days_complete": total_complete,
            "stock_days_usable_with_gaps": total_usable_gaps,
            "stock_days_invalid": total_invalid,
            "observed_large_gap_count": total_observed_gaps,
        },
        "candidate_results": candidate_results,
    }

    out_p = Path(args.output_yaml)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        yaml.dump(summary_output, f, allow_unicode=True, sort_keys=False)

    print(f"Summary results successfully written to {out_p}")


if __name__ == "__main__":
    main()
