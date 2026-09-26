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

    def open_fill(self, symbol, name, price):
        from paper_account import buy
        return buy(symbol, name, price)

    def try_buy(self, symbol, name, price):
        return self.open_fill(symbol, name, price).get('shares', 0)

    def close_and_settle(self, symbol, exit_price, exit_reason='平倉出場',
                         name=None, entry_price=None, shares=None, trade_id=None):
        from paper_account import sell
        return sell(symbol, exit_price, exit_reason, trade_id=trade_id)


from datetime import time
from functools import wraps
from threading import RLock


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._position_lock:
            return method(self, *args, **kwargs)
    return call


class PositionManager:
    """
    Easystock 當沖部位管理器 V2

    Runtime 注入紙上帳務 callbacks，成交／結算成功後才提交部位事件。
    離線研究可不注入 callbacks，此時明確標記 strategy_signal。
    不呼叫 Shioaji Order / Deal。
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
        exit_mode='hybrid',
        breakeven_activate_pct=.006,
        breakeven_floor_pct=.0035,
        technical_exit_enabled=True,
        before_open=None,
        before_close=None,
    ):
        if exit_mode not in {'fixed', 'trailing', 'hybrid'}:
            raise ValueError('invalid_exit_mode')
        values = (stop_loss_pct, take_profit_pct, trailing_activate_pct,
                  trailing_pullback_pct, breakeven_activate_pct, breakeven_floor_pct)
        if any(not math.isfinite(float(v)) or not 0 < float(v) < 1 for v in values):
            raise ValueError('invalid_exit_percentages')
        if breakeven_floor_pct >= breakeven_activate_pct:
            raise ValueError('breakeven_floor_must_be_below_activation')
        self._position_lock = RLock()
        self.exit_mode = exit_mode
        self.breakeven_activate_pct = breakeven_activate_pct
        self.breakeven_floor_pct = breakeven_floor_pct
        self.technical_exit_enabled = technical_exit_enabled
        self.before_open, self.before_close = before_open, before_close
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

    @synchronized
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

        if not math.isfinite(price) or price <= 0:
            raise ValueError('invalid_entry_price')
        fill = None
        if self.before_open:
            fill = self.before_open(symbol=str(symbol), name=name, price=price)
            if not isinstance(fill, dict) or fill.get('status') != 'bought' or fill.get('shares',0) <= 0:
                return None

        position = {
            "symbol": str(symbol),
            "name": name,
            "trade_id": fill.get('trade_id') if fill else None,
            "shares": fill.get('shares') if fill else None,
            "execution_kind": 'paper_fill' if fill else 'strategy_signal',
            "exit_mode": self.exit_mode,

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
            "trade_id": position.get("trade_id"),
            "position": position.copy(),
        }


    # =====================================================
    # Tick 即時監控
    # =====================================================

    @synchronized
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
        if not math.isfinite(price) or price <= 0:
            return None

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

        # 動態保本機制：若最高價曾漲達 +0.6% 以上，拉升至保本位(成本+0.35%稅費)，杜絕獲利反轉虧損
        highest = position.get("highest_price", price)
        entry_price = position.get("entry_price", price)
        if highest >= entry_price * (1+self.breakeven_activate_pct) and price <= entry_price * (1+self.breakeven_floor_pct):
            return self.close_position(
                symbol=symbol,
                exit_price=price,
                exit_time=current_time,
                reason="動態保本出場",
            )


        # =================================================
        # 固定停利
        # =================================================

        if (
            self.exit_mode in {"fixed", "hybrid"}
            and price
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
            self.exit_mode in {"trailing", "hybrid"}
            and position["highest_price"]
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
            self.exit_mode in {"trailing", "hybrid"}
            and trailing_stop is not None
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

    @synchronized
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


        if not self.technical_exit_enabled:
            return None

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

    @synchronized
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

        if not math.isfinite(exit_price) or exit_price <= 0:
            return None
        settlement = None
        if self.before_close:
            settlement = self.before_close(symbol=symbol, exit_price=exit_price,
                exit_reason=reason, trade_id=position.get('trade_id'))
            if not isinstance(settlement, dict) or settlement.get('status') != 'sold':
                return None

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
            "settlement": settlement,

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
            "trade_id": position.get("trade_id"),
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
