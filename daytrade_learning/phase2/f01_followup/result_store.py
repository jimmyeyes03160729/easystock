"""Phase 2C F01 Follow-up: Result Store & Mechanism Metric Aggregation.

Maintains strict effect decomposition and accounting identities across all mechanism strata:
Net Return % == Theoretical Return % - Trading Friction %
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class MechanismTradeRecord:
    signal_event_id: str
    symbol: str
    date: str
    candidate_id: str
    direction: str  # "LONG" or "SHORT"
    signal_time: str
    theo_entry: float
    theo_exit: float
    initial_risk: float
    initial_risk_ticks: float
    theoretical_return_pct: float
    trading_friction_pct: float
    net_return_pct: float
    pnl_R: float
    mfe_R: float
    mae_R: float
    # F01 Verdict (Must match Phase 2B sealed logic)
    f01_keep: bool
    # H01 Trend
    proxy_intraday_return: float
    proxy_direction_consistency: float
    # H02 Volatility
    realized_volatility: float
    intraday_range: float
    # H03 Opening Direction
    opening_15m_return: Optional[float]
    opening_15m_direction: Optional[str]
    opening_30m_return: Optional[float]
    opening_30m_direction: Optional[str]
    # H04 Time of Day
    time_of_day: str  # "OPEN", "MID", "LATE"
    # H05 Breadth
    peer_constituent_count: int
    breadth_bucket: str  # "PEER_34_54", "PEER_55_79", "PEER_80_99"


class MechanismAccumulator:
    """Accumulates trades and produces standard effect decomposition metrics."""

    def __init__(self, name: str = ""):
        self.name = name
        self.n_total = 0
        self.n_filtered = 0

        self.unf_theo_list: list[float] = []
        self.unf_friction_list: list[float] = []
        self.unf_net_list: list[float] = []
        self.unf_R_list: list[float] = []
        self.unf_mfe_list: list[float] = []
        self.unf_mae_list: list[float] = []

        self.filt_theo_list: list[float] = []
        self.filt_friction_list: list[float] = []
        self.filt_net_list: list[float] = []
        self.filt_R_list: list[float] = []
        self.filt_mfe_list: list[float] = []
        self.filt_mae_list: list[float] = []

    def add(self, rec: MechanismTradeRecord) -> None:
        self.n_total += 1
        self.unf_theo_list.append(rec.theoretical_return_pct)
        self.unf_friction_list.append(rec.trading_friction_pct)
        self.unf_net_list.append(rec.net_return_pct)
        self.unf_R_list.append(rec.pnl_R)
        self.unf_mfe_list.append(rec.mfe_R)
        self.unf_mae_list.append(rec.mae_R)

        if rec.f01_keep:
            self.n_filtered += 1
            self.filt_theo_list.append(rec.theoretical_return_pct)
            self.filt_friction_list.append(rec.trading_friction_pct)
            self.filt_net_list.append(rec.net_return_pct)
            self.filt_R_list.append(rec.pnl_R)
            self.filt_mfe_list.append(rec.mfe_R)
            self.filt_mae_list.append(rec.mae_R)

    def to_metrics(self) -> dict[str, Any]:
        retention = (self.n_filtered / self.n_total) if self.n_total > 0 else 0.0

        u_theo = float(sum(self.unf_theo_list) / self.n_total) if self.n_total > 0 else 0.0
        u_fric = float(sum(self.unf_friction_list) / self.n_total) if self.n_total > 0 else 0.0
        u_net = float(sum(self.unf_net_list) / self.n_total) if self.n_total > 0 else 0.0
        u_R = float(sum(self.unf_R_list) / self.n_total) if self.n_total > 0 else 0.0

        f_theo = float(sum(self.filt_theo_list) / self.n_filtered) if self.n_filtered > 0 else 0.0
        f_fric = float(sum(self.filt_friction_list) / self.n_filtered) if self.n_filtered > 0 else 0.0
        f_net = float(sum(self.filt_net_list) / self.n_filtered) if self.n_filtered > 0 else 0.0
        f_R = float(sum(self.filt_R_list) / self.n_filtered) if self.n_filtered > 0 else 0.0

        d_theo = round(f_theo - u_theo, 4)
        d_fric = round(f_fric - u_fric, 4)
        d_net = round(f_net - u_net, 4)
        d_R = round(f_R - u_R, 4)

        # Secondary metrics for filtered set
        win_count = sum(1 for r in self.filt_R_list if r > 0)
        win_rate = (win_count / self.n_filtered) if self.n_filtered > 0 else 0.0
        gross_win = sum(r for r in self.filt_R_list if r > 0)
        gross_loss = abs(sum(r for r in self.filt_R_list if r < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else (1.0 if gross_win == 0 else 999.0)

        mfe = float(sum(self.filt_mfe_list) / self.n_filtered) if self.n_filtered > 0 else 0.0
        mae = float(sum(self.filt_mae_list) / self.n_filtered) if self.n_filtered > 0 else 0.0

        # Identity discrepancy check
        identity_discrepancy = abs(d_net - (d_theo - d_fric))

        return {
            "name": self.name,
            "unique_signals": self.n_total,
            "filtered_signals": self.n_filtered,
            "retention_rate": round(retention, 4),
            "unfiltered_theoretical_return_pct": round(u_theo, 4),
            "filtered_theoretical_return_pct": round(f_theo, 4),
            "delta_theoretical_return_pct": d_theo,
            "unfiltered_trading_friction_pct": round(u_fric, 4),
            "filtered_trading_friction_pct": round(f_fric, 4),
            "delta_trading_friction_pct": d_fric,
            "unfiltered_net_return_pct": round(u_net, 4),
            "filtered_net_return_pct": round(f_net, 4),
            "delta_net_return_pct": d_net,
            "unfiltered_net_expectancy_R": round(u_R, 4),
            "filtered_net_expectancy_R": round(f_R, 4),
            "delta_net_expectancy_R": d_R,
            "filtered_win_rate": round(win_rate, 4),
            "filtered_profit_factor": round(pf, 4),
            "filtered_MFE_R": round(mfe, 4),
            "filtered_MAE_R": round(mae, 4),
            "accounting_identity_holds": identity_discrepancy < 1e-4,
        }
