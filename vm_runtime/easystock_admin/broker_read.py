"""Whitelisted, read-only Shioaji account projection. No order/cancel/CA calls."""
from datetime import datetime
import hashlib
import math
from zoneinfo import ZoneInfo

TPE = ZoneInfo('Asia/Taipei')


def number(value):
    if isinstance(value, bool):
        raise ValueError('invalid_broker_number')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('invalid_broker_number')
    return value


def integer(value):
    n = number(value)
    if n < 0 or int(n) != n:
        raise ValueError('invalid_broker_quantity')
    return int(n)


def enum(value):
    return str(getattr(value, 'value', value))


def identity(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def at(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=TPE).isoformat() if value.tzinfo is None else value.astimezone(TPE).isoformat()
    return None


def snapshot(service, sdk):
    now = datetime.now(TPE)
    result = {'source': 'shioaji', 'connected': False, 'authenticated': False, 'account': {},
              'updated_at': now.isoformat(), 'complete': False, 'positions': [], 'orders': [], 'deals': [],
              'pnl': {'unrealized': None, 'realized_today': None}, 'error_code': 'broker_disconnected'}
    if not service.is_logged_in or service.api is None or sdk is None:
        return result
    api, account = service.api, service.api.stock_account
    result.update(connected=True, authenticated=True, account=service.public_account())
    result['account_fingerprint'] = identity(str(account.broker_id) + ':' + str(account.account_id))
    try:
        # Blocking backend refresh, not the empty post-login local trade cache.
        api.update_status(account, timeout=5000)
        trades = api.list_trades()
        positions = api.list_positions(account, unit=sdk.Unit.Share, timeout=5000)
        pending = {}
        for trade in trades:
            order, status, contract = trade.order, trade.status, trade.contract
            acc = order.account
            if str(acc.account_id) != str(account.account_id) or str(acc.broker_id) != str(account.broker_id):
                continue
            if enum(contract.security_type) != 'STK':
                continue
            lot = enum(order.order_lot)
            if lot not in ('Common', 'IntradayOdd', 'Odd'):
                raise ValueError('unsupported_order_lot')
            unit = 1000 if lot == 'Common' else 1
            qty = integer(status.order_quantity) * unit
            if qty != integer(order.quantity) * unit:
                raise ValueError('order_quantity_not_reconciled')
            filled = integer(status.deal_quantity) * unit
            cancelled = integer(status.cancel_quantity) * unit
            state, side = enum(status.status), enum(order.action).upper()
            if state not in ('Cancelled', 'Filled', 'PartFilled', 'Inactive', 'Failed', 'PendingSubmit', 'PreSubmitted', 'Submitted') or side not in ('BUY', 'SELL') or filled + cancelled > qty:
                raise ValueError('unknown_order_status')
            remaining = qty - filled - cancelled
            if side == 'SELL' and state not in ('Cancelled', 'Filled', 'Failed'):
                pending[contract.code] = pending.get(contract.code, 0) + remaining
            row = {'order_id': identity(order.id), 'client_order_id': None, 'symbol': contract.code,
                   'side': side, 'qty': qty, 'price': number(order.price), 'status': state,
                   'filled_qty': filled, 'created_at': at(status.order_datetime), 'source': 'shioaji'}
            result['orders'].append(row)
            for deal in status.deals:
                result['deals'].append({'deal_id': identity(str(order.id) + ':' + str(deal.seq)),
                    'order_id': row['order_id'], 'symbol': contract.code, 'side': side,
                    'qty': integer(deal.quantity) * unit, 'price': number(deal.price),
                    'deal_time': at(getattr(deal, 'datetime', None)), 'source': 'shioaji'})
        for p in positions:
            qty, old_qty = integer(p.quantity), integer(p.yd_quantity)
            price, current, pnl = number(p.price), number(p.last_price), number(p.pnl)
            cash_long = enum(p.cond) == 'Cash' and enum(p.direction) == 'Buy'
            # Only prior-day cash holdings supported initially. Same-day daytrade/credit availability
            # needs authoritative eligibility evidence; never guess from the displayed position.
            available = max(0, min(qty, old_qty) - pending.get(p.code, 0)) if cash_long else None
            contract = service._find_contract(p.code)
            result['positions'].append({'symbol': p.code, 'name': getattr(contract, 'name', p.code),
                'quantity': qty, 'average_price': price, 'current_price': current, 'unrealized_pnl': pnl,
                'return_pct': pnl / (price * qty) * 100 if price > 0 and qty else None,
                'available_to_sell': available, 'availability_basis': 'prior_day_cash_minus_open_sell',
                'source': 'shioaji', 'strategy': 'broker / unknown', 'entry_time': None,
                'position_key': identity(str(p.id) + ':' + p.code + ':' + enum(p.cond) + ':' + enum(p.direction)),
                'broker_updated_at': now.isoformat()})
        # Ambiguous duplicate-symbol holdings must not share a sell allowance.
        for row in result['positions']:
            if sum(p['symbol'] == row['symbol'] for p in result['positions']) != 1:
                row['available_to_sell'] = None
        result['pnl']['unrealized'] = sum(p['unrealized_pnl'] for p in result['positions'])
        result.update(complete=True, error_code=None)
    except Exception:
        result.update(complete=False, error_code='broker_sync_unavailable')
        for row in result['positions']:
            row['available_to_sell'] = None
    try:
        day = now.date().isoformat()
        pnl_rows = api.list_profit_loss(account, begin_date=day, end_date=day, unit=sdk.Unit.Share, timeout=5000)
        if any(p.date != day for p in pnl_rows):
            raise ValueError('pnl_date_mismatch')
        result['pnl']['realized_today'] = sum(number(p.pnl) for p in pnl_rows)
    except Exception:
        pass  # Unknown is null, not fictitious zero PnL.
    return result
