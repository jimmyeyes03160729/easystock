"""Shared, versioned daily eligibility. Scores are rankings, never probabilities.
No network or Firebase writes. Historical and current technical rules use this module.
"""
from datetime import date
import math

RULE_VERSION = '2.0.0'
MIN_SCORE = 70


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == '':
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def bounded(value, lo=0, hi=1):
    return max(lo, min(hi, value))


def technical_decision(strategy, f):
    """Point-in-time daily prices; entry next session, primary exit day 10 close.
    Liquidity and snapshot checks are separate live eligibility gates and are
    explicitly NOT covered by this technical-only historical diagnostic.
    """
    keys = ['close', 'open', 'ma20', 'ma60', 'near_high', 'sharpe',
            'vol_ratio', 'recent_min_low', 'momo20', 'range_position']
    v = {k: number(f.get(k)) for k in keys}
    missing = [k for k, x in v.items() if x is None]
    if missing:
        return {'eligible': False, 'score': 0, 'reasons': ['技術資料不足：' + ', '.join(missing)]}
    c, m20, m60 = v['close'], v['ma20'], v['ma60']
    if min(c, m20, m60, v['open']) <= 0:
        return {'eligible': False, 'score': 0, 'reasons': ['價格或均線無效']}
    trend = c > m20 >= m60
    extension = c / m20 - 1
    if strategy == 'swing':
        valid = (trend and v['near_high'] >= .90 and v['sharpe'] >= .5
                 and .8 <= v['vol_ratio'] <= 4 and extension <= .12)
        score = (bounded(v['near_high']) * 50
                 + bounded((v['sharpe'] + 1) / 3) * 30 + (20 if trend else 0))
        reasons = ['站上20/60日均線且均線多頭', '距近期高點10%內', '量能與乖離通過檢查']
    elif strategy == 'rebound':
        low = v['recent_min_low']
        touch = any(ma * .97 <= low <= ma * 1.02 for ma in (m20, m60))
        valid = (trend and touch and c > v['open'] and v['momo20'] >= 1
                 and .8 <= v['vol_ratio'] <= 3 and extension <= .06)
        score = (45 + bounded(v['near_high']) * 20
                 + bounded(v['vol_ratio'] / 2) * 20
                 + bounded((v['range_position'] - .3) / .7) * 15)
        reasons = ['多頭均線附近回踩後轉強', '20日動能非負', '量能與乖離通過檢查']
    else:
        return {'eligible': False, 'score': 0, 'reasons': ['未知策略']}
    score = round(score, 2)
    return {'eligible': bool(valid and score >= MIN_SCORE), 'score': score,
            'reasons': reasons if valid else ['未通過趨勢、回踩／高點、量能或乖離門檻']}


def fresh_field(stock, field, asof, max_age=120):
    info = (stock.get('field_meta') or {}).get(field) or {}
    try:
        age = (date.fromisoformat(asof) - date.fromisoformat(info['as_of'])).days
        return number(stock.get(field)) is not None and 0 <= age <= max_age
    except (KeyError, ValueError, TypeError):
        return False


def long_decision(stock, asof):
    required = ['roe', 'eps', 'fcf', 'debt_ratio', 'pe', 'yield_pct', 'dividend_continuity_years']
    missing = [k for k in required if not fresh_field(stock, k, asof)]
    finance = any(x in str(stock.get('category', '')) for x in ('金融', '保險', '銀行'))
    if finance:
        return {'eligible': False, 'score': 0, 'reasons': ['金融業專用財務模型尚未建立，不套用一般企業負債與現金流門檻']}
    if missing:
        return {'eligible': False, 'score': 0, 'reasons': ['長期資料不足或過期：' + ', '.join(missing)]}
    v = {k: number(stock[k]) for k in required}
    valid = (v['roe'] > 0 and v['eps'] > 0 and v['fcf'] > 0
             and 0 <= v['debt_ratio'] < 70 and v['pe'] > 0
             and v['yield_pct'] >= 4 and v['dividend_continuity_years'] >= 3)
    score = round(30 * bounded(v['roe'] / 20) + 25 * bounded(v['yield_pct'] / 8)
                  + 20 * bounded(v['dividend_continuity_years'] / 5)
                  + 15 * bounded((70 - v['debt_ratio']) / 70)
                  + 10 * bounded((30 - v['pe']) / 30), 2)
    return {'eligible': bool(valid and score >= MIN_SCORE), 'score': score,
            'reasons': ['獲利與正自由現金流', '至少3年配息紀錄', '收益型長期觀察；尚無長期策略回測'] if valid else ['未通過獲利、現金流、配息或估值門檻']}


def stock_decisions(stock, asof):
    f = dict(zip(['close','open','ma20','ma60','near_high','sharpe','vol_ratio','recent_min_low','momo20','range_position'],
                 [stock.get(k) for k in ['price','open','sma20','sma60','near_high_ratio','sharpe20','volume_ratio','recent_min_low_3','momo20','range_position']]))
    out = {name.upper(): technical_decision(name, f) for name in ('rebound', 'swing')}
    out['LONG'] = long_decision(stock, asof)
    common = []
    if stock.get('updated_at') != asof: common.append('行情日期不一致')
    if (number(stock.get('amount')) or 0) < 50_000_000: common.append('日成交金額低於5,000萬元')
    if (number(stock.get('kline_count')) or 0) < 60: common.append('歷史不足60根日K')
    for key, d in out.items():
        if key == 'SWING' and (number(stock.get('kline_count')) or 0) < 250:
            d['eligible'] = False
            d['reasons'] = ['強勢波段需250根日K']
        if common:
            d['eligible'] = False
            d['reasons'] = common + d['reasons']
        d['holding_period'] = '3–12個月觀察／未驗證' if key == 'LONG' else '10個交易日／日線技術研究'
    return {'version': RULE_VERSION, 'as_of': asof, 'strategies': out}
