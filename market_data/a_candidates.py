"""A watchlist projection. Candidate evidence never creates an order or fill."""
from datetime import datetime, timezone, timedelta
import math

TPE = timezone(timedelta(hours=8))


def numeric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def candidate(*, symbol, stock, result, price, now, quote_at, limits,
              market_pass, entry_window, mode, model=None):
    score, price = numeric(result.get('daytrade_score')), numeric(price)
    if score is None or score < 50 or not price or not quote_at:
        return None
    now, quote_at = now.astimezone(TPE), quote_at.astimezone(TPE)
    age = (now - quote_at).total_seconds()
    if quote_at.date() != now.date() or not 0 <= age <= 30:
        return None
    previous = numeric(stock.get('previous_close'))
    gain = (price / previous - 1) * 100 if previous and previous > 0 else None
    waits = list(result.get('vetoes') or [])
    if not market_pass:
        waits.append('等待大盤風控通過')
    if not entry_window:
        waits.append('非新進場時段')
    if age > 3:
        waits.append('等待3秒內新成交')
    if gain is None:
        waits.append('等待有效昨收')
    if not limits:
        waits.append('等待設定確認')
    elif not limits['min_price'] <= price <= limits['max_price'] or gain is not None and gain > limits['max_gain_pct']:
        waits.append('超出股價或漲幅設定')
    if not result.get('eligible'):
        waits.append('等待規則68分與兩項進場理由')
    if stock.get('daytrade_eligibility') not in ('Yes', 'OnlyBuy'):
        waits.append('等待當沖資格確認')
    model = model or {}
    probability = numeric(model.get('probability')) if model.get('evaluated') else None
    if mode == 'model' and not all(model.get(k) for k in ('active','evaluated','approved','accepted')):
        waits.append('等待AI模型門檻')
    if mode not in ('rules','model'):
        waits.append('等待進場模式確認')
    return {'symbol': str(symbol), 'name': str(stock.get('name') or symbol), 'price': price,
            'gain_pct': gain, 'rule_score': score, 'model_score': probability,
            'model_role': 'advisory' if mode == 'rules' else 'entry_gate',
            'model_version': model.get('model_version') if probability is not None else None,
            'opening_recovery': bool(result.get('opening_recovery')),
            'reasons': list(result.get('reasons') or result.get('daytrade_reasons') or []), 'waits': list(dict.fromkeys(waits)),
            'state': 'watch' if waits else 'rule_ready', 'execution': 'not_filled',
            'quote_at': quote_at.isoformat(), 'updated_at': now.isoformat()}


def snapshot(rows, now, limit=5):
    now = now.astimezone(TPE)
    valid = []
    for row in rows.values():
        try:
            at = datetime.fromisoformat(row['quote_at']).astimezone(TPE)
            if at.date() == now.date() and 0 <= (now - at).total_seconds() <= 30:
                valid.append(dict(row))
        except (ValueError, TypeError, KeyError):
            continue
    valid.sort(key=lambda r: (r['state'] == 'rule_ready', r['opening_recovery'],
                             r['rule_score'], r['model_score'] or 0), reverse=True)
    return {'schema_version': 1, 'day': now.date().isoformat(), 'updated_at': now.isoformat(),
            'rows': valid[:max(1, min(5, int(limit)))], 'kind': 'watchlist',
            'policy': 'rules-68-ai-advisory-v1', 'filled': False}
