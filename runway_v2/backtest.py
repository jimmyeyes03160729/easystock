"""Runway V2: 歷史回測與前向盲測引擎 (Walk-forward Blind Backtest)
嚴格無未來函數 (Zero Lookahead Bias)：
1. 僅使用當前分鐘與過去歷史分鐘的價格、成交量與雷達動能指標。
2. 開盤 09:05 前不進場，確立第 1 根 5 分 K 線高點 (ORB 基準)。
3. 嚴格執行：-1.5% 停損、+1.5% 分批出半趟保本、+2.0% 啟動移動停利 (回檔 0.8% 出場)、12:55 收盤強制全平。
4. 真實扣除券商手續費 (28折)、當沖證交稅 (0.15%) 與進出場雙向滑價 (0.05% + 0.05%)。
"""
from __future__ import annotations
import os
import json
import math
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .config import (
    MIN_PRICE,
    MAX_PRICE,
    MIN_GAIN_PCT,
    MAX_GAIN_PCT,
    MAX_CONCURRENT_POSITIONS,
    DEFAULT_POSITION_AMOUNT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_HALF_PCT,
    TRAILING_TRIGGER_PCT,
    TRAILING_PULLBACK_PCT,
    FEE_RATE,
    TAX_RATE,
    SLIPPAGE_RATE,
)
from .strategy import score_candidate, calculate_vwap


@dataclass
class BacktestTrade:
    trade_id: str
    symbol: str
    name: str
    entry_date: str
    entry_time: str
    entry_price: float
    shares: int
    signal_type: str
    score: float
    reasons: list[str]
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    gross_pnl: float = 0.0
    fee: float = 0.0
    tax: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 999999.0
    half_closed: bool = False
    half_pnl: float = 0.0


def calculate_trade_costs(buy_price: float, sell_price: float, shares: int) -> tuple[float, float]:
    """計算 (手續費, 證交稅)"""
    buy_amount = buy_price * shares
    sell_amount = sell_price * shares
    fee = math.floor(buy_amount * FEE_RATE) + math.floor(sell_amount * FEE_RATE)
    tax = math.floor(sell_amount * TAX_RATE)
    return float(fee), float(tax)


class RunwayV2Backtester:
    def __init__(self, data_root: str = "/home/ubuntu/easystock-learning-data"):
        self.data_root = Path(data_root)
        self.bars_dir = self.data_root / "bars"

    def load_day_data(self, date_str: str) -> tuple[dict[str, dict], dict[tuple[str, str], dict], dict[str, str]]:
        """載入特定交易日的 bars 資料與 journal 雷達記錄。"""
        day_bars_dir = self.bars_dir / date_str
        journal_path = self.data_root / f"journal-{date_str}.jsonl"

        stocks_data = {}
        if day_bars_dir.exists():
            for fname in os.listdir(day_bars_dir):
                if fname.endswith(".json"):
                    sym = fname[:-5]
                    fpath = day_bars_dir / fname
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            prev_info = data.get("previous_close") or {}
                            prev_close = prev_info.get("price") if isinstance(prev_info, dict) else None
                            bars = data.get("bars", [])
                            if prev_close and bars:
                                # 建立時間索引 HH:MM -> bar
                                bars_by_time = {}
                                for b in bars:
                                    at_str = b.get("at", "")
                                    if len(at_str) >= 16:
                                        hhmm = at_str[11:16]
                                        bars_by_time[hhmm] = b
                                stocks_data[sym] = {
                                    "prev_close": float(prev_close),
                                    "bars": bars,
                                    "bars_by_time": bars_by_time,
                                }
                    except Exception:
                        continue

        journal_metrics = {}
        stock_names = {}
        if journal_path.exists():
            try:
                with open(journal_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        if obj.get("kind") == "sample":
                            rec = obj.get("recorded_at", "")
                            if len(rec) >= 16:
                                hhmm = rec[11:16]
                                d = obj.get("data", {})
                                sym = d.get("symbol")
                                if sym and d.get("name"):
                                    stock_names[sym] = d["name"]
                                m = d.get("metrics", {})
                                if sym and m.get("surge_60s") is not None:
                                    journal_metrics[(sym, hhmm)] = {
                                        "price": d.get("price"),
                                        "surge_60s": float(m.get("surge_60s") or 0.0),
                                        "buy_ratio_60s": float(m.get("buy_ratio_60s") or 0.0),
                                        "amount_60s": float(m.get("amount_60s") or 0.0),
                                    }
            except Exception:
                pass

        return stocks_data, journal_metrics, stock_names

    def run_day(self, date_str: str) -> list[BacktestTrade]:
        """對單一交易日執行嚴格前向盲測模擬。"""
        stocks_data, journal_metrics, stock_names = self.load_day_data(date_str)
        if not stocks_data:
            return []

        # 產生 09:00 至 13:00 的分鐘時序清單
        minutes = []
        for h in range(9, 14):
            for m in range(0, 60):
                if h == 9 and m < 0:
                    continue
                if h == 13 and m > 0:
                    break
                minutes.append(f"{h:02d}:{m:02d}")

        open_positions: dict[str, BacktestTrade] = {}
        completed_trades: list[BacktestTrade] = []

        # 依時間推進每一分鐘
        for current_hhmm in minutes:
            current_time_sec = f"{current_hhmm}:00"

            # ----------------------------------------------------
            # 1. 持倉風控檢驗 (停損、分批停利、移動停利、強制平倉)
            # ----------------------------------------------------
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

                # A. 強制平倉 (12:55)
                if current_hhmm >= "12:55":
                    exit_price = b_close * (1.0 - SLIPPAGE_RATE)
                    self._finalize_exit(trade, current_hhmm, exit_price, "收盤強制平倉")
                    completed_trades.append(trade)
                    symbols_to_close.append(sym)
                    continue

                # B. 停損出場
                # 若已出半趟，防守點為成本價 (保本)；否則為 -1.5% 結構停損
                stop_threshold = trade.entry_price if trade.half_closed else (trade.entry_price * (1.0 - STOP_LOSS_PCT))
                if b_low <= stop_threshold:
                    exit_price = min(b_close, stop_threshold) * (1.0 - SLIPPAGE_RATE)
                    reason = "保本出場" if trade.half_closed else "停損出場"
                    self._finalize_exit(trade, current_hhmm, exit_price, reason)
                    completed_trades.append(trade)
                    symbols_to_close.append(sym)
                    continue

                # C. 分批停利 (+1.5% 先出 50%，剩餘保本)
                if not trade.half_closed and b_high >= trade.entry_price * (1.0 + TAKE_PROFIT_HALF_PCT):
                    half_shares = trade.shares // 2
                    if half_shares >= 1000:
                        trade.half_closed = True
                        half_exit_price = (trade.entry_price * (1.0 + TAKE_PROFIT_HALF_PCT)) * (1.0 - SLIPPAGE_RATE)
                        h_gross = (half_exit_price - trade.entry_price) * half_shares
                        h_fee, h_tax = calculate_trade_costs(trade.entry_price, half_exit_price, half_shares)
                        trade.half_pnl = h_gross - (h_fee + h_tax)
                        trade.shares -= half_shares

                # D. 移動停利 (+2.0% 啟動，自高點回檔 0.8% 出場)
                max_return = (trade.highest_price / trade.entry_price - 1.0)
                if max_return >= TRAILING_TRIGGER_PCT:
                    pullback_trigger = trade.highest_price * (1.0 - TRAILING_PULLBACK_PCT)
                    if b_low <= pullback_trigger:
                        exit_price = min(b_close, pullback_trigger) * (1.0 - SLIPPAGE_RATE)
                        self._finalize_exit(trade, current_hhmm, exit_price, "移動停利出場")
                        completed_trades.append(trade)
                        symbols_to_close.append(sym)
                        continue

            for sym in symbols_to_close:
                open_positions.pop(sym, None)

            # ----------------------------------------------------
            # 2. 新進場訊號評估 (09:05 ~ 12:30)
            # ----------------------------------------------------
            if not ("09:05" <= current_hhmm <= "12:30"):
                continue

            available_slots = MAX_CONCURRENT_POSITIONS - len(open_positions)
            if available_slots <= 0:
                continue

            candidates = []

            for sym, s_data in stocks_data.items():
                if sym in open_positions:
                    continue

                bar = s_data["bars_by_time"].get(current_hhmm)
                if not bar:
                    continue

                current_price = float(bar["close"])
                prev_close = s_data["prev_close"]

                # 價格與漲幅初篩
                if not (MIN_PRICE <= current_price <= MAX_PRICE):
                    continue
                gain_pct = (current_price / prev_close - 1.0) * 100.0
                if not (MIN_GAIN_PCT <= gain_pct <= MAX_GAIN_PCT):
                    continue

                # 截至當前分鐘的所有 1 分 K 線
                hist_bars = []
                for b in s_data["bars"]:
                    b_at = b.get("at", "")
                    if len(b_at) >= 16 and b_at[11:16] <= current_hhmm:
                        hist_bars.append(b)

                if len(hist_bars) < 5:
                    continue

                # 計算當前即時 VWAP
                vwap = calculate_vwap(hist_bars)
                if vwap is not None and current_price < vwap * 0.998:
                    continue

                # 5 分 K 線合成
                kbars5 = []
                chunk = []
                for b in hist_bars:
                    chunk.append(b)
                    if len(chunk) == 5:
                        k5 = {
                            "open": float(chunk[0]["open"]),
                            "high": max(float(x["high"]) for x in chunk),
                            "low": min(float(x["low"]) for x in chunk),
                            "close": float(chunk[-1]["close"]),
                            "volume": sum(float(x.get("volume", 0)) for x in chunk),
                        }
                        kbars5.append(k5)
                        chunk = []

                if not kbars5:
                    continue

                # 型態判定
                signal_type = None
                if "09:05" <= current_hhmm <= "09:35":
                    # ORB 突破第 1 根 5 分 K 高點
                    opening_high = float(kbars5[0]["high"])
                    if opening_high > 0 and current_price >= opening_high:
                        signal_type = "ORB_BREAKOUT"

                elif "09:35" < current_hhmm <= "11:30" and len(kbars5) >= 3 and vwap:
                    # VWAP 回踩不破出量轉強
                    recent_bars = kbars5[-3:]
                    touched_vwap = any(
                        0.995 <= (float(b["low"]) / vwap) <= 1.010 for b in recent_bars
                    )
                    last_bar = recent_bars[-1]
                    bullish_reversal = float(last_bar["close"]) > float(last_bar["open"]) and current_price >= vwap
                    if touched_vwap and bullish_reversal:
                        signal_type = "VWAP_PULLBACK"

                if not signal_type:
                    continue

                # 動能指標取得 (優先 journal，次之 bars 估算)
                j_key = (sym, current_hhmm)
                if j_key in journal_metrics:
                    m = journal_metrics[j_key]
                    radar_metrics = {
                        "surge_60s": m["surge_60s"],
                        "buy_ratio_60s": m["buy_ratio_60s"],
                        "amount_60s": m["amount_60s"],
                    }
                else:
                    # 從近 5 分鐘 K 線估計爆量與買盤比率
                    vol_recent = sum(float(b.get("volume", 0)) for b in hist_bars[-5:])
                    vol_base = sum(float(b.get("volume", 0)) for b in hist_bars[:5]) / 5.0
                    surge_est = (vol_recent / 5.0) / (vol_base + 1.0)
                    up_bars = sum(1 for b in hist_bars[-5:] if float(b["close"]) >= float(b["open"]))
                    buy_ratio_est = 0.5 + (up_bars / 5.0) * 0.4
                    radar_metrics = {
                        "surge_60s": round(surge_est, 2),
                        "buy_ratio_60s": round(buy_ratio_est, 2),
                        "amount_60s": vol_recent * current_price * 1000,
                    }

                score, reasons = score_candidate(
                    price=current_price,
                    vwap=vwap,
                    previous_close=prev_close,
                    radar_metrics=radar_metrics,
                    kbars5=kbars5,
                )

                if score >= 60.0:
                    candidates.append({
                        "symbol": sym,
                        "name": stock_names.get(sym, sym),
                        "price": current_price,
                        "signal_type": signal_type,
                        "score": score,
                        "reasons": reasons,
                    })

            # 依分數排序，優先進場最高分者
            candidates.sort(key=lambda x: x["score"], reverse=True)
            for c in candidates[:available_slots]:
                sym = c["symbol"]
                # 進場成交價計入滑價 (買貴 0.05%)
                exec_price = c["price"] * (1.0 + SLIPPAGE_RATE)
                shares = max(1000, int(DEFAULT_POSITION_AMOUNT // (exec_price * 1000)) * 1000)
                trade = BacktestTrade(
                    trade_id=f"BT-{sym}-{date_str}-{current_hhmm.replace(':', '')}",
                    symbol=sym,
                    name=c["name"],
                    entry_date=date_str,
                    entry_time=current_time_sec,
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

    def _finalize_exit(self, trade: BacktestTrade, exit_hhmm: str, exit_price: float, reason: str) -> None:
        trade.exit_time = f"{exit_hhmm}:00"
        trade.exit_price = exit_price
        trade.exit_reason = reason

        gross = (exit_price - trade.entry_price) * trade.shares
        fee, tax = calculate_trade_costs(trade.entry_price, exit_price, trade.shares)
        net = gross - (fee + tax) + trade.half_pnl

        # 總成本估算
        trade.gross_pnl = gross
        trade.fee = fee
        trade.tax = tax
        trade.net_pnl = net
        trade.return_pct = round((net / (trade.entry_price * (trade.shares * (2 if trade.half_closed else 1)))) * 100.0, 2)


def run_10_days_backtest(
    dates: list[str] | None = None,
    data_root: str = "/home/ubuntu/easystock-learning-data",
) -> dict[str, Any]:
    """執行近 10 天全市場前向盲測回測並彙整報表。"""
    if dates is None:
        dates = [
            "2026-09-22",
            "2026-09-24",
            "2026-09-29",
            "2026-09-30",
            "2026-10-01",
            "2026-10-02",
            "2026-10-05",
            "2026-10-06",
            "2026-10-07",
            "2026-10-08",
        ]

    tester = RunwayV2Backtester(data_root=data_root)
    all_trades: list[BacktestTrade] = []
    daily_summaries = []

    print(f"=== 開始執行跑道 B (Runway V2) 近 {len(dates)} 日前向盲測回測 ===")

    for d in dates:
        trades = tester.run_day(d)
        all_trades.extend(trades)

        day_wins = sum(1 for t in trades if t.net_pnl > 0)
        day_losses = sum(1 for t in trades if t.net_pnl <= 0)
        day_count = len(trades)
        day_pnl = sum(t.net_pnl for t in trades)
        day_win_rate = (day_wins / day_count * 100.0) if day_count > 0 else 0.0

        daily_summaries.append({
            "date": d,
            "trade_count": day_count,
            "wins": day_wins,
            "losses": day_losses,
            "win_rate": round(day_win_rate, 1),
            "net_pnl": round(day_pnl, 0),
            "trades": trades,
        })
        print(f"[{d}] 交易: {day_count:2d} 檔 | 勝: {day_wins} 負: {day_losses} | 勝率: {day_win_rate:5.1f}% | 淨損益: {day_pnl:+9.0f} 元")

    total_count = len(all_trades)
    total_wins = sum(1 for t in all_trades if t.net_pnl > 0)
    total_losses = sum(1 for t in all_trades if t.net_pnl <= 0)
    total_win_rate = (total_wins / total_count * 100.0) if total_count > 0 else 0.0
    total_net_pnl = sum(t.net_pnl for t in all_trades)
    total_gross_wins = sum(t.net_pnl for t in all_trades if t.net_pnl > 0)
    total_gross_losses = abs(sum(t.net_pnl for t in all_trades if t.net_pnl < 0))
    profit_factor = (total_gross_wins / total_gross_losses) if total_gross_losses > 0 else 99.9

    # 計算損益曲線與最大回撤 (MDD)
    equity_curve = [0.0]
    peak = 0.0
    max_drawdown = 0.0
    running_pnl = 0.0
    for t in all_trades:
        running_pnl += t.net_pnl
        equity_curve.append(running_pnl)
        if running_pnl > peak:
            peak = running_pnl
        dd = peak - running_pnl
        if dd > max_drawdown:
            max_drawdown = dd

    result = {
        "dates_tested": dates,
        "total_trades": total_count,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": round(total_win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "total_net_pnl": round(total_net_pnl, 0),
        "max_drawdown": round(max_drawdown, 0),
        "daily_summaries": daily_summaries,
        "all_trades": all_trades,
    }

    return result


if __name__ == "__main__":
    res = run_10_days_backtest()
    print("\n" + "=" * 50)
    print(f"總交易筆數: {res['total_trades']}")
    print(f"勝率: {res['win_rate']}% ({res['total_wins']} 勝 / {res['total_losses']} 負)")
    print(f"盈虧比 (Profit Factor): {res['profit_factor']}")
    print(f"10 日累積淨獲利: {res['total_net_pnl']:+,} 元")
    print(f"最大資產回撤 (MDD): {res['max_drawdown']:,} 元")
    print("=" * 50)
