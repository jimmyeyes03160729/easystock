"""200 元版的候選股票：從 VM 官方日線資料庫算出行情欄位，交易狀態取自證交所／櫃買中心處置股公告。

AI 只能從這份名單選股，行情數字不用再上網找；網路搜尋留給營收、公告與新聞。
"""
import json
import re
import sqlite3

import requests

TWSE_PUNISH = 'https://openapi.twse.com.tw/v1/announcement/punish'
TPEX_DISPOSAL = 'https://www.tpex.org.tw/openapi/v1/tpex_disposal_information'
STOCK = re.compile(r'^[1-8]\d{3}$')       # 4-digit common stocks; 0xxx are ETFs, 91xx are TDRs
WINDOW, MIN_AVG_AMOUNT = 20, 50_000_000
FIELDS = ('symbol', 'name', 'exchange', 'security_type', 'price_date', 'close', 'amount', 'avg_amount_20d',
          'history_sessions', 'ma5', 'ma20', 'return_5d_pct', 'trading_status')


def roc_dates(text):
    """ROC dates in '115/10/08～115/10/15' or '1151008~1151019' → ISO dates."""
    out = []
    for y, m, d in re.findall(r'(1\d{2})/?(\d{2})/?(\d{2})', text or ''):
        out.append('%04d-%s-%s' % (int(y) + 1911, m, d))
    return out


def disposition_symbols(entry_day, get=requests.get):
    """Symbols under a TWSE/TPEx disposition period that covers entry_day; None when either source fails."""
    found = set()
    try:
        for url, code, period in ((TWSE_PUNISH, 'Code', 'DispositionPeriod'),
                                  (TPEX_DISPOSAL, 'SecuritiesCompanyCode', 'DispositionPeriod')):
            r = get(url, timeout=30)
            r.raise_for_status()
            for row in r.json():
                days = roc_dates(row.get(period))
                if days and days[0] <= entry_day <= days[-1]:
                    found.add(str(row.get(code, '')).strip())
    except (requests.RequestException, ValueError):
        return None
    return found


def load_names(path):
    try:
        db = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        names = dict(db.execute("SELECT symbol, name FROM revenue WHERE name IS NOT NULL AND name != '' ORDER BY month"))
        db.close()
        return names
    except sqlite3.Error:
        return {}


def build(db_path, prev, entry_day, max_price, names, disposed, checked_at):
    """Candidates: prev close in (0, max_price], 20 recorded sessions, 20-day mean amount >= 50M, not under disposition.

    Prices are ex-rights adjusted inside the window so ma5 / ma20 / return_5d_pct are not distorted by dividends.
    disposed is None when the status sources failed: those candidates are kept with trading_status 未知.
    """
    db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    days = [d for (d,) in db.execute("SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day <= ? "
                                     "ORDER BY day DESC LIMIT ?", (prev, WINDOW))][::-1]
    bars = {}
    for s, d, ex, c, a in db.execute('SELECT symbol, day, exchange, close, amount FROM bars WHERE day >= ? AND day <= ?',
                                     (days[0], prev)):
        if STOCK.match(s):
            bars.setdefault(s, {})[d] = (ex, c, a)
    factors = {}
    try:
        for s, d, pc, ref in db.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day > ? AND day <= ?',
                                        (days[0], prev)):
            if pc and ref and pc > 0 and ref > 0:
                factors.setdefault(s, []).append((d, ref / pc))
    except sqlite3.Error:
        pass
    db.close()
    out = []
    for s, by in bars.items():
        if prev not in by or len(by) < WINDOW or len(days) < WINDOW:
            continue
        ex, close, amount = by[prev]
        avg = sum(by[d][2] for d in days) / WINDOW
        if not close or close <= 0 or close > max_price or avg < MIN_AVG_AMOUNT:
            continue
        if disposed is not None and s in disposed:
            continue
        adj = [by[d][1] * _factor(factors.get(s, ()), d) for d in days]
        out.append({'symbol': s, 'name': names.get(s, ''), 'exchange': 'TPEX' if ex.upper().startswith('TP') else 'TWSE',
                    'security_type': '普通股', 'price_date': prev, 'close': close, 'amount': round(amount),
                    'avg_amount_20d': round(avg), 'history_sessions': WINDOW,
                    'ma5': round(sum(adj[-5:]) / 5, 2), 'ma20': round(sum(adj) / WINDOW, 2),
                    'return_5d_pct': round((adj[-1] / adj[-6] - 1) * 100, 2),
                    'trading_status': '未知' if disposed is None else '正常', 'status_checked_at': checked_at})
    out.sort(key=lambda r: (-r['avg_amount_20d'], r['symbol']))
    return out


def _factor(events, day):
    """Multiply an older close by the ex-rights ratios of later days in the window."""
    f = 1.0
    for d, r in events:
        if d > day:
            f *= r
    return f


def as_prompt_json(rows):
    """Compact table: values shared by every row once under "common", then one array per stock."""
    shared = ('security_type', 'price_date', 'history_sessions', 'status_checked_at')
    per_row = tuple(k for k in FIELDS if k not in shared)
    common = {k: rows[0][k] for k in shared} if rows else {}
    return json.dumps({'common': common, 'fields': per_row, 'rows': [[r[k] for k in per_row] for r in rows]},
                      ensure_ascii=False, separators=(',', ':'))
