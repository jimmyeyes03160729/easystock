"""Runway V2 參數調優研究腳本 (100萬額度專用) - 1個月完整盲測版
"""
from __future__ import annotations
import gc
import json
import math
import os
import sys
from pathlib import Path

from runway_v2.backtest import RunwayV2Backtester, calculate_trade_costs, BacktestTrade
from runway_v2.config import (
    MIN_PRICE,
    MAX_PRICE,
    MIN_GAIN_PCT,
    MAX_GAIN_PCT,
    SLIPPAGE_RATE,
)
from runway_v2.strategy import score_candidate, calculate_vwap

DATES_1M = [
    "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
    "2026-09-17", "2026-09-18", "2026-09-22", "2026-09-24",
    "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02",
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"
]


def precompute_day_candidates(
    stocks_data: dict,
    journal_metrics: dict,
    stock_names: dict,
    minutes: list[str],
) -> dict[str, list[dict]]:
    for s_data in stocks_data.values():
        s_data["time_idx"] = {b["at"][11:16]: i for i, b in enumerate(s_data["bars"]) if "at" in b}

    minute_candidates = {m: [] for m in minutes}

    for current_hhmm in minutes:
        if not ("09:05" <= current_hhmm <= "12:30"):
            continue

        cands = []
        is_orb_time = ("09:05" <= current_hhmm <= "09:35")
        is_vwap_time = ("09:35" < current_hhmm <= "11:30")

        for sym, s_data in stocks_data.items():
            t_idx = s_data["time_idx"].get(current_hhmm)
            if t_idx is None or t_idx < 4:
                continue

            bar = s_data["bars"][t_idx]
            current_price = float(bar["close"])
            prev_close = s_data["prev_close"]

            if not (MIN_PRICE <= current_price <= MAX_PRICE):
                continue
            gain_pct = (current_price / prev_close - 1.0) * 100.0
            if not (MIN_GAIN_PCT <= gain_pct <= MAX_GAIN_PCT):
                continue

            hist_bars = s_data["bars"][:t_idx + 1]
            vwap = calculate_vwap(hist_bars)
            if vwap is not None and current_price < vwap * 0.998:
                continue

            kbars5 = []
            chunk = []
            for b in hist_bars:
                chunk.append(b)
                if len(chunk) == 5:
                    kbars5.append({
                        "open": float(chunk[0]["open"]),
                        "high": max(float(x["high"]) for x in chunk),
                        "low": min(float(x["low"]) for x in chunk),
                        "close": float(chunk[-1]["close"]),
                        "volume": sum(float(x.get("volume", 0)) for x in chunk),
                    })
                    chunk = []

            if not kbars5:
                continue

            signal_type = None
            if is_orb_time:
                opening_high = float(kbars5[0]["high"])
                if opening_high > 0 and current_price >= opening_high:
                    signal_type = "ORB_BREAKOUT"
            elif is_vwap_time and len(kbars5) >= 3 and vwap:
                recent_bars = kbars5[-3:]
                touched_vwap = any(0.995 <= (float(b["low"]) / vwap) <= 1.010 for b in recent_bars)
                last_bar = recent_bars[-1]
                if touched_vwap and float(last_bar["close"]) > float(last_bar["open"]) and current_price >= vwap:
                    signal_type = "VWAP_PULLBACK"

            if not signal_type:
                continue

            j_key = (sym, current_hhmm)
            if j_key in journal_metrics:
                m = journal_metrics[j_key]
                radar_metrics = {
                    "surge_60s": m["surge_60s"],
                    "buy_ratio_60s": m["buy_ratio_60s"],
                    "amount_60s": m["amount_60s"],
                }
            else:
                vol_recent = sum(float(b.get("volume", 0)) for b in hist_bars[-5:])
                vol_base = sum(float(b.get("volume", 0)) for b in hist_bars[:5]) / 5.0
                surge_est = (vol_recent / 5.0) / (vol_base + 1.0)
                up_bars = sum(1 for b in hist_bars[-5:] if float(b["close"]) >= float(b["open"]))
                radar_metrics = {
                    "surge_60s": round(surge_est, 2),
                    "buy_ratio_60s": round(0.5 + (up_bars / 5.0) * 0.4, 2),
                    "amount_60s": vol_recent * current_price * 1000,
                }

            score, reasons = score_candidate(
                price=current_price,
                vwap=vwap,
                previous_close=prev_close,
                radar_metrics=radar_metrics,
                kbars5=kbars5,
            )
            if score >= 55.0:
                cands.append({
                    "symbol": sym,
                    "name": stock_names.get(sym, sym),
                    "price": current_price,
                    "signal_type": signal_type,
                    "score": score,
                    "reasons": reasons,
                })

        cands.sort(key=lambda x: x["score"], reverse=True)
        minute_candidates[current_hhmm] = cands

    return minute_candidates


def simulate_day_fast(
    stocks_data: dict,
    minute_candidates: dict[str, list[dict]],
    date_str: str,
    stop_loss_pct: float,
    take_profit_half_pct: float,
    orb_min_score: float,
    vwap_min_score: float,
    trailing_trigger_pct: float,
    trailing_pullback_pct: float,
    pos_amount: float,
    daily_max_buy: float,
    max_positions: int = 3,
) -> list[BacktestTrade]:
    minutes = sorted(minute_candidates.keys())
    open_positions = {}
    completed_trades = []
    daily_buy_spent = 0.0

    for current_hhmm in minutes:
        symbols_to_close = []
        for sym, trade in list(open_positions.items()):
            s_data = stocks_data.get(sym)
            if not s_data:
                continue
            bar = s_data["bars_by_time"].get(current_hhmm)
            if not bar:
                continue

            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_close = float(bar["close"])
            trade.highest_price = max(trade.highest_price, b_high)
            trade.lowest_price = min(trade.lowest_price, b_low)

            if current_hhmm >= "12:55":
                exit_price = b_close * (1.0 - SLIPPAGE_RATE)
                finalize_exit(trade, current_hhmm, exit_price, "收盤強制平倉")
                completed_trades.append(trade)
                symbols_to_close.append(sym)
                continue

            stop_threshold = trade.entry_price if trade.half_closed else (trade.entry_price * (1.0 - stop_loss_pct))
            if b_low <= stop_threshold:
                exit_price = min(b_close, stop_threshold) * (1.0 - SLIPPAGE_RATE)
                reason = "保本出場" if trade.half_closed else "停損出場"
                finalize_exit(trade, current_hhmm, exit_price, reason)
                completed_trades.append(trade)
                symbols_to_close.append(sym)
                continue

            if not trade.half_closed and b_high >= trade.entry_price * (1.0 + take_profit_half_pct):
                half_shares = trade.shares // 2
                if half_shares >= 1000:
                    trade.half_closed = True
                    half_exit_price = (trade.entry_price * (1.0 + take_profit_half_pct)) * (1.0 - SLIPPAGE_RATE)
                    h_gross = (half_exit_price - trade.entry_price) * half_shares
                    h_fee, h_tax = calculate_trade_costs(trade.entry_price, half_exit_price, half_shares)
                    trade.half_pnl = h_gross - (h_fee + h_tax)
                    trade.shares -= half_shares

            max_return = (trade.highest_price / trade.entry_price - 1.0)
            if max_return >= trailing_trigger_pct:
                pullback_trigger = trade.highest_price * (1.0 - trailing_pullback_pct)
                if b_low <= pullback_trigger:
                    exit_price = min(b_close, pullback_trigger) * (1.0 - SLIPPAGE_RATE)
                    finalize_exit(trade, current_hhmm, exit_price, "移動停利出場")
                    completed_trades.append(trade)
                    symbols_to_close.append(sym)
                    continue

        for sym in symbols_to_close:
            open_positions.pop(sym, None)

        if not ("09:05" <= current_hhmm <= "12:30"):
            continue

        if daily_max_buy is not None and daily_buy_spent >= daily_max_buy:
            continue

        available_slots = max_positions - len(open_positions)
        if available_slots <= 0:
            continue

        raw_cands = minute_candidates.get(current_hhmm, [])
        for c in raw_cands:
            if len(open_positions) >= max_positions:
                break
            sym = c["symbol"]
            if sym in open_positions:
                continue

            req_score = orb_min_score if c["signal_type"] == "ORB_BREAKOUT" else vwap_min_score
            if c["score"] < req_score:
                continue

            exec_price = c["price"] * (1.0 + SLIPPAGE_RATE)
            rem_budget = daily_max_buy - daily_buy_spent if daily_max_buy is not None else float("inf")
            if rem_budget < exec_price * 1000:
                continue

            max_pos_budget = min(pos_amount, rem_budget)
            shares = max(1000, int(max_pos_budget // (exec_price * 1000)) * 1000)
            buy_total = exec_price * shares
            if buy_total > rem_budget:
                shares = int(rem_budget // (exec_price * 1000)) * 1000
                if shares < 1000:
                    continue
                buy_total = exec_price * shares

            daily_buy_spent += buy_total

            trade = BacktestTrade(
                trade_id=f"BT-{sym}-{date_str}-{current_hhmm.replace(':', '')}",
                symbol=sym,
                name=c["name"],
                entry_date=date_str,
                entry_time=f"{current_hhmm}:00",
                entry_price=exec_price,
                shares=shares,
                signal_type=c["signal_type"],
                score=c["score"],
                reasons=c["reasons"],
                highest_price=exec_price,
                lowest_price=exec_price,
            )
            open_positions[sym] = trade

    return completed_trades


def finalize_exit(trade: BacktestTrade, exit_hhmm: str, exit_price: float, exit_reason: str):
    trade.exit_time = f"{exit_hhmm}:00"
    trade.exit_price = exit_price
    trade.exit_reason = exit_reason
    remain_gross = (exit_price - trade.entry_price) * trade.shares
    fee, tax = calculate_trade_costs(trade.entry_price, exit_price, trade.shares)
    remain_net = remain_gross - (fee + tax)
    trade.net_pnl = round(trade.half_pnl + remain_net, 2)
    trade.gross_pnl = round(remain_gross, 2)
    trade.fee = fee
    trade.tax = tax
    total_cost = trade.entry_price * (trade.shares * (2 if trade.half_closed else 1))
    trade.return_pct = round((trade.net_pnl / total_cost) * 100.0, 2) if total_cost > 0 else 0.0


def run_1m_study(dates: list[str], configs: dict[str, dict], data_root: str = "/home/ubuntu/easystock-learning-data"):
    bt_loader = RunwayV2Backtester(data_root=data_root)
    results = {k: [] for k in configs}
    daily_results = {k: {d: 0.0 for d in dates} for k in configs}

    minutes = [
        f"{h:02d}:{m:02d}"
        for h in range(9, 14)
        for m in range(0, 60)
        if not (h == 9 and m < 0) and not (h == 13 and m > 0)
    ]

    print(f"=== 啟動 1 個月 (16 個交易日) 100 萬額度全量前向盲測 ===", flush=True)

    for idx, d in enumerate(dates, 1):
        stocks_data, journal_metrics, stock_names = bt_loader.load_day_data(d)
        if not stocks_data:
            print(f"[{idx:2d}/{len(dates):2d}] {d}: 無資料，跳過", flush=True)
            continue

        minute_candidates = precompute_day_candidates(stocks_data, journal_metrics, stock_names, minutes)

        for cfg_name, cfg in configs.items():
            trades = simulate_day_fast(
                stocks_data=stocks_data,
                minute_candidates=minute_candidates,
                date_str=d,
                stop_loss_pct=cfg.get("stop_loss_pct", 0.015),
                take_profit_half_pct=cfg.get("take_profit_half_pct", 0.015),
                orb_min_score=cfg.get("orb_min_score", 60.0),
                vwap_min_score=cfg.get("vwap_min_score", 60.0),
                trailing_trigger_pct=cfg.get("trailing_trigger_pct", 0.020),
                trailing_pullback_pct=cfg.get("trailing_pullback_pct", 0.008),
                pos_amount=cfg.get("pos_amount", 300000.0),
                daily_max_buy=cfg.get("daily_max_buy", 1000000.0),
                max_positions=cfg.get("max_positions", 3),
            )
            results[cfg_name].extend(trades)
            day_pnl = sum(t.net_pnl for t in trades)
            daily_results[cfg_name][d] = day_pnl

        del stocks_data, journal_metrics, stock_names, minute_candidates
        gc.collect()
        print(f"[{idx:2d}/{len(dates):2d}] {d}: 完成", flush=True)

    print("\n" + "=" * 98, flush=True)
    print(f"{'配置名稱':<42s} | {'交易筆數':>4s} | {'勝率':>6s} | {'盈虧比':>5s} | {'淨損益(元)':>11s} | {'最大回撤(元)':>10s}", flush=True)
    print("-" * 98, flush=True)

    for cfg_name, trades in results.items():
        cnt = len(trades)
        wins = sum(1 for t in trades if t.net_pnl > 0)
        win_rate = (wins / cnt * 100.0) if cnt else 0.0
        net_pnl = sum(t.net_pnl for t in trades)
        gross_win = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        pf = (gross_win / gross_loss) if gross_loss else 99.9

        peak = 0.0
        mdd = 0.0
        curr = 0.0
        for t in trades:
            curr += t.net_pnl
            if curr > peak:
                peak = curr
            if (peak - curr) > mdd:
                mdd = peak - curr

        print(f"{cfg_name:<42s} | {cnt:4d} 筆 | {win_rate:5.1f}% | {pf:5.2f} | {net_pnl:>+11.0f} | {mdd:>10.0f}", flush=True)

    print("=" * 98, flush=True)

    # 輸出逐日損益對照表
    print("\n=== 1 個月 (16 個交易日) 逐日淨損益對照表 (單位: 新台幣元) ===", flush=True)
    header = f"{'交易日期':<10s}"
    for cfg_name in configs:
        short_name = cfg_name.split(":")[0]
        header += f" | {short_name:>12s}"
    print(header, flush=True)
    print("-" * len(header), flush=True)

    for d in dates:
        row = f"{d:<10s}"
        for cfg_name in configs:
            val = daily_results[cfg_name].get(d, 0.0)
            row += f" | {val:>+12.0f}"
        print(row, flush=True)
    print("-" * len(header), flush=True)

    # 輸出全部交易清單存檔為 JSON 便於前端或報告查閱
    output_path = "/home/ubuntu/easystock/runway_v2_1m_results.json"
    save_data = {
        "dates": dates,
        "daily_results": daily_results,
        "summary": {}
    }
    for cfg_name, trades in results.items():
        cnt = len(trades)
        wins = sum(1 for t in trades if t.net_pnl > 0)
        net_pnl = sum(t.net_pnl for t in trades)
        save_data["summary"][cfg_name] = {
            "trades": cnt,
            "win_rate": (wins / cnt * 100.0) if cnt else 0.0,
            "net_pnl": net_pnl,
            "trade_records": [
                {
                    "trade_id": t.trade_id,
                    "symbol": t.symbol,
                    "name": t.name,
                    "entry_date": t.entry_date,
                    "entry_time": t.entry_time,
                    "entry_price": t.entry_price,
                    "shares": t.shares,
                    "exit_time": t.exit_time,
                    "exit_price": t.exit_price,
                    "exit_reason": t.exit_reason,
                    "net_pnl": t.net_pnl,
                    "return_pct": t.return_pct,
                }
                for t in trades
            ]
        }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n完整 1 個月明細已儲存至: {output_path}", flush=True)


if __name__ == "__main__":
    configs_1m = {
        "基準方案 (SL -1.5%, TP +1.5%, 3檔)": {
            "stop_loss_pct": 0.015, "take_profit_half_pct": 0.015, "pos_amount": 300000.0, "max_positions": 3
        },
        "J2 方案 (穩健放大: SL -1.5%, TP +2.0%, 3檔)": {
            "stop_loss_pct": 0.015, "take_profit_half_pct": 0.020, "pos_amount": 300000.0, "max_positions": 3
        },
        "K2 方案 (呼吸推進: SL -1.8%, TP +2.0%, 3檔)": {
            "stop_loss_pct": 0.018, "take_profit_half_pct": 0.020, "pos_amount": 300000.0, "max_positions": 3
        },
        "K3 方案 (極致盈虧: SL -1.8%, TP +2.5%, 3檔)": {
            "stop_loss_pct": 0.018, "take_profit_half_pct": 0.025, "pos_amount": 300000.0, "max_positions": 3
        },
        "L2 方案 (集中精銳: SL -1.5%, TP +2.0%, 2檔@48萬)": {
            "stop_loss_pct": 0.015, "take_profit_half_pct": 0.020, "pos_amount": 480000.0, "max_positions": 2
        },
        "L3 方案 (精銳呼吸: SL -1.8%, TP +2.0%, 2檔@48萬)": {
            "stop_loss_pct": 0.018, "take_profit_half_pct": 0.020, "pos_amount": 480000.0, "max_positions": 2
        },
    }

    run_1m_study(DATES_1M, configs_1m)
