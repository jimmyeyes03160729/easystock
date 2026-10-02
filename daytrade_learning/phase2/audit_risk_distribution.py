"""Phase 2B Batch 1 Diagnostic: Initial Risk Distribution Audit.

Computes exact risk denominator distribution across candidate signals:
- initial_risk_pct: |entry - stop| / entry * 100%
- initial_risk_ticks: |entry - stop| / tick_size
- signals_with_risk_lt_1_tick
- signals_with_risk_lt_2_ticks
- signals_with_risk_lt_round_trip_cost
"""
from __future__ import annotations
import gzip
import json
import math
import multiprocessing as mp
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

from daytrade_learning.phase2 import (
    MarketBar,
    get_twse_tick_size,
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
    BASE_COMMISSION_REFERENCE_RATE,
    PARAM_BROKER_DISCOUNT,
    PARAM_DAYTRADE_TAX_RATE,
)

TPE = timezone(timedelta(hours=8))


def calc_percentile(arr: list[float], p: float) -> float:
    if not arr:
        return 0.0
    arr_sorted = sorted(arr)
    k = (len(arr_sorted) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return arr_sorted[int(k)]
    return arr_sorted[int(f)] * (c - k) + arr_sorted[int(c)] * (k - f)


def load_shioaji_kbars(path: Path) -> list[MarketBar]:
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


def audit_chunk(file_paths: list[str]) -> dict[str, Any]:
    # candidates: P2B_01, P2B_02, P2B_03, P2B_04
    # Store list of (risk_pct, risk_ticks, lt_1tick, lt_2ticks, lt_cost)
    cand_data = {
        "P2B_01": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_02": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_03": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_04": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
    }

    fee_rate = BASE_COMMISSION_REFERENCE_RATE * PARAM_BROKER_DISCOUNT.value * 2.0
    tax_rate = PARAM_DAYTRADE_TAX_RATE.value

    for fpath_str in file_paths:
        fpath = Path(fpath_str)
        symbol = fpath.stem.split(".")[0]
        try:
            bars = load_shioaji_kbars(fpath)
        except Exception:
            continue
        if len(bars) < 10:
            continue

        n_bars = len(bars)
        bar_time_map = {b.bar_close_time: idx for idx, b in enumerate(bars)}

        # 1. P2B_01
        sigs_01 = set()
        for pb in [3, 5]:
            det = PullbackVolumeDecayDetector(max_pullback_bars=pb)
            for s in det.detect_signals(symbol, bars, threshold=0.50):
                idx = bar_time_map.get(s.signal_time, None)
                if idx is not None and idx + 1 < n_bars:
                    sigs_01.add((idx, s.direction.upper(), s.stop_loss_price))

        # 2. P2B_02
        sigs_02 = set()
        for lb in [3, 5]:
            det = RangeExpansionDetector(lookback_bars=lb)
            for s in det.detect_signals(symbol, bars, threshold=1.2):
                idx = bar_time_map.get(s.signal_time, None)
                if idx is not None and idx + 1 < n_bars:
                    sigs_02.add((idx, s.direction.upper(), s.stop_loss_price))

        # 3. P2B_03
        sigs_03 = set()
        for cb in [2, 3]:
            for fb in [3, 5]:
                det = TwoBReversalDetector(pivot_confirmation_bars=cb, max_failure_bars=fb)
                for s in det.detect_signals(symbol, bars):
                    idx = bar_time_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        sigs_03.add((idx, s.direction.upper(), s.stop_loss_price))

        # 4. P2B_04
        sigs_04 = set()
        for cb in [1, 2]:
            det = OneTwoThreeDetector(confirmation_bars=cb)
            for s in det.detect_signals(symbol, bars):
                idx = bar_time_map.get(s.signal_time, None)
                if idx is not None and idx + 1 < n_bars:
                    sigs_04.add((idx, s.direction.upper(), s.stop_loss_price))

        all_cands = [
            ("P2B_01", sigs_01),
            ("P2B_02", sigs_02),
            ("P2B_03", sigs_03),
            ("P2B_04", sigs_04),
        ]

        for ckey, sigs in all_cands:
            c_dict = cand_data[ckey]
            for sig_idx, dir_upper, stop_loss in sigs:
                entry_bar = bars[sig_idx + 1]
                theo_entry = entry_bar.open
                if dir_upper == "LONG" and stop_loss >= theo_entry:
                    continue
                if dir_upper == "SHORT" and stop_loss <= theo_entry:
                    continue

                risk = abs(theo_entry - stop_loss)
                if risk <= 0:
                    continue

                tick_sz = get_twse_tick_size(theo_entry)
                risk_pct = (risk / theo_entry) * 100.0
                risk_ticks = risk / tick_sz

                # 1 tick adverse slippage on entry + exit (2 ticks total) + fee + tax
                # statutory friction in price units
                round_trip_friction = (2 * tick_sz) + (theo_entry * (fee_rate + tax_rate))

                c_dict["total"] += 1
                c_dict["risk_pct"].append(risk_pct)
                c_dict["risk_ticks"].append(risk_ticks)

                if risk_ticks < 1.0:
                    c_dict["lt_1"] += 1
                if risk_ticks < 2.0:
                    c_dict["lt_2"] += 1
                if risk < round_trip_friction:
                    c_dict["lt_cost"] += 1

    return cand_data


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="/home/ubuntu/easystock-history-expanded-data/raw")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit-dates", type=int, default=None)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    all_files = sorted(list(data_dir.glob("*/*.json.gz")))
    all_dates = sorted(list(set(f.parent.name for f in all_files)))
    if args.limit_dates:
        all_dates = all_dates[:args.limit_dates]
        d_set = set(all_dates)
        all_files = [f for f in all_files if f.parent.name in d_set]

    total_files = len(all_files)
    print(f"Auditing Initial Risk Distribution across {total_files} files ({len(all_dates)} dates)...", flush=True)

    chunk_size = 200
    file_paths = [str(f) for f in all_files]
    chunks = [file_paths[i:i+chunk_size] for i in range(0, total_files, chunk_size)]

    with mp.Pool(args.workers) as pool:
        results = pool.map(audit_chunk, chunks)

    # Consolidate
    merged = {
        "P2B_01": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_02": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_03": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
        "P2B_04": {"risk_pct": [], "risk_ticks": [], "lt_1": 0, "lt_2": 0, "lt_cost": 0, "total": 0},
    }

    for r in results:
        for cid in merged:
            merged[cid]["total"] += r[cid]["total"]
            merged[cid]["lt_1"] += r[cid]["lt_1"]
            merged[cid]["lt_2"] += r[cid]["lt_2"]
            merged[cid]["lt_cost"] += r[cid]["lt_cost"]
            # Subsample to keep memory flat
            merged[cid]["risk_pct"].extend(r[cid]["risk_pct"][::5])
            merged[cid]["risk_ticks"].extend(r[cid]["risk_ticks"][::5])

    print("\n" + "="*80)
    print("INITIAL RISK DISTRIBUTION AUDIT REPORT")
    print("="*80)

    for cid in ["P2B_01", "P2B_02", "P2B_03", "P2B_04"]:
        c = merged[cid]
        tot = c["total"]
        pcts = c["risk_pct"]
        ticks = c["risk_ticks"]

        p10_pct = calc_percentile(pcts, 10)
        p25_pct = calc_percentile(pcts, 25)
        med_pct = calc_percentile(pcts, 50)
        p75_pct = calc_percentile(pcts, 75)
        p90_pct = calc_percentile(pcts, 90)

        p10_tk = calc_percentile(ticks, 10)
        p25_tk = calc_percentile(ticks, 25)
        med_tk = calc_percentile(ticks, 50)

        print(f"\nCandidate: {cid} (Unique Signals = {tot:,})")
        print(f"  Risk % Distribution:")
        print(f"    p10:    {p10_pct:.4f}%")
        print(f"    p25:    {p25_pct:.4f}%")
        print(f"    median: {med_pct:.4f}%")
        print(f"    p75:    {p75_pct:.4f}%")
        print(f"    p90:    {p90_pct:.4f}%")
        print(f"  Risk Ticks Distribution:")
        print(f"    p10:    {p10_tk:.2f} ticks")
        print(f"    p25:    {p25_tk:.2f} ticks")
        print(f"    median: {med_tk:.2f} ticks")
        print(f"  Small-Denominator Vulnerability Counts:")
        print(f"    Risk < 1 tick:             {c['lt_1']:,} ({c['lt_1']/tot*100.0:.2f}%)")
        print(f"    Risk < 2 ticks:            {c['lt_2']:,} ({c['lt_2']/tot*100.0:.2f}%)")
        print(f"    Risk < Round-Trip Friction:{c['lt_cost']:,} ({c['lt_cost']/tot*100.0:.2f}%)")


if __name__ == "__main__":
    main()
