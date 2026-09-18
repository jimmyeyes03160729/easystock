#!/usr/bin/env python3
"""
Paper Trade Position & Capital Manager
動態權益部位計算與結算模組
"""

from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta

try:
    from easystock_admin.store import (
        read_paper_trade_settings,
        record_paper_trade_settlement,
        log_paper_trade_event,
        set_paper_position,
        clear_paper_position,
        get_paper_position
    )
except ImportError:
    from vm_runtime.easystock_admin.store import (
        read_paper_trade_settings,
        record_paper_trade_settlement,
        log_paper_trade_event,
        set_paper_position,
        clear_paper_position,
        get_paper_position
    )

TPE = timezone(timedelta(hours=8))
BROKER_FEE_RATE = 0.001425 * 0.28  # 預設 28 折手續費
TAX_RATE = 0.0015                 # 現股當沖證交稅 0.15%

class PaperWallet:
    def __init__(self):
        self.state = read_paper_trade_settings()

    def refresh(self) -> dict:
        self.state = read_paper_trade_settings()
        return self.state

    def is_active(self) -> bool:
        return self.state.get("status") == "running"

    def current_capital(self) -> float:
        return float(self.state.get("current_capital") or self.state.get("initial_capital", 100000.0))

    def try_buy(self, symbol: str, name: str, price: float) -> int:
        """嘗試開倉，若無法買進則記錄具體略過原因"""
        self.refresh()
        if not self.is_active():
            log_paper_trade_event(symbol, name, price, "略過", "後台模擬當沖處於【暫停】狀態")
            return 0

        capital = self.current_capital()
        # 單檔標的最多投入當日可用資金的 80% (保留保證金緩衝)
        max_budget = capital * 0.8
        one_lot_cost = price * 1000

        if one_lot_cost > max_budget:
            reason = f"資金不足：買進 1 張需 {one_lot_cost:,.0f} 元，已超過單檔上限 {max_budget:,.0f} 元 (總資金 {capital:,.0f} 元)"
            log_paper_trade_event(symbol, name, price, "略過", reason)
            print(f"[Paper Trade] {symbol} {name} 略過: {reason}")
            return 0

        shares = math.floor(max_budget / one_lot_cost) * 1000
        if shares > 0:
            set_paper_position(symbol, name, price, shares)
            log_paper_trade_event(symbol, name, price, "買進", f"成功買進 {shares} 股，花費約 {price * shares:,.0f} 元")
            print(f"[Paper Trade] 成功開倉 {symbol} {name} {shares} 股，價格 {price}")
            return shares

        log_paper_trade_event(symbol, name, price, "略過", "部位計算為 0 股，取消委託")
        return 0

    def close_and_settle(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str = "平倉出場",
        name: str | None = None,
        entry_price: float | None = None,
        shares: int | None = None,
    ) -> dict:
        """平倉出場並結算損益；缺少買進資料時由 SQLite 持倉讀回。"""

        symbol = str(symbol)

        if name is None or entry_price is None or shares is None:
            position = get_paper_position(symbol)

            if not position:
                raise RuntimeError(
                    f"找不到 PaperWallet 持倉資料: {symbol}"
                )

            name = str(position["name"])
            entry_price = float(position["entry_price"])
            shares = int(position["shares"])

        entry_price = float(entry_price)
        exit_price = float(exit_price)
        shares = int(shares)

        if shares <= 0:
            raise ValueError(
                f"PaperWallet shares 無效: {symbol} shares={shares}"
            )

        self.refresh()

        start_cap = self.current_capital()

        buy_amount = entry_price * shares
        sell_amount = exit_price * shares

        buy_fee = max(
            20,
            round(buy_amount * BROKER_FEE_RATE)
        )

        sell_fee = max(
            20,
            round(sell_amount * BROKER_FEE_RATE)
        )

        tax = round(
            sell_amount * TAX_RATE
        )

        costs = buy_fee + sell_fee + tax
        gross_pnl = sell_amount - buy_amount

        net_pnl = round(
            gross_pnl - costs,
            2
        )

        end_cap = round(
            start_cap + net_pnl,
            2
        )

        today_str = datetime.now(
            TPE
        ).strftime("%Y-%m-%d")

        clear_paper_position(symbol)

        log_paper_trade_event(
            symbol,
            name,
            exit_price,
            "賣出",
            (
                f"{exit_reason}："
                f"淨損益 {net_pnl:+,.0f} 元 "
                f"(扣手續費與稅 {costs} 元)"
            )
        )

        record_paper_trade_settlement(
            date_str=today_str,
            start_bal=start_cap,
            end_bal=end_cap,
            net_pnl=net_pnl,
            symbols_str=f"{symbol} {name}",
            costs=costs,
            trades_count=1,
        )

        self.refresh()

        print(
            f"[Paper Settle] "
            f"{symbol} {name} 平倉完成 | "
            f"淨損益: {net_pnl:+.0f} | "
            f"最新本金: {end_cap:,.0f}"
        )

        return {
            "date": today_str,
            "start_balance": start_cap,
            "end_balance": end_cap,
            "net_pnl": net_pnl,
            "costs": costs,
        }


from datetime import time


class PositionManager:
    """
    Easystock 當沖部位管理器 V2

    目前管理的是「訊號部位」。
    尚未串接 Shioaji 真實 Order / Deal，
    所以 entry / exit price 仍是策略訊號價。
    """

    ENTRY_START = time(9, 30)
    ENTRY_CUTOFF = time(12, 30)
    FORCE_EXIT_TIME = time(12, 55)
    DAYTRADE_END = time(13, 0)

    def __init__(
        self,
        stop_loss_pct=0.008,
        take_profit_pct=0.012,
        trailing_activate_pct=0.006,
        trailing_pullback_pct=0.004,
        allow_reentry=False,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

        self.trailing_activate_pct = (
            trailing_activate_pct
        )

        self.trailing_pullback_pct = (
            trailing_pullback_pct
        )

        self.allow_reentry = allow_reentry

        # {symbol: position}
        self.positions = {}

        # 已完成交易
        self.closed_trades = []

        # 當日已做過的股票
        self.traded_symbols = set()


    # =====================================================
    # 時間控制
    # =====================================================

    def can_open_now(self, dt):
        clock = dt.time()

        return (
            clock >= self.ENTRY_START
            and clock < self.ENTRY_CUTOFF
        )


    def is_force_exit_time(self, dt):
        return (
            dt.time()
            >= self.FORCE_EXIT_TIME
        )


    def is_daytrade_closed(self, dt):
        return (
            dt.time()
            >= self.DAYTRADE_END
        )


    # =====================================================
    # 部位狀態
    # =====================================================

    def has_open_position(self, symbol):
        return (
            symbol in self.positions
        )


    def get_position(self, symbol):
        return self.positions.get(
            symbol
        )


    def get_open_positions(self):
        return list(
            self.positions.values()
        )


    def can_open(self, symbol, dt):

        if not self.can_open_now(dt):
            return False

        if self.has_open_position(symbol):
            return False

        if (
            not self.allow_reentry
            and symbol
            in self.traded_symbols
        ):
            return False

        return True


    # =====================================================
    # 開倉
    # =====================================================

    def open_position(
        self,
        symbol,
        name,
        price,
        entry_time,
        score,
        reasons,
        vwap=None,
    ):

        if not self.can_open(
            symbol,
            entry_time
        ):
            return None

        price = float(price)

        position = {
            "symbol": str(symbol),
            "name": name,

            "status": "OPEN",

            "entry_price": price,
            "entry_time": entry_time,

            "current_price": price,

            "entry_score": score,

            "entry_reasons":
                list(reasons or []),

            "entry_vwap": vwap,

            "highest_price": price,
            "lowest_price": price,

            "stop_price":
                price
                * (
                    1
                    - self.stop_loss_pct
                ),

            "take_profit_price":
                price
                * (
                    1
                    + self.take_profit_pct
                ),

            "trailing_stop": None,

            "last_update_at":
                entry_time,
        }

        self.positions[
            str(symbol)
        ] = position

        self.traded_symbols.add(
            str(symbol)
        )

        return {
            "type": "ENTRY",
            "position": position.copy(),
        }


    # =====================================================
    # Tick 即時監控
    # =====================================================

    def on_tick(
        self,
        symbol,
        price,
        current_time,
    ):

        symbol = str(symbol)

        position = (
            self.positions.get(
                symbol
            )
        )

        if position is None:
            return None

        price = float(price)

        position["current_price"] = (
            price
        )

        position["last_update_at"] = (
            current_time
        )

        position["highest_price"] = max(
            position["highest_price"],
            price,
        )

        position["lowest_price"] = min(
            position["lowest_price"],
            price,
        )


        # =================================================
        # 12:55 強制出場
        # =================================================

        if self.is_force_exit_time(
            current_time
        ):

            return self.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=current_time,
                reason="12:55當沖強制出場",
            )


        # =================================================
        # 固定停損
        # =================================================

        if (
            price
            <= position["stop_price"]
        ):

            return self.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=current_time,
                reason="固定停損",
            )


        # =================================================
        # 固定停利
        # =================================================

        if (
            price
            >= position[
                "take_profit_price"
            ]
        ):

            return self.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=current_time,
                reason="固定停利",
            )


        # =================================================
        # 移動停利
        # =================================================

        activate_price = (
            position["entry_price"]
            * (
                1
                + self.trailing_activate_pct
            )
        )


        if (
            position["highest_price"]
            >= activate_price
        ):

            new_stop = (
                position["highest_price"]
                * (
                    1
                    - self.trailing_pullback_pct
                )
            )

            old_stop = (
                position.get(
                    "trailing_stop"
                )
            )

            if old_stop is None:

                position["trailing_stop"] = (
                    new_stop
                )

            else:

                position["trailing_stop"] = max(
                    old_stop,
                    new_stop,
                )


        trailing_stop = (
            position.get(
                "trailing_stop"
            )
        )


        if (
            trailing_stop is not None
            and price <= trailing_stop
        ):

            return self.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=current_time,
                reason="移動停利",
            )


        return None


    # =====================================================
    # 每完成一根 5M K 後做技術面出場
    # =====================================================

    def on_strategy_result(
        self,
        symbol,
        result,
        current_time,
    ):

        symbol = str(symbol)

        position = (
            self.positions.get(
                symbol
            )
        )

        if position is None:
            return None


        # 12:55 時間出場
        if self.is_force_exit_time(
            current_time
        ):

            return self.close_position(
                symbol=symbol,
                exit_price=position[
                    "current_price"
                ],
                exit_time=current_time,
                reason="12:55當沖強制出場",
            )


        vetoes = (
            result.get("vetoes")
            or []
        )


        if "跌破VWAP" in vetoes:

            return self.close_position(
                symbol=symbol,
                exit_price=result[
                    "price"
                ],
                exit_time=current_time,
                reason="跌破VWAP",
            )


        if "5分K破短低" in vetoes:

            return self.close_position(
                symbol=symbol,
                exit_price=result[
                    "price"
                ],
                exit_time=current_time,
                reason="5分K破短低",
            )


        return None


    # =====================================================
    # 平倉
    # =====================================================

    def close_position(
        self,
        symbol,
        exit_price,
        exit_time,
        reason,
    ):

        symbol = str(symbol)

        position = (
            self.positions.get(
                symbol
            )
        )

        if position is None:
            return None

        exit_price = float(
            exit_price
        )

        entry_price = float(
            position["entry_price"]
        )


        pnl_pct = (
            exit_price
            / entry_price
            - 1
        ) * 100


        mfe_pct = (
            position["highest_price"]
            / entry_price
            - 1
        ) * 100


        mae_pct = (
            position["lowest_price"]
            / entry_price
            - 1
        ) * 100


        try:

            duration_seconds = int(
                (
                    exit_time
                    - position[
                        "entry_time"
                    ]
                )
                .total_seconds()
            )

        except Exception:

            duration_seconds = None


        trade = {
            **position,

            "status": "CLOSED",

            "exit_price":
                exit_price,

            "exit_time":
                exit_time,

            "exit_reason":
                reason,

            "pnl_pct":
                pnl_pct,

            "mfe_pct":
                mfe_pct,

            "mae_pct":
                mae_pct,

            "duration_seconds":
                duration_seconds,
        }


        self.closed_trades.append(
            trade
        )


        del self.positions[
            symbol
        ]


        return {
            "type": "EXIT",
            "trade": trade,
        }


    # =====================================================
    # LINE ENTRY
    # =====================================================

    def format_entry_message(
        self,
        event,
    ):

        p = event["position"]

        reasons = "\n".join(
            f"✓ {reason}"
            for reason
            in p["entry_reasons"]
        )


        return (
            "🚀【當沖進場訊號】\n\n"

            f"{p['symbol']} "
            f"{p['name']}\n"

            f"訊號價："
            f"{p['entry_price']:.2f}\n"

            f"分數："
            f"{p['entry_score']}\n"

            f"VWAP："
            f"{p['entry_vwap'] or '-'}\n\n"

            f"{reasons}\n\n"

            f"停損參考："
            f"{p['stop_price']:.2f}\n"

            f"停利參考："
            f"{p['take_profit_price']:.2f}\n\n"

            "狀態：OPEN"
        )


    # =====================================================
    # LINE EXIT
    # =====================================================

    def format_exit_message(
        self,
        event,
    ):

        t = event["trade"]

        pnl = t["pnl_pct"]

        sign = (
            "+"
            if pnl >= 0
            else ""
        )


        seconds = (
            t.get(
                "duration_seconds"
            )
        )


        if seconds is None:

            duration_text = "-"

        else:

            duration_text = (
                f"{seconds // 60}分"
                f"{seconds % 60}秒"
            )


        return (
            "✅【當沖出場】\n\n"

            f"{t['symbol']} "
            f"{t['name']}\n\n"

            f"訊號進場："
            f"{t['entry_price']:.2f}\n"

            f"訊號出場："
            f"{t['exit_price']:.2f}\n\n"

            f"報酬："
            f"{sign}"
            f"{pnl:.2f}%\n"

            f"最高浮盈："
            f"{t['mfe_pct']:+.2f}%\n"

            f"最大浮虧："
            f"{t['mae_pct']:+.2f}%\n"

            f"持有時間："
            f"{duration_text}\n\n"

            f"出場原因："
            f"{t['exit_reason']}"
        )
