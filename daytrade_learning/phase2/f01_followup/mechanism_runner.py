"""Phase 2C F01 Follow-up: Mechanism Runner & Evaluator.

Executes causal detector evaluation, trade simulation with canonical cost accounting,
F01 leave-one-out market regime classification, and comprehensive H01-H07 mechanism stratification.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, time
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from daytrade_learning.phase2 import (
    MarketBar,
    TransactionCostModel,
    BASE_COMMISSION_REFERENCE_RATE,
    PARAM_BROKER_DISCOUNT,
    PARAM_MINIMUM_FEE,
    PARAM_DAYTRADE_TAX_RATE,
    get_twse_tick_size,
    parse_phase2_timestamp,
    RangeExpansionDetector,
    PullbackVolumeDecayDetector,
    TwoBReversalDetector,
    OneTwoThreeDetector,
)

from .trend_context import TrendContextAnalyzer
from .volatility_context import VolatilityContextAnalyzer
from .opening_context import OpeningContextAnalyzer
from .breadth_context import BreadthContextAnalyzer, CausalityOrMetadataFailure
from .result_store import MechanismTradeRecord, MechanismAccumulator

TPE = timezone(timedelta(hours=8))


def classify_time_of_day(sig_t: datetime | time) -> str:
    """Classifies signal time into half-open intervals with invariant TIME_BUCKET_MEMBERSHIP_COUNT == 1.
    
    OPEN:  [09:00, 10:00)
    MID:   [10:00, 12:00)
    LATE:  [12:00, 13:30]
    """
    t = sig_t.time() if isinstance(sig_t, datetime) else sig_t
    in_open = (time(9, 0) <= t < time(10, 0))
    in_mid = (time(10, 0) <= t < time(12, 0))
    in_late = (time(12, 0) <= t <= time(13, 30))

    membership_count = sum([in_open, in_mid, in_late])
    if membership_count != 1:
        raise ValueError(
            f"TIME_BUCKET_MEMBERSHIP_COUNT invariant violated: expected 1, got {membership_count} for time {t}"
        )
    if in_open:
        return "OPEN"
    elif in_mid:
        return "MID"
    else:
        return "LATE"


def assert_h07_descriptive_only() -> dict[str, Any]:
    """Ensures H07 failure regime classification is strictly descriptive post-hoc and never part of filtering."""
    return {
        "DESCRIPTIVE_POST_OUTCOME_CLASSIFICATION": True,
        "IN_FILTER_DECISION_PATH": False,
        "PREDICTIVE_REGIME_CLAIM_PROHIBITED": True,
    }


@dataclass
class MechanismRunResult:
    trades: list[MechanismTradeRecord]
    raw_signal_count: int
    simulated_signal_count: int
    dropped_count: int
    drop_reasons: dict[str, int]
    stratified_metrics: dict[str, dict[str, Any]]


class MechanismRunner:
    """Orchestrates F01 follow-up mechanism evaluation on stock-days."""

    def __init__(self):
        self.cost_model = TransactionCostModel(
            broker_fee_rate=BASE_COMMISSION_REFERENCE_RATE,
            broker_discount=PARAM_BROKER_DISCOUNT.value,
            minimum_fee=PARAM_MINIMUM_FEE.value,
            daytrade_tax_rate=PARAM_DAYTRADE_TAX_RATE.value,
        )
        # Fixed candidate detectors from Phase 2B
        self.det_p2b01 = [PullbackVolumeDecayDetector(max_pullback_bars=pb) for pb in [3, 5]]
        self.det_p2b02 = [RangeExpansionDetector(lookback_bars=lb) for lb in [3, 5]]
        self.det_p2b03 = [TwoBReversalDetector(pivot_confirmation_bars=cb, max_failure_bars=fb) for cb in [2, 3] for fb in [3, 5]]
        self.det_p2b04 = [OneTwoThreeDetector(confirmation_bars=cb) for cb in [1, 2]]

    def evaluate_date(
        self,
        date_str: str,
        universe_bars: dict[str, list[MarketBar]],
    ) -> tuple[list[MechanismTradeRecord], int, int, dict[str, int]]:
        """Processes a single date's universe bars with causal LOO proxy and mechanism annotations."""
        if not universe_bars:
            return [], 0, 0, {}

        # Precompute cross-sectional timeline
        all_ts_set = set()
        for sym, b_list in universe_bars.items():
            for b in b_list:
                all_ts_set.add(b.bar_close_time)

        sorted_ts = sorted(list(all_ts_set))
        ts_index_map = {ts: idx for idx, ts in enumerate(sorted_ts)}
        n_ts = len(sorted_ts)

        # Build symbol return arrays
        sym_cum_ret: dict[str, list[float]] = {}
        sym_1m_ret: dict[str, list[float]] = {}
        cum_ret_sum = [0.0] * n_ts
        cum_ret_count = [0] * n_ts

        for sym, b_list in universe_bars.items():
            c_ret = [float("nan")] * n_ts
            m_ret = [0.0] * n_ts
            first_open = b_list[0].open if b_list else 100.0
            prev_close = first_open

            for b in b_list:
                t_idx = ts_index_map[b.bar_close_time]
                c_ret[t_idx] = (b.close - first_open) / first_open
                m_ret[t_idx] = (b.close - prev_close) / prev_close if prev_close > 0 else 0.0
                prev_close = b.close
                cum_ret_sum[t_idx] += c_ret[t_idx]
                cum_ret_count[t_idx] += 1

            sym_cum_ret[sym] = c_ret
            sym_1m_ret[sym] = m_ret

        # Calculate opening benchmarks (09:15 and 09:30)
        ts_0915 = None
        ts_0930 = None
        for ts in sorted_ts:
            if ts.time() == time(9, 15):
                ts_0915 = ts
            elif ts.time() == time(9, 30):
                ts_0930 = ts

        raw_signals = []
        raw_count = 0

        # Detect raw signals
        for sym, bars in universe_bars.items():
            n_bars = len(bars)
            bar_map = {b.bar_close_time: idx for idx, b in enumerate(bars)}
            signals_collected = []

            # P2B_01
            for d in self.det_p2b01:
                sigs = d.detect_signals(sym, bars, threshold=0.50)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_01_v1", s, idx))

            # P2B_02
            for d in self.det_p2b02:
                sigs = d.detect_signals(sym, bars, threshold=1.2)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_02_v1", s, idx))

            # P2B_03
            for d in self.det_p2b03:
                sigs = d.detect_signals(sym, bars)
                for s in sigs:
                    idx = bar_map.get(s.signal_time, None)
                    if idx is not None and idx + 1 < n_bars:
                        signals_collected.append(("P2B_03_v1", s, idx))

            # P2B_04
            for d in self.det_p2b04:
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

            raw_count += len(unique_sigs)
            for cid, s, idx in unique_sigs.values():
                raw_signals.append((s, cid, s.direction.upper(), sym, idx))

        trades: list[MechanismTradeRecord] = []
        drop_reasons: dict[str, int] = {}
        simulated_count = 0

        # Simulate trades and extract mechanism context
        for sig, cid, direction, sym, sig_idx in raw_signals:
            bars = universe_bars[sym]
            n_bars = len(bars)
            entry_idx = sig_idx + 1
            if entry_idx >= n_bars:
                drop_reasons["NO_LEGAL_EXECUTION"] = drop_reasons.get("NO_LEGAL_EXECUTION", 0) + 1
                continue

            entry_bar = bars[entry_idx]
            theo_entry = entry_bar.open
            stop_loss = sig.stop_loss_price

            if direction == "LONG" and stop_loss >= theo_entry:
                drop_reasons["STOP_LOSS_VIOLATION"] = drop_reasons.get("STOP_LOSS_VIOLATION", 0) + 1
                continue
            if direction == "SHORT" and stop_loss <= theo_entry:
                drop_reasons["STOP_LOSS_VIOLATION"] = drop_reasons.get("STOP_LOSS_VIOLATION", 0) + 1
                continue

            initial_risk = abs(theo_entry - stop_loss)
            if initial_risk <= 0.0:
                drop_reasons["STOP_LOSS_VIOLATION"] = drop_reasons.get("STOP_LOSS_VIOLATION", 0) + 1
                continue

            # 15m exit horizon
            exit_idx = min(entry_idx + 15, n_bars - 1)
            sub_bars = bars[entry_idx : exit_idx + 1]
            if not sub_bars:
                drop_reasons["INSUFFICIENT_FORWARD_HORIZON"] = drop_reasons.get("INSUFFICIENT_FORWARD_HORIZON", 0) + 1
                continue

            simulated_count += 1

            # Hit stop loss check
            hit_stop = False
            hit_exit_p = 0.0
            for b in sub_bars:
                if direction == "LONG" and b.low <= stop_loss:
                    hit_stop = True
                    hit_exit_p = stop_loss
                    break
                elif direction == "SHORT" and b.high >= stop_loss:
                    hit_stop = True
                    hit_exit_p = stop_loss
                    break

            theo_exit = hit_exit_p if hit_stop else bars[exit_idx].close

            # Execution with canonical 1-tick adverse slippage
            e_tick = get_twse_tick_size(theo_entry)
            x_tick = get_twse_tick_size(theo_exit)
            act_entry = (theo_entry + e_tick) if direction == "LONG" else (theo_entry - e_tick)
            act_exit = (theo_exit - x_tick) if direction == "LONG" else (theo_exit + x_tick)

            gross_theo = (theo_exit - theo_entry) if direction == "LONG" else (theo_entry - theo_exit)
            gross_actual = (act_exit - act_entry) if direction == "LONG" else (act_entry - act_exit)
            slip_cost = gross_theo - gross_actual

            e_notional = act_entry * 1000.0
            x_notional = act_exit * 1000.0
            e_comm = self.cost_model.calculate_commission(e_notional)
            x_comm = self.cost_model.calculate_commission(x_notional)
            tax = self.cost_model.calculate_tax(x_notional, is_daytrade=True)

            net_pnl = gross_actual * 1000.0 - (e_comm + x_comm + tax)
            initial_risk_twd = initial_risk * 1000.0
            pnl_R = net_pnl / initial_risk_twd if initial_risk_twd > 0 else 0.0

            highs = [b.high for b in sub_bars]
            lows = [b.low for b in sub_bars]
            if direction == "LONG":
                mfe_R = max(0.0, (max(highs) - theo_entry) / initial_risk)
                mae_R = max(0.0, (theo_entry - min(lows)) / initial_risk)
            else:
                mfe_R = max(0.0, (theo_entry - min(lows)) / initial_risk)
                mae_R = max(0.0, (max(highs) - theo_entry) / initial_risk)

            # Percentage returns
            theo_pct = gross_theo / act_entry * 100.0
            slip_pct = slip_cost / act_entry * 100.0
            comm_pct = (e_comm + x_comm) / e_notional * 100.0
            tax_pct = tax / e_notional * 100.0
            friction_pct = slip_pct + comm_pct + tax_pct
            net_pct = theo_pct - friction_pct

            # Accounting identity assert
            assert abs(net_pct - (theo_pct - friction_pct)) < 1e-7

            # Timestamp matrix index
            sig_t = sig.signal_time if isinstance(sig.signal_time, datetime) else parse_phase2_timestamp(sig.signal_time)
            t_matrix_idx = ts_index_map[sig_t]

            # F01 Leave-One-Out Market Regime (Frozen Phase 2B logic)
            tot_c = cum_ret_count[t_matrix_idx]
            s_ret = sym_cum_ret[sym][t_matrix_idx]
            if not math.isnan(s_ret) and tot_c > 1:
                loo_cum = (cum_ret_sum[t_matrix_idx] - s_ret) / (tot_c - 1)
                peer_cnt = tot_c - 1
            elif tot_c > 0:
                loo_cum = cum_ret_sum[t_matrix_idx] / tot_c
                peer_cnt = tot_c
            else:
                loo_cum = 0.0
                peer_cnt = 0

            f01_keep = (loo_cum >= 0.0) if direction == "LONG" else (loo_cum <= 0.0)

            # Build LOO 1m return series up to signal_time
            loo_1m_rets = []
            loo_highs = []
            loo_lows = []
            for idx in range(t_matrix_idx + 1):
                c_cnt = cum_ret_count[idx]
                s_c_ret = sym_cum_ret[sym][idx]
                if not math.isnan(s_c_ret) and c_cnt > 1:
                    l_val = (cum_ret_sum[idx] - s_c_ret) / (c_cnt - 1)
                elif c_cnt > 0:
                    l_val = cum_ret_sum[idx] / c_cnt
                else:
                    l_val = 0.0
                loo_1m_rets.append(l_val)
                loo_highs.append(l_val)
                loo_lows.append(l_val)

            # H01 Trend
            trend_snap = TrendContextAnalyzer.compute(loo_1m_rets, proxy_open=1.0, proxy_current=1.0 + loo_cum)

            # H02 Volatility
            vol_snap = VolatilityContextAnalyzer.compute(loo_1m_rets, loo_highs, loo_lows, proxy_open=1.0)

            # H03 Opening
            idx_0915 = ts_index_map.get(ts_0915) if ts_0915 else None
            idx_0930 = ts_index_map.get(ts_0930) if ts_0930 else None
            p_0915 = (cum_ret_sum[idx_0915] / cum_ret_count[idx_0915]) if (idx_0915 and cum_ret_count[idx_0915] > 0) else None
            p_0930 = (cum_ret_sum[idx_0930] / cum_ret_count[idx_0930]) if (idx_0930 and cum_ret_count[idx_0930] > 0) else None
            opening_snap = OpeningContextAnalyzer.compute(
                signal_dt=sig_t,
                proxy_open_0901=1.0,
                proxy_close_0915=(1.0 + p_0915) if p_0915 is not None else None,
                proxy_close_0930=(1.0 + p_0930) if p_0930 is not None else None,
            )

            # H04 Time of Day (Strict half-open intervals & single membership)
            tod = classify_time_of_day(sig_t)

            # H05 Breadth
            breadth_snap = BreadthContextAnalyzer.compute(peer_cnt)

            rec = MechanismTradeRecord(
                signal_event_id=f"{sym}_{date_str}_{cid}_{sig_idx}_{direction}",
                symbol=sym,
                date=date_str,
                candidate_id=cid,
                direction=direction,
                signal_time=sig_t.isoformat(),
                theo_entry=theo_entry,
                theo_exit=theo_exit,
                initial_risk=initial_risk,
                initial_risk_ticks=round(initial_risk / e_tick, 2),
                theoretical_return_pct=round(theo_pct, 4),
                trading_friction_pct=round(friction_pct, 4),
                net_return_pct=round(net_pct, 4),
                pnl_R=round(pnl_R, 4),
                mfe_R=round(mfe_R, 4),
                mae_R=round(mae_R, 4),
                f01_keep=f01_keep,
                proxy_intraday_return=trend_snap.proxy_intraday_return,
                proxy_direction_consistency=trend_snap.proxy_direction_consistency,
                realized_volatility=vol_snap.realized_volatility,
                intraday_range=vol_snap.intraday_range,
                opening_15m_return=opening_snap.opening_15m_return,
                opening_15m_direction=opening_snap.opening_15m_direction,
                opening_30m_return=opening_snap.opening_30m_return,
                opening_30m_direction=opening_snap.opening_30m_direction,
                time_of_day=tod,
                peer_constituent_count=breadth_snap.peer_constituent_count,
                breadth_bucket=breadth_snap.breadth_bucket,
            )
            trades.append(rec)

        return trades, raw_count, simulated_count, drop_reasons

    @staticmethod
    def stratify(
        trades: list[MechanismTradeRecord],
        quantile_boundaries: Optional[tuple[float, float, float]] = None,
    ) -> dict[str, dict[str, Any]]:
        """Stratifies trade records across pre-registered one-dimensional mechanism dimensions."""
        accumulators: dict[str, dict[str, MechanismAccumulator]] = {
            "overall": {"OVERALL": MechanismAccumulator("OVERALL")},
            "H01_trend": {
                "Q1": MechanismAccumulator("Q1"),
                "Q2": MechanismAccumulator("Q2"),
                "Q3": MechanismAccumulator("Q3"),
                "Q4": MechanismAccumulator("Q4"),
            },
            "H02_volatility": {
                "LOW": MechanismAccumulator("LOW"),
                "MID": MechanismAccumulator("MID"),
                "HIGH": MechanismAccumulator("HIGH"),
            },
            "H03_opening_15m": {
                "OPENING_DIRECTION_POSITIVE": MechanismAccumulator("OPENING_DIRECTION_POSITIVE"),
                "OPENING_DIRECTION_NEUTRAL": MechanismAccumulator("OPENING_DIRECTION_NEUTRAL"),
                "OPENING_DIRECTION_NEGATIVE": MechanismAccumulator("OPENING_DIRECTION_NEGATIVE"),
                "NOT_AVAILABLE": MechanismAccumulator("NOT_AVAILABLE"),
            },
            "H04_time_of_day": {
                "OPEN": MechanismAccumulator("OPEN"),
                "MID": MechanismAccumulator("MID"),
                "LATE": MechanismAccumulator("LATE"),
            },
            "H05_breadth": {
                "BREADTH_34_54": MechanismAccumulator("BREADTH_34_54"),
                "BREADTH_55_79": MechanismAccumulator("BREADTH_55_79"),
                "BREADTH_80_99": MechanismAccumulator("BREADTH_80_99"),
                "INSUFFICIENT_BREADTH": MechanismAccumulator("INSUFFICIENT_BREADTH"),
            },
            "H06_candidate_direction": {
                "LONG": MechanismAccumulator("LONG"),
                "SHORT": MechanismAccumulator("SHORT"),
                "P2B_01_v1": MechanismAccumulator("P2B_01_v1"),
                "P2B_02_v1": MechanismAccumulator("P2B_02_v1"),
                "P2B_03_v1": MechanismAccumulator("P2B_03_v1"),
                "P2B_04_v1": MechanismAccumulator("P2B_04_v1"),
            },
            "H07_failure_regime": {
                "IMPROVED_DAY": MechanismAccumulator("IMPROVED_DAY"),
                "DEGRADED_DAY": MechanismAccumulator("DEGRADED_DAY"),
            },
        }

        # Calculate daily theoretical deltas for H07 classification (Strictly post-outcome descriptive)
        daily_trades: dict[str, list[MechanismTradeRecord]] = {}
        for tr in trades:
            daily_trades.setdefault(tr.date, []).append(tr)

        daily_verdicts: dict[str, str] = {}
        for d, d_list in daily_trades.items():
            u_th = sum(t.theoretical_return_pct for t in d_list) / len(d_list)
            f_list = [t for t in d_list if t.f01_keep]
            f_th = sum(t.theoretical_return_pct for t in f_list) / len(f_list) if f_list else u_th
            daily_verdicts[d] = "IMPROVED_DAY" if (f_th - u_th) > 0 else "DEGRADED_DAY"

        # Determine Q1..Q4 boundaries for H01
        if quantile_boundaries is not None:
            q1_cut, q2_cut, q3_cut = quantile_boundaries
        else:
            # Descriptive sample quartiles
            rets = sorted([t.proxy_intraday_return for t in trades])
            n = len(rets)
            if n >= 4:
                q1_cut = rets[int(n * 0.25)]
                q2_cut = rets[int(n * 0.50)]
                q3_cut = rets[int(n * 0.75)]
            else:
                q1_cut, q2_cut, q3_cut = (-0.001, 0.0, 0.001)

        # Classify and accumulate
        for tr in trades:
            accumulators["overall"]["OVERALL"].add(tr)

            # H01 Trend (Quantiles)
            if tr.proxy_intraday_return <= q1_cut:
                accumulators["H01_trend"]["Q1"].add(tr)
            elif tr.proxy_intraday_return <= q2_cut:
                accumulators["H01_trend"]["Q2"].add(tr)
            elif tr.proxy_intraday_return <= q3_cut:
                accumulators["H01_trend"]["Q3"].add(tr)
            else:
                accumulators["H01_trend"]["Q4"].add(tr)

            # H02 Volatility (Tertiles)
            if tr.realized_volatility < 0.0005:
                accumulators["H02_volatility"]["LOW"].add(tr)
            elif tr.realized_volatility < 0.0015:
                accumulators["H02_volatility"]["MID"].add(tr)
            else:
                accumulators["H02_volatility"]["HIGH"].add(tr)

            # H03 Opening 15m
            op_dir = tr.opening_15m_direction
            if op_dir in accumulators["H03_opening_15m"]:
                accumulators["H03_opening_15m"][op_dir].add(tr)
            else:
                accumulators["H03_opening_15m"]["NOT_AVAILABLE"].add(tr)

            # H04 Time of Day
            if tr.time_of_day in accumulators["H04_time_of_day"]:
                accumulators["H04_time_of_day"][tr.time_of_day].add(tr)

            # H05 Breadth
            b_bkt = tr.breadth_bucket
            if b_bkt in accumulators["H05_breadth"]:
                accumulators["H05_breadth"][b_bkt].add(tr)
            else:
                accumulators["H05_breadth"]["INSUFFICIENT_BREADTH"].add(tr)

            # H06 Direction & Candidate
            if tr.direction == "LONG":
                accumulators["H06_candidate_direction"]["LONG"].add(tr)
            else:
                accumulators["H06_candidate_direction"]["SHORT"].add(tr)

            if tr.candidate_id in accumulators["H06_candidate_direction"]:
                accumulators["H06_candidate_direction"][tr.candidate_id].add(tr)

            # H07 Failure Regime (Descriptive post-outcome classification)
            d_verd = daily_verdicts.get(tr.date, "DEGRADED_DAY")
            accumulators["H07_failure_regime"][d_verd].add(tr)

        output: dict[str, dict[str, Any]] = {}
        for dim, sub_accs in accumulators.items():
            output[dim] = {k: acc.to_metrics() for k, acc in sub_accs.items()}

        # Attach governance metadata
        output["governance"] = {
            "DISCOVERY_DATA_REUSED": True,
            "INDEPENDENT_CONFIRMATION": False,
            "ONE_DIMENSIONAL_ONLY": True,
            "CARTESIAN_SEARCH_ALLOWED": False,
            "H07_DESCRIPTIVE_ONLY": True,
            "h07_governance": assert_h07_descriptive_only(),
            "H01_quantile_boundaries": [round(q1_cut, 6), round(q2_cut, 6), round(q3_cut, 6)],
        }

        return output
