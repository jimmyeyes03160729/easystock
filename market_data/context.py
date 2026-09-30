"""Read local standardized context. No network, credentials or model changes."""
from datetime import datetime
from .health import data_dir, read_json, timestamp, TPE


def esun_index_snapshot(now=None):
    now = now or datetime.now(TPE)
    context = read_json(data_dir() / 'context.json')
    worker = read_json(data_dir() / 'esun.json')
    checked = timestamp(worker.get('checked_at'))
    if not checked or not 0 <= (now - checked).total_seconds() <= 120: return None
    if not worker.get('connected') or not worker.get('authenticated') or not worker.get('parser_ok'): return None
    quote = (context.get('indices') or {}).get('taiex') or {}
    if quote.get('symbol') != 'IX0001' or quote.get('source') != 'esun': return None
    return {'symbol': 'IX0001', 'datetime': quote.get('quote_at'), 'change_rate': quote.get('change_pct')}
