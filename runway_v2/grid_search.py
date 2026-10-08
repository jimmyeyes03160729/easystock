import os
import sys
from pathlib import Path

from runway_v2.backtest import RunwayV2Backtester, calculate_trade_costs, BacktestTrade
from runway_v2.config import SLIPPAGE_RATE, DEFAULT_POSITION_AMOUNT, MAX_CONCURRENT_POSITIONS
from runway_v2.strategy import score_candidate, calculate_vwap

dates_10d = [
    "2026-09-22", "2026-09-24", "2026-09-29", "2026-09-30",
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06",
    "2026-10-07", "2026-10-08"
]


class TunedBacktester(RunwayV2Backtester):
    def __init__(
        self,
        data_root="/home/ubuntu/easystock-learning-data",
        daily_max_buy_amount=1000000.0,
        morning_max_buy_amount=600000.0,   # 早盤 09:05~09:35 額度上限
        orb_min_score=65.0,                # ORB 進場分數門檻
        vwap_min_score=60.0,               # VWAP 回踩分數門檻
        take_profit_half_pct=0.015,        # 分批停利門檻
        trailing_trigger_pct=0.020,        # 移動停利門檻
        trailing_pullback_pct=0.008,       # 移動停利拉回
        stop_loss_pct=0.015,               # 停損
    ):
        super().__init__(data_root=data_root, daily_max_buy_amount=daily_max_buy_amount)
        self.morning_max_buy_amount = morning_max_buy_amount
        self.orb_min_score = orb_min_score
        self.vwap_min_score = vwap_min_score
        self.tp_half_pct = take_profit_half_pct
        self.trail_trig_pct = trailing_trigger_pct
        self.trail_pull_pct = trailing_pullback_pct
        self.stop_loss_pct = stop_loss_pct

    def run_day(self, date_str: str) -> list[BacktestTrade]:
        stocks_data, journal_metrics, stock_names = self.load_day_data(date_str)
        if not stocks_data:
            return []

        minutes = [
            f"{h:02d}:{m:02d}"
            for h in range(9, 14)
            for m in range(0, 60)
            if not (h == 9 and m < 0) and not (h == 13 and m > 0)
        ]
        open_positions = {}
        completed_trades = []
        daily_buy_spent = 0.0
        morning_buy_spent = 0.0

        for current_hhmm in minutes:
            # 1. 出場檢驗
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

                # 強制平倉 (12:55)
                if current_hhmm >= "12:55":
                    exit_price = b_close * (1.0 - SLIPPAGE_RATE)
                    self._finalize_exit(trade, current_hhmm, exit_price, "收盤強制平倉")
                    completed_trades.append(trade)
                    symbols_to_close.append(sym)
                    continue

                # 停損出場
                stop_threshold = trade.entry_price if trade.half_closed else (trade.entry_price * (1.0 - self.stop_loss_pct))
                if b_low <= stop_threshold:
                    exit_price = min(b_close, stop_threshold) * (1.0 - SLIPPAGE_RATE)
                    reason = "保本出場" if trade.half_closed else "停損出場"
                    self._finalize_exit(trade, current_hhmm, exit_price, reason)
                    completed_trades.append(trade)
                    symbols_to_close.append(sym)
                    continue

                # 分批停利
                if not trade.half_closed and b_high >= trade.entry_price * (1.0 + self.tp_half_pct):
                    half_shares = trade.shares // 2
                    if half_shares >= 1000:
                        trade.half_closed = True
                        half_exit_price = (trade.entry_price * (1.0 + self.tp_half_pct)) * (1.0 - SLIPPAGE_RATE)
                        h_gross = (half_exit_price - trade.entry_price) * half_shares
                        h_fee, h_tax = calculate_trade_costs(trade.entry_price, half_exit_price, half_shares)
                        trade.half_pnl = h_gross - (h_fee + h_tax)
                        trade.shares -= half_shares

                # 移動停利
                max_return = (trade.highest_price / trade.entry_price - 1.0)
                if max_return >= self.trail_trig_pct:
                    pullback_trigger = trade.highest_price * (1.0 - self.trail_pull_pct)
                    if b_low <= pullback_trigger:
                        exit_price = min(b_close, pullback_trigger) * (1.0 - SLIPPAGE_RATE)
                        self._finalize_exit(trade, current_hhmm, exit_price, "移動停利出場")
                        completed_trades.append(trade)
                        symbols_to_close.append(sym)
                        continue

            for sym in symbols_to_close:
                open_positions.pop(sym, None)

            # 2. 新進場評估
            if not ("09:05" <= current_hhmm <= "12:30"):
                continue

            # 每日總限額檢查
            if self.daily_max_buy_amount and daily_buy_spent >= self.daily_max_buy_amount:
                continue

            # 早盤專屬限額檢查
            is_morning = ("09:05" <= current_hhmm <= "09:35")
            if is_morning and self.morning_max_buy_amount and morning_buy_spent >= self.morning_max_buy_amount:
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
                if not (15.0 <= current_price <= 600.0):
                    continue
                gain_pct = (current_price / prev_close - 1.0) * 100.0
                if not (1.0 <= gain_pct <= 7.5):
                    continue

                hist_bars = [b for b in s_data["bars"] if b.get("at", "")[11:16] <= current_hhmm]
                if len(hist_bars) < 5:
                    continue
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
                required_score = 60.0
                if "09:05" <= current_hhmm <= "09:35":
                    opening_high = float(kbars5[0]["high"])
                    if opening_high > 0 and current_price >= opening_high:
                        signal_type = "ORB_BREAKOUT"
                        required_score = self.orb_min_score
                elif "09:35" < current_hhmm <= "11:30" and len(kbars5) >= 3 and vwap:
                    recent_bars = kbars5[-3:]
                    touched_vwap = any(0.995 <= (float(b["low"]) / vwap) <= 1.010 for b in recent_bars)
                    last_bar = recent_bars[-1]
                    if touched_vwap and float(last_bar["close"]) > float(last_bar["open"]) and current_price >= vwap:
                        signal_type = "VWAP_PULLBACK"
                        required_score = self.vwap_min_score

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
                if score >= required_score:
                    candidates.append({
                        "symbol": sym,
                        "name": stock_names.get(sym, sym),
                        "price": current_price,
                        "signal_type": signal_type,
                        "score": score,
                        "reasons": reasons,
                    })

            candidates.sort(key=lambda x: x["score"], reverse=True)
            for c in candidates:
                if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
                    break
                sym = c["symbol"]
                exec_price = c["price"] * (1.0 + SLIPPAGE_RATE)

                # 預算控管
                rem_budget = self.daily_max_buy_amount - daily_buy_spent
                if is_morning and self.morning_max_buy_amount:
                    rem_budget = min(rem_budget, self.morning_max_buy_amount - morning_buy_spent)
                if rem_budget < exec_price * 1000:
                    continue

                max_pos_budget = min(DEFAULT_POSITION_AMOUNT, rem_budget)
                shares = max(1000, int(max_pos_budget // (exec_price * 1000)) * 1000)
                buy_total = exec_price * shares
                if buy_total > rem_budget:
                    shares = int(rem_budget // (exec_price * 1000)) * 1000
                    if shares < 1000:
                        continue
                    buy_total = exec_price * shares

                daily_buy_spent += buy_total
                if is_morning:
                    morning_buy_spent += buy_total

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


def eval_config(name, dates=dates_10d, **kwargs):
    bt = TunedBacktester(**kwargs)
    trades = []
    daily_pnls = []
    for d in dates:
        d_trades = bt.run_day(d)
        trades.extend(d_trades)
        daily_pnls.append(sum(t.net_pnl for t in d_trades))

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

    print(f"[{name:32s}] 筆數: {cnt:2d} | 勝率: {win_rate:5.1f}% | PF: {pf:4.2f} | 淨損益: {net_pnl:>+9.0f} 元 | MDD: {mdd:>7.0f} 元")
    return {
        "name": name,
        "trades": cnt,
        "win_rate": win_rate,
        "pf": pf,
        "net_pnl": net_pnl,
        "mdd": mdd,
        "trades_list": trades,
    }


if __name__ == "__main__":
    print("=== 測試 100 萬額度上限下的優化參數組合 (近 10 日) ===")
    eval_config("基準 (無時段控額, ORB 60分)", morning_max_buy_amount=None, orb_min_score=60.0)
    eval_config("配置 A (早60萬/盤40萬, ORB 65分)", morning_max_buy_amount=600000.0, orb_min_score=65.0)
    eval_config("配置 B (早50萬/盤50萬, ORB 65分)", morning_max_buy_amount=500000.0, orb_min_score=65.0)
    eval_config("配置 C (早60萬, ORB 70分極致精選)", morning_max_buy_amount=600000.0, orb_min_score=70.0)
    eval_config("配置 D (早60萬, ORB 65分, TP 1.8%)", morning_max_buy_amount=600000.0, orb_min_score=65.0, take_profit_half_pct=0.018)
    eval_config("配置 E (早50萬, ORB 65分, TP 1.8%)", morning_max_buy_amount=500000.0, orb_min_score=65.0, take_profit_half_pct=0.018)
