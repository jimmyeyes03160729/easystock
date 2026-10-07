#!/usr/bin/env python3
"""
Paper research positions and daily BUY limit execution
研究部位追蹤與每日額度模擬成交
"""

from __future__ import annotations
import math
import uuid
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
        self.execution_evidence = None

    def refresh(self) -> dict:
        self.state = read_paper_trade_settings()
        return self.state

    def is_active(self) -> bool:
        return self.state.get("status") == "running"

    def daily_buy_limit(self) -> float:
        return float(self.refresh()['daily_buy_limit'])

    def daily_buy_used(self) -> float:
        return float(self.refresh()['daily_buy_used'])

    def daily_buy_remaining(self) -> float:
        return float(self.refresh()['daily_buy_remaining'])

    def open_fill(self, symbol, name, price, execution_id=None):
        from paper_account import buy
        from paper_execution import execution
        evidence = self.execution_evidence(symbol) if self.execution_evidence else {}
        decision = execution(evidence, 'BUY', datetime.now(TPE))
        if decision['status'] != 'executable':
            return decision
        result = buy(symbol, name, decision['price'], execution_id=execution_id,
                     max_shares=decision['max_shares'])
        return dict(result, execution_evidence=decision)

    def try_buy(self, symbol, name, price):
        return self.open_fill(symbol, name, price).get('shares', 0)

    def close_and_settle(self, symbol, exit_price, exit_reason='平倉出場',
                         name=None, entry_price=None, shares=None, trade_id=None):
        from paper_account import sell, open_positions, settlement_receipt
        from paper_execution import execution
        receipt = settlement_receipt(trade_id) if trade_id else None
        if receipt:
            return dict(receipt, already_settled=True)
        position = next((p for p in open_positions() if p['symbol']==str(symbol)), None)
        if not position:
            return {'status':'no_position'}
        evidence = self.execution_evidence(symbol) if self.execution_evidence else {}
        decision = execution(evidence, 'SELL', datetime.now(TPE), position['shares'])
        if decision['status'] != 'executable':
            return decision
        return sell(symbol, decision['price'], exit_reason, trade_id=trade_id)


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

    research_mode separates accepted strategy episodes from paper execution.
    Paper callbacks retain daily-limit/re-entry constraints; research closes independently.
    Legacy callers can retain fill-only behavior with research_mode=False.
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
        cost_aware_breakeven=False,
        before_open=None,
        before_close=None,
        research_mode=False,
        research_store=None,
        paper_max_daily_entries=5,
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
        self.cost_aware_breakeven = bool(cost_aware_breakeven)
        self.before_open, self.before_close = before_open, before_close
        self.research_mode = research_mode
        self.research_store = research_store
        self.paper_max_daily_entries = paper_max_daily_entries
        self.paper_traded_symbols = set()
        self.rearm_states = {}
        self.pending_paper_settlements = {}
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

        if self.research_mode:
            armed, observed = self.rearm_states.get((dt.date().isoformat(), str(symbol)), (True, None))
            return armed and (observed is None or dt > observed)

        if (
            not self.allow_reentry
            and symbol
            in self.traded_symbols
        ):
            return False

        return True

    @synchronized
    def observe_entry_predicate(self, symbol, accepted, at):
        """Re-arm only after a post-close false predicate, never on a timer."""
        symbol = str(symbol)
        if not self.research_mode or self.has_open_position(symbol) or accepted:
            return
        key = (at.date().isoformat(), symbol)
        armed, closed_at = self.rearm_states.get(key, (True, None))
        if not armed and closed_at is not None and at > closed_at:
            if self.research_store:
                self.research_store.arm(symbol, at)
            self.rearm_states[key] = (True, at)

    def _persist(self, position, armed=None):
        if self.research_store:
            self.research_store.save(position, armed)

    @synchronized
    def migrate_closed_paper(self, rows, day, receipt_lookup):
        """Preserve verified pre-upgrade fills; never invent unfunded research."""
        if not self.research_store:
            return
        known = {row.get('paper_trade_id') for row in self.research_store.trades(day)}
        for source in sorted(rows, key=lambda row: str(row.get('exit_time', ''))):
            paper_id = source.get('trade_id')
            if (not paper_id or paper_id in known or source.get('research_trade_id')
                    or source.get('execution_kind') != 'paper_fill'):
                continue
            receipt = receipt_lookup(paper_id)
            if not isinstance(receipt, dict) or receipt.get('status') != 'sold' or receipt.get('trade_id') != paper_id:
                continue
            entry = datetime.fromisoformat(str(source['entry_time']))
            exit_at = datetime.fromisoformat(str(source['exit_time']))
            if (entry.tzinfo is None or exit_at.tzinfo is None or entry.date().isoformat() != day
                    or exit_at.date().isoformat() != day or exit_at < entry):
                raise RuntimeError('Invalid verified legacy paper timestamps')
            identity = 'legacy-paper-' + paper_id
            row = dict(source, research_trade_id=identity, episode_id=identity,
                research_execution='TRACKED', paper_execution='FILLED', paper_skip_reason=None,
                paper_trade_id=paper_id, paper_attempted=True, paper_settlement_pending=False,
                status='CLOSED', entry_time=entry, exit_time=exit_at, settlement=receipt,
                entry_gate_evidence={'legacy_verified_paper_settlement': True})
            if receipt.get('shares'):
                row['research_net_pnl_pct'] = float(receipt['net_pnl'])/(float(row['entry_price'])*receipt['shares'])*100
                row['research_cost_basis'] = 'legacy_verified_paper_settlement'
            self._persist(row, armed=False)
            known.add(paper_id)

    @synchronized
    def restore_research(self, day):
        if not self.research_store:
            return
        rows = self.research_store.trades(status='OPEN')
        for row in rows:
            if row['status'] == 'OPEN' and str(row['entry_time'])[:10] != day:
                raise RuntimeError('Overnight research position needs reconciliation: ' + row['symbol'])
        for row in self.research_store.trades(day):
            for key in ('entry_time', 'last_update_at', 'exit_time'):
                if row.get(key):
                    row[key] = datetime.fromisoformat(row[key])
            symbol = row['symbol']
            if row.get('paper_execution') == 'FILLED':
                self.paper_traded_symbols.add(symbol)
            if row['status'] == 'OPEN':
                self.positions[symbol] = row
            else:
                self.closed_trades.append(row)
                if row.get('paper_settlement_pending'):
                    self.pending_paper_settlements[row['research_trade_id']] = row
        self.rearm_states.update({(day, symbol): (armed, datetime.fromisoformat(at))
                                  for symbol, (armed, at) in self.research_store.state(day).items()})

    @synchronized
    def retry_paper_settlements(self):
        for identity, trade in list(self.pending_paper_settlements.items()):
            try:
                receipt = self.before_close(symbol=trade['symbol'], exit_price=trade['exit_price'],
                    exit_reason=trade['exit_reason'], trade_id=trade['paper_trade_id'])
            except Exception:
                continue
            if isinstance(receipt, dict) and receipt.get('status') == 'sold':
                trade.update(settlement=receipt, paper_settlement_pending=False)
                self._persist(trade)
                del self.pending_paper_settlements[identity]


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
        decision_evidence=None,
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
        if self.before_open and not self.research_mode:
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

        if self.research_mode:
            identity = uuid.uuid4().hex
            position.update(research_trade_id=identity, episode_id=identity,
                research_execution='TRACKED', paper_execution='NOT_ATTEMPTED',
                paper_skip_reason=None, paper_trade_id=None, paper_attempted=False,
                **(decision_evidence or {}))
            # Persist acceptance before touching the separate execution ledger.
            self._persist(position)
            self.positions[str(symbol)] = position
            if self.before_open:
                position['paper_attempted'] = True
                position['paper_skip_reason'] = 'execution_unconfirmed'
                self._persist(position)
                if not self.allow_reentry and str(symbol) in self.paper_traded_symbols:
                    fill = {'status': 'reentry_disabled'}
                elif len(self.paper_traded_symbols) >= self.paper_max_daily_entries:
                    fill = {'status': 'daily_entry_limit'}
                else:
                    try:
                        fill = self.before_open(symbol=str(symbol), name=name, price=price, execution_id=identity)
                    except Exception:
                        fill = {'status': 'execution_unconfirmed'}
                if (isinstance(fill, dict) and fill.get('status') == 'bought'
                        and fill.get('shares', 0) > 0 and fill.get('trade_id')):
                    position.update(paper_execution='FILLED', paper_skip_reason=None,
                        paper_trade_id=fill['trade_id'], trade_id=fill['trade_id'],
                        shares=fill['shares'], execution_kind='paper_fill')
                    position['paper_entry_price'] = fill.get('entry_price')
                    position['paper_execution_evidence'] = fill.get('execution_evidence')
                    self.paper_traded_symbols.add(str(symbol))
                else:
                    position.update(paper_execution='SKIPPED',
                        paper_skip_reason=(fill.get('skip_reason') or fill.get('status', 'execution_unconfirmed')) if isinstance(fill, dict)
                        else 'execution_unconfirmed', execution_kind='research_only')
                    if isinstance(fill, dict) and (fill.get('eligibility_detail') or fill.get('quote_error')):
                        position['paper_skip_detail'] = {k: fill[k] for k in ('eligibility_detail', 'quote_error') if fill.get(k)}
                self._persist(position)

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

    def breakeven_prices(self, position):
        """(floor, activation) prices for the breakeven exit of a position."""
        entry = float(position["entry_price"])
        if not self.cost_aware_breakeven:
            return (entry * (1 + self.breakeven_floor_pct),
                    entry * (1 + self.breakeven_activate_pct))
        from paper_execution import cost_aware_breakeven
        # A Paper fill at the ask costs more than the signal price.
        basis = max(entry, float(position.get("paper_entry_price") or 0))
        floor, activate = cost_aware_breakeven(
            basis, self.breakeven_floor_pct, self.breakeven_activate_pct)
        return (max(floor, entry * (1 + self.breakeven_floor_pct)),
                max(activate, entry * (1 + self.breakeven_activate_pct)))

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

        if current_time < position['last_update_at']:
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

        if self.research_mode:
            self._persist(position)


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

        # 動態保本：最高價達啟動價後，跌回保本價即出場。預設為固定百分比
        # （+0.6% 啟動、+0.35% 出場），未涵蓋手續費、稅與買賣價差；
        # cost_aware_breakeven 時改以實際成本與跳動單位計算。
        highest = position.get("highest_price", price)
        floor, activate = self.breakeven_prices(position)
        if highest >= activate and price <= floor:
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
        if self.research_mode:
            if exit_time < position['last_update_at']:
                return None
            position.update(current_price=exit_price, last_update_at=exit_time,
                highest_price=max(position['highest_price'], exit_price),
                lowest_price=min(position['lowest_price'], exit_price))
        settlement = None
        if self.before_close and not self.research_mode:
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

        if self.research_mode:
            # Research closes independently; a failed paper settlement is retried
            # against the same frozen exit and identity without reopening research.
            trade['paper_settlement_pending'] = trade.get('paper_execution') == 'FILLED'
            # Hypothetical one-lot research costs, independent of wallet size.
            from decimal import Decimal, ROUND_HALF_UP
            from paper_ledger import fee, BUY_RATE, SELL_RATE
            from paper_execution import tax, tick_size
            entry_amount = Decimal(str(entry_price))*1000
            exit_amount = Decimal(str(exit_price))*1000
            costs = (fee(entry_amount, BUY_RATE) + fee(exit_amount, SELL_RATE)
                     + tax(exit_amount))
            trade['research_net_pnl_pct'] = pnl_pct - float(costs/entry_amount)*100
            trade['research_cost_basis'] = 'one_lot_fee_28pct_discount_daytrade_tax'
            # Signal and exit prices are last trades; an actual fill buys at the
            # ask and sells at the bid. Estimate that as one tick per round trip.
            spread = float(tick_size(entry_price)/Decimal(str(entry_price)))*100
            trade['research_spread_cost_pct'] = spread
            trade['research_net_after_spread_pct'] = trade['research_net_pnl_pct'] - spread
            self._persist(trade, armed=False)
            self.rearm_states[(exit_time.date().isoformat(), symbol)] = (False, exit_time)
            if trade['paper_settlement_pending']:
                self.pending_paper_settlements[trade['research_trade_id']] = trade
                self.retry_paper_settlements()


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
