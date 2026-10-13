"""Causal opening classification and versioned closing observations."""
import math
from datetime import datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8), 'Asia/Taipei')
OPENING = 'OPENING_EIGHT_METHODS_V1'
CLOSING = 'CLOSING_EIGHT_METHODS_V1'
SOURCE_OPEN = 'https://www.yunfar.com.tw/GBSSKILL/starting-8ways.html'
# Reference numbering is deliberately NOT lexicographic.
PATTERNS = ['UUU', 'UUD', 'UDD', 'DUU', 'DDU', 'DDD', 'DUD', 'UDU']
DESCRIPTIONS = ['連續上行', '先升後回落', '上行後連續回落', '下行後連續回升',
                '連續下行後回升', '連續下行', '下上交錯', '上下交錯']
RULESETS = {
    'TW_CLOSING_RULES_V1': {'currency': 'TWD', 'gain': [3, 5], 'turnover': [2, 10],
                        'cap': [5e9, 50e9], 'ratio_min_exclusive': 1, 'high_ratio': .98},
    'CN_ORIGINAL_V1': {'currency': 'CNY', 'gain': [3, 5], 'turnover': [5, 10],
                       'cap': [5e9, 20e9], 'ratio_min_exclusive': 1, 'high_ratio': 1,
                       'enabled': False, 'volume': '持續放大', 'trend': '短期均線與60日線向上',
                       'position': '尾盤創新高且不跌破均線；未量化，不套用台股腳本'},
}
LABELS = ['當日漲幅', '成交量比', '換手率', '市值', '成交量擴張', '均線趨勢', '相對大盤強度', '接近當日高點']

def number(x, positive=False):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and (not positive or x > 0)

def stamp(s):
    t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('timezone required')
    return t.astimezone(TPE)

def opening(previous_close, quotes, now):
    now = now.astimezone(TPE)
    result = {'version': OPENING, 'status': 'insufficient', 'method': None, 'directions': [], 'prices': [], 'reason': ''}
    if now.strftime('%H:%M:%S') < '09:15:00':
        return dict(result, status='pending', reason='09:15 前尚未完成')
    if not number(previous_close, True):
        return dict(result, reason='沒有有效昨收')
    prices = [previous_close]
    for clock in ['09:05', '09:10', '09:15']:
        boundary = stamp(now.date().isoformat() + 'T' + clock + ':00+08:00')
        valid = []
        for q in quotes:
            try:
                at, available = stamp(q['quote_at']), stamp(q.get('available_at', q['quote_at']))
                if at <= boundary and available <= now and 0 <= (boundary-at).total_seconds() <= 30 and number(q.get('price'), True):
                    valid.append((at, q['price']))
            except (KeyError, ValueError, TypeError):
                continue
        if not valid:
            return dict(result, prices=prices, reason=clock + ' 缺 Tick 或行情超過 30 秒')
        prices.append(max(valid, key=lambda x: x[0])[1])
    directions = ['U' if b > a else 'D' if b < a else '=' for a, b in zip(prices, prices[1:])]
    if '=' in directions:
        return dict(result, prices=prices, directions=directions, reason='平盤，未分類')
    return dict(result, status='classified', prices=prices, directions=directions,
                method=PATTERNS.index(''.join(directions))+1, reason='三段價格型態，非買入訊號')

def closing(row, now, ruleset='TW_CLOSING_RULES_V1'):
    rule = RULESETS[ruleset]
    if rule.get('enabled') is False:
        raise ValueError('CN original qualitative rules are archived, not implemented with TW thresholds')
    now = now.astimezone(TPE)
    clock = now.strftime('%H:%M:%S')
    phase = 'waiting' if clock < '13:00:00' else 'observing' if clock < '13:25:00' else 'auction' if clock < '13:30:00' else 'ended'
    reason = '等待 13:00' if phase == 'waiting' else '連續交易訊號已截止' if phase != 'observing' else ''
    try:
        at = stamp(row['quote_at'])
        fresh = at.date() == now.date() and 0 <= (now-at).total_seconds() <= 30
    except (KeyError, ValueError, TypeError):
        fresh = False
    if phase == 'observing' and not fresh:
        reason = '行情過期、缺時間戳或未來行情'
    p, prev = row.get('price'), row.get('previous_close')
    gain = (p/prev-1)*100 if number(p, True) and number(prev, True) else None
    v, vols, closes = row.get('day_volume'), row.get('past_volumes', []), row.get('past_closes', [])
    volume_ok = len(vols) >= 5 and all(number(x, True) for x in vols[-5:]) and number(v) and v >= 0
    ratio = v/(sum(vols[-5:])/5) if volume_ok else None
    ma_ok = len(closes) >= 60 and all(number(x, True) for x in closes[-60:]) and number(p, True)
    if ma_ok:
        series = closes[-60:] + [p]
        ma = lambda n: sum(series[-n:])/n
        trend = ma(5) > ma(20) > ma(60) > sum(closes[-60:])/60
    else:
        trend = None
    turnover, cap, benchmark, high = (row.get(k) for k in ['turnover_pct', 'market_cap', 'benchmark_gain_pct', 'day_high'])
    tests = [None if gain is None else rule['gain'][0]-1e-9 <= gain <= rule['gain'][1]+1e-9,
             None if ratio is None else ratio > rule['ratio_min_exclusive'],
             None if not number(turnover) else rule['turnover'][0] <= turnover <= rule['turnover'][1],
             None if not number(cap, True) or row.get('cap_currency') != rule['currency'] else rule['cap'][0] <= cap <= rule['cap'][1],
             None if not volume_ok else (v > vols[-1] and vols[-1] > vols[-2]*.8),
             trend, None if gain is None or not number(benchmark) else gain > benchmark,
             None if not number(p, True) or not number(high, True) or high < p else p >= high*rule['high_ratio']]
    missing = ['缺昨收或有效股價', '缺累積成交股數或前五交易日量', '缺可靠換手率', '缺同幣別總市值',
               '缺累積成交量或歷史量', '缺 60 個交易日收盤價', '缺同時點大盤漲幅', '缺當日完整高點']
    conditions = [{'id': i+1, 'label': label, 'state': 'insufficient' if reason or value is None else 'pass' if value else 'fail',
                   'reason': reason or (missing[i] if value is None else '')} for i, (label, value) in enumerate(zip(LABELS, tests))]
    return {'version': CLOSING, 'ruleset': ruleset, 'phase': phase, 'gain_pct': gain if fresh else None,
            'conditions': conditions, 'passed': sum(c['state'] == 'pass' for c in conditions),
            'complete': all(c['state'] != 'insufficient' for c in conditions), 'reason': reason}
