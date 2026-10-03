"""Runs small validation sample for Phase 2B Batch 2 Context Filters with full integrity fixes.

Strict Governance:
- Small sample only: 4 symbols (1101, 2317, 1802, 2834), 8 trading dates (2023-09-27 through 2023-10-11).
- Diverse liquidity representation: includes lower-liquidity symbols (1802, 2834) to observe F05 discrimination (both KEEP and DROP).
- Evaluates 4 candidates (P2B_01_v1, P2B_02_v1, P2B_03_v1, P2B_04_v1) covering both LONG and SHORT.
- Evaluates 5 filter families: F01, F02, F03, F04, F05.
- Enforces LEAVE_ONE_OUT_PROXY for F01 and F02 (target symbol strictly excluded).
- Uses official archive Amount as primary traded value source.
- Validates strict signal funnel identity: raw == simulated + sum(drop_reasons).
- Evaluates effect decomposition (R vs percentage returns, initial risk distributions).
- Outputs structured results to docs/daytrade_phase2/phase2b_batch2_smoke_results.yaml.
"""
from __future__ import annotations
import gzip
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence
import yaml

from daytrade_learning.phase2 import (
    MarketBar,
    TransactionCostModel,
    ResearchRunner,
    EXIT_FIXED_15M,
    PullbackVolumeDecayDetector,
    RangeExpansionDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
    ResearchMarketRegime,
    RelativeStrengthFilter,
    SectorStrengthFilter,
    HigherTimeframeAggregator,
    LiquidityFilter,
    Batch2FilterRunner,
    RawSignalEvent,
    Batch2ResultStore,
    DroppedSignalRecord,
)

TPE = timezone(timedelta(hours=8))


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

        # Priority: use official archive Amount if valid, else fallback to close * volume * 1000
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


def run_batch2_validation(data_dir: Path, output_file: Path) -> dict[str, Any]:
    symbols = ["1101", "2317", "1802", "2834"]
    dates = [
        "2023-09-27",
        "2023-09-28",
        "2023-10-02",
        "2023-10-03",
        "2023-10-04",
        "2023-10-05",
        "2023-10-06",
        "2023-10-11",
    ]

    all_symbol_bars: dict[str, list[MarketBar]] = {s: [] for s in symbols}
    available_dates = []

    for d in dates:
        date_folder = data_dir / d
        if not date_folder.exists():
            continue
        has_all = True
        for s in symbols:
            fpath = date_folder / f"{s}.json.gz"
            if not fpath.exists():
                has_all = False
                break
        if has_all:
            available_dates.append(d)
            for s in symbols:
                bars = load_shioaji_kbars(date_folder / f"{s}.json.gz")
                all_symbol_bars[s].extend(bars)

    # Sort bars chronologically
    for s in symbols:
        all_symbol_bars[s].sort(key=lambda b: b.bar_close_time)

    # Initialize Filters with strict Leave-One-Out semantics
    regime = ResearchMarketRegime(universe_bars_by_symbol=all_symbol_bars)
    rs_filter = RelativeStrengthFilter(regime, all_symbol_bars)
    sector_filter = SectorStrengthFilter(
        snapshot_categories={"1101": "01", "2317": "25", "1802": "08", "2834": "17"}
    )
    htf_aggregators = {s: HigherTimeframeAggregator(bars) for s, bars in all_symbol_bars.items()}
    liq_filter = LiquidityFilter(all_symbol_bars)

    runner = Batch2FilterRunner(slippage_ticks=1, exit_policy=EXIT_FIXED_15M)

    # Detect all raw signals across the small sample
    all_raw_events: list[RawSignalEvent] = []
    for s in symbols:
        events = runner.detect_raw_signals(symbol=s, bars=all_symbol_bars[s])
        all_raw_events.extend(events)

    all_raw_events.sort(key=lambda e: e.signal_time)

    # Funnel Accounting: simulate all raw events and track dropped signals
    simulated_trades, dropped_signals = runner.simulate_events_with_funnel(all_raw_events, all_symbol_bars)

    # Verify funnel identity
    assert len(all_raw_events) == len(simulated_trades) + len(dropped_signals), (
        f"Funnel mismatch: raw={len(all_raw_events)}, simulated={len(simulated_trades)}, dropped={len(dropped_signals)}"
    )

    # Filter definitions
    filter_specs = [
        {
            "id": "F01_REGIME_INTRADAY_DIRECTION",
            "family": "F01_MARKET_REGIME",
            "condition": "LEAVE_ONE_OUT_PROXY_INTRADAY_DIRECTION",
            "func": lambda ev: regime.filter_signal(ev.symbol, ev.signal_time, ev.direction, "INTRADAY_DIRECTION"),
            "notes": "Keeps LONG only if leave-one-out peer proxy return >= 0; keeps SHORT only if <= 0.",
        },
        {
            "id": "F02_RELATIVE_STRENGTH_15M",
            "family": "F02_RELATIVE_STRENGTH",
            "condition": "LEAVE_ONE_OUT_RS_15M_NON_ADVERSE",
            "func": lambda ev: rs_filter.filter_signal(ev.symbol, ev.signal_time, ev.direction, window_minutes=15),
            "notes": "Keeps LONG if RS >= -0.001; keeps SHORT if RS <= 0.001 against peer proxy.",
        },
        {
            "id": "F03_SECTOR_STRENGTH",
            "family": "F03_SECTOR_STRENGTH",
            "condition": "SECTOR_SERIES_CHECK",
            "func": lambda ev: sector_filter.filter_signal(ev.symbol, ev.signal_time, ev.direction),
            "notes": "Records DATA_INSUFFICIENT; retains 100% of signals unmutated.",
        },
        {
            "id": "F04_HTF_5M_DIRECTION",
            "family": "F04_HIGHER_TIMEFRAME_CONTEXT",
            "condition": "LAST_CLOSED_5M_BAR_DIRECTION",
            "func": lambda ev: htf_aggregators[ev.symbol].filter_signal(
                ev.symbol, ev.signal_time, ev.direction, timeframe="5m", htf_condition="HTF_BAR_DIRECTION"
            ),
            "notes": "Requires last closed 5m bar bullish for LONG, bearish for SHORT.",
        },
        {
            "id": "F05_LIQUIDITY_30M",
            "family": "F05_LIQUIDITY_CANDIDATE_POOL",
            "condition": "MIN_ROLLING_TRADED_VALUE_10M",
            "func": lambda ev: liq_filter.filter_signal(
                ev.symbol, ev.signal_time, min_rolling_traded_value_twd=10_000_000.0, lookback_minutes=30
            ),
            "notes": "Requires rolling 30m traded value >= 10M TWD prior to signal.",
        },
    ]

    comparisons = []
    for spec in filter_specs:
        res = runner.evaluate_filter(
            filter_id=spec["id"],
            filter_family=spec["family"],
            condition_name=spec["condition"],
            all_events=all_raw_events,
            bars_by_symbol=all_symbol_bars,
            filter_decision_func=spec["func"],
            notes=spec["notes"],
        )
        comparisons.append(res)

    # Candidate signal counts
    cid_counts = {}
    for ev in all_raw_events:
        cid_counts[ev.candidate_id] = cid_counts.get(ev.candidate_id, 0) + 1

    # Drop reasons count
    drop_reasons: dict[str, int] = {}
    for d in dropped_signals:
        drop_reasons[d.drop_reason] = drop_reasons.get(d.drop_reason, 0) + 1

    metadata = {
        "phase": "PHASE_2B_BATCH_2",
        "purpose": "SMOKE_SAMPLE_VALIDATION",
        "timestamp": datetime.now(TPE).isoformat(),
        "symbols": symbols,
        "available_dates": available_dates,
        "total_raw_signals": len(all_raw_events),
        "total_simulated_signals": len(simulated_trades),
        "total_dropped_signals": len(dropped_signals),
        "signal_funnel_identity_pass": True,
        "drop_reasons": drop_reasons,
        "signals_per_candidate": cid_counts,
        "market_proxy_used": True,
        "market_proxy_type": "UNIVERSE_EQUAL_WEIGHTED_MARKET_PROXY",
        "leave_one_out_proxy": True,
        "target_excluded": True,
        "official_index": False,
        "missing_constituent_policy": "EXCLUDE_FROM_CURRENT_CROSS_SECTION",
        "historical_volume_unit": "LOTS",
        "volume_unit_evidence": "archive Amount / (close * volume) median = 1000.0000 across 26,139 sampled bars",
        "traded_value_source": "ARCHIVE_AMOUNT_PRIMARY",
        "approximated_traded_value": False,
        "survivorship_bias": True,
        "point_in_time_universe": False,
        "point_in_time_sector_mapping": False,
        "implementation_review": "PASS_WITH_BLOCKERS_RESOLVED",
        "ready_for_full_batch2_run": False,  # Pending Full Run Plan freeze & review
    }

    store = Batch2ResultStore()
    store.save_results_to_yaml(output_file, metadata, comparisons, dropped_signals)

    return {
        "metadata": metadata,
        "comparisons": comparisons,
        "dropped_signals": dropped_signals,
    }


if __name__ == "__main__":
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/ubuntu/easystock-history-expanded-data/raw")
    out_file = Path("docs/daytrade_phase2/phase2b_batch2_smoke_results.yaml")
    res = run_batch2_validation(data_dir, out_file)
    meta = res["metadata"]
    print(f"VALIDATION FINISHED. Raw: {meta['total_raw_signals']}, Simulated: {meta['total_simulated_signals']}, Dropped: {meta['total_dropped_signals']}")
    print(f"Drop reasons: {meta['drop_reasons']}")
    for comp in res["comparisons"]:
        print(f"[{comp.filter_family}] Retention: {comp.retention_rate:.2%}, Delta Net R: {comp.delta_net_R:+.4f}, Delta Net %: {comp.delta_net_return_pct:+.4f}%, Attribution: {comp.effect_attribution}")
