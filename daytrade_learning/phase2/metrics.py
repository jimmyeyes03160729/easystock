"""Phase 2A Research Expectancy & Risk-Adjusted Metrics.

Calculates:
- trade_count
- win_rate
- avg_win_R
- avg_loss_R
- expectancy_R
- median_R
- std_R
- max_loss_R
- max_win_R
- MFE_R (average)
- MAE_R (average)
- profit_factor
- SQN (System Quality Number)

CRITICAL GOVERNANCE CONSTRAINT:
- SQN is an exploratory metric ONLY.
- SQN > 2 = PASS is strictly forbidden.
- SQN shall NOT be used as a production promotion gateway.
"""
from __future__ import annotations
import math
import statistics
from typing import Sequence

from .dataset import Phase2TradeRecord


def calculate_trade_metrics(trades: Sequence[Phase2TradeRecord]) -> dict[str, float]:
    """Calculates R-multiple, expectancy, profit factor, and SQN metrics.
    
    Returns standard metric dictionary.
    """
    n = len(trades)
    if n == 0:
        return {
            "trade_count": 0.0,
            "win_rate": 0.0,
            "avg_win_R": 0.0,
            "avg_loss_R": 0.0,
            "expectancy_R": 0.0,
            "median_R": 0.0,
            "std_R": 0.0,
            "max_loss_R": 0.0,
            "max_win_R": 0.0,
            "MFE_R": 0.0,
            "MAE_R": 0.0,
            "profit_factor": 0.0,
            "SQN": 0.0,
        }

    r_multiples = [t.pnl_R for t in trades]
    mfe_rs = [t.mfe_R for t in trades]
    mae_rs = [t.mae_R for t in trades]

    wins = [r for r in r_multiples if r > 0]
    losses = [r for r in r_multiples if r < 0]
    evens = [r for r in r_multiples if r == 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / n

    avg_win_R = statistics.mean(wins) if wins else 0.0
    avg_loss_R = statistics.mean(losses) if losses else 0.0
    median_R = statistics.median(r_multiples)
    expectancy_R = statistics.mean(r_multiples)

    std_R = statistics.stdev(r_multiples) if n >= 2 else 0.0
    max_loss_R = min(r_multiples)
    max_win_R = max(r_multiples)
    avg_mfe_R = statistics.mean(mfe_rs)
    avg_mae_R = statistics.mean(mae_rs)

    total_gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
    total_gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
    if total_gross_loss > 0:
        profit_factor = total_gross_win / total_gross_loss
    else:
        profit_factor = float("inf") if total_gross_win > 0 else 0.0

    # System Quality Number: sqrt(N) * expectancy_R / std_R
    # Strictly an informative metric; never an automated production gate.
    if n >= 2 and std_R > 1e-9:
        sqn = math.sqrt(n) * (expectancy_R / std_R)
    else:
        sqn = 0.0

    return {
        "trade_count": float(n),
        "win_rate": round(win_rate, 4),
        "avg_win_R": round(avg_win_R, 4),
        "avg_loss_R": round(avg_loss_R, 4),
        "expectancy_R": round(expectancy_R, 4),
        "median_R": round(median_R, 4),
        "std_R": round(std_R, 4),
        "max_loss_R": round(max_loss_R, 4),
        "max_win_R": round(max_win_R, 4),
        "MFE_R": round(avg_mfe_R, 4),
        "MAE_R": round(avg_mae_R, 4),
        "profit_factor": round(profit_factor, 4) if not math.isinf(profit_factor) else 9999.0,
        "SQN": round(sqn, 4),
    }
