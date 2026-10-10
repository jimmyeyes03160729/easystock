"""LLM_CONSENSUS_PAPER_V1：每天開盤前問 ChatGPT、Claude、Gemini 短線選股，比較各家、交集與對照組的紙上損益。

規則（2026-10-10 凍結，之後不改；要改就換新版本名）：
- 開盤日 08:00 前後由 `pick` 對啟用的 AI（預設 ChatGPT、Claude；2026-10-10 第一批之前決定不用 Gemini）
  送同一份提示詞（prompt.txt），各取最多 5 檔有效的上市櫃普通股；
  09:00 之後不再凍結名單。名單、原始回覆與 sha256 存在 picks_YYYY-MM-DD.json，之後不再修改。
- 進場：當天（T）開盤價；開盤 >= 參考價 x1.09 視為漲停買不到，該份資金留現金。
- 出場：T 起第 5 個交易日收盤（持有 5 個交易日）。另記錄 T 當天收盤賣出的一日報酬（次要數據）。
- 成本：手續費雙邊 + 證交稅（與營收研究相同的 cost_pct），每組 100 萬平均分配。
- 組別：各家各自、consensus（所有啟用的 AI 都成功且都選）、majority2（啟用三家以上時才有：至少兩家選）、
  hot10（前一交易日成交金額前 10 名）、random5（前一日成交額 >= 5000 萬、股價 >= 10 元中依日期固定亂數抽 5 檔）。
  LLM 組要贏 hot10 與 random5 才算有東西；只贏大盤不算。
- 第二份提示詞 p200（2026-10-10 第一批之前加入，使用者本金 20 萬）：只收前一日收盤 <= 200 元的股票，
  超過的回答記為 invalid；組別加上 p200_ 前綴，hot10 / random5 也只從 <= 200 元的股票挑。
不下單，只做紙上記錄。
"""
import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from short_term import feed as F  # noqa: E402  (same fill, ex-rights and session helpers as the short-term block)
from short_term.feed import R  # noqa: E402
from llm_paper.providers import PROVIDERS, env  # noqa: E402

TPE = timezone(timedelta(hours=8))
RULES_VERSION = 'llm-consensus-paper-v1'
OUT_DIR = Path(os.environ.get('LLM_PAPER_DIR', '/home/ubuntu/easystock-llm-paper'))
DAILY_DB = os.environ.get('LLM_PAPER_DAILY_DB', R.DAILY_DB)
PROMPT_FILE = Path(os.environ.get('LLM_PAPER_PROMPT_FILE', Path(__file__).with_name('prompt.txt')))
PER_MODEL, HOLD, HOT_N, RANDOM_N = 5, 5, 10, 5
MIN_AMOUNT, MIN_PRICE = 50_000_000, 10.0
CAPITAL = 1_000_000
LATEST_FREEZE = '08:55'
MODELS = tuple(m for m in os.environ.get('LLM_PAPER_PROVIDERS', 'openai,claude').split(',') if m in PROVIDERS)
BASE_GROUPS = MODELS + ('consensus',) + (('majority2',) if len(MODELS) > 2 else ()) + ('hot10', 'random5')
# (group prefix, prompt file, max previous close)
VARIANTS = (('', PROMPT_FILE, None), ('p200_', Path(__file__).with_name('prompt_p200.txt'), 200.0))
GROUPS = tuple(v + g for v, _, _ in VARIANTS for g in BASE_GROUPS)


def parse_symbols(text, universe):
    """Ordered unique 4-digit symbols from the reply's JSON (falls back to bare codes); split into valid / invalid."""
    found = []
    m = re.search(r'\{.*\}', text or '', re.S)
    try:
        found = [str(p.get('symbol', '')).strip() for p in json.loads(m.group(0))['picks']] if m else []
    except (ValueError, KeyError, TypeError, AttributeError):
        found = []
    if not found:
        found = re.findall(r'(?<!\d)([1-9]\d{3})(?!\d)', text or '')
    valid, invalid = [], []
    for s in dict.fromkeys(found):
        (valid if s in universe else invalid).append(s)
    return valid[:PER_MODEL], invalid


def build_groups(model_picks, universe, day, models=MODELS):
    """model_picks: {model: [symbols]} (missing model = failed). universe: {symbol: (close, amount)} of the previous session."""
    votes = {}
    for syms in model_picks.values():
        for s in syms:
            votes[s] = votes.get(s, 0) + 1
    order = [s for m in models for s in model_picks.get(m, [])]
    ranked = sorted(universe, key=lambda s: (-universe[s][1], s))
    liquid = sorted(s for s, (c, a) in universe.items() if a >= MIN_AMOUNT and c >= MIN_PRICE)
    rng = random.Random(int(day.replace('-', '')))
    groups = {m: list(model_picks.get(m, [])) for m in models}
    everyone = all(m in model_picks for m in models)
    groups['consensus'] = list(dict.fromkeys(s for s in order if votes[s] == len(models))) if everyone else []
    if len(models) > 2:
        groups['majority2'] = list(dict.fromkeys(s for s in order if votes[s] >= 2))
    groups['hot10'] = ranked[:HOT_N]
    groups['random5'] = sorted(rng.sample(liquid, min(RANDOM_N, len(liquid))))
    return groups


def previous_universe(db_path, today):
    db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    row = db.execute("SELECT max(day) FROM sessions WHERE exchange='TWSE' AND status='open' AND day < ?", (today,)).fetchone()
    prev = row[0]
    uni = {s: (c, a) for s, c, a in db.execute('SELECT symbol, close, amount FROM bars WHERE day = ?', (prev,))
           if R.COMMON.match(s)}
    db.close()
    return prev, uni


def write_frozen(path, data):
    body = json.dumps(data, ensure_ascii=False, indent=1)
    F.write_json(path, data)
    with open(OUT_DIR / 'picks.sha256', 'a', encoding='utf-8') as f:
        f.write('%s  %s  %s\n' % (hashlib.sha256(body.encode('utf-8')).hexdigest(), path.name, data['frozen_at']))


def pick(now, force=False, clock=lambda: datetime.now(TPE)):
    today = now.date().isoformat()
    path = OUT_DIR / ('picks_%s.json' % today)
    if path.exists():
        print('already frozen', path)
        return 0
    if now.strftime('%H:%M') > LATEST_FREEZE and not force:
        print('too late to freeze before the open:', now.isoformat())
        return 1
    prev, universe = previous_universe(DAILY_DB, today)
    prompts = {v: f.read_text(encoding='utf-8').format(date=today, time=now.strftime('%H:%M'), prev_session=prev)
               for v, f, _ in VARIANTS}
    jobs = [(v, m) for v, _, _ in VARIANTS for m in MODELS if env(*PROVIDERS[m][1])]

    def ask(job):
        v, m = job
        try:
            text, meta = PROVIDERS[m][0](prompts[v])
            return v + m, {'ok': True, 'text': text, 'meta': meta}
        except Exception as exc:  # noqa: BLE001  (a failed provider is recorded, the others still run)
            return v + m, {'ok': False, 'error': str(exc)[:500]}
    with ThreadPoolExecutor(max(1, len(jobs))) as pool:
        replies = dict(pool.map(ask, jobs))
    groups, invalid = {}, {}
    for v, _, max_price in VARIANTS:
        uni = {s: ca for s, ca in universe.items() if max_price is None or ca[0] <= max_price}
        model_picks = {}
        for m in MODELS:
            r = replies.setdefault(v + m, {'ok': False, 'error': 'no API key configured'})
            if r['ok']:
                model_picks[m], invalid[v + m] = parse_symbols(r['text'], uni)
        groups.update({v + g: syms for g, syms in build_groups(model_picks, uni, today).items()})
    now_done = clock()
    data = {'rules_version': RULES_VERSION, 'day': today, 'prev_session': prev, 'asked_at': now.isoformat(timespec='seconds'),
            'frozen_at': now_done.isoformat(timespec='seconds'), 'late': now_done >= now.replace(hour=9, minute=0, second=0, microsecond=0),
            'prompt_sha256': {v.rstrip('_') or 'main': hashlib.sha256(p.encode('utf-8')).hexdigest() for v, p in prompts.items()},
            'prompts': {v.rstrip('_') or 'main': p for v, p in prompts.items()},
            'groups': groups, 'invalid': invalid,
            'replies': replies}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_frozen(path, data)
    print(json.dumps({'day': today, 'groups': data['groups'], 'invalid': invalid,
                      'errors': {m: r['error'] for m, r in replies.items() if not r['ok']}}, ensure_ascii=False))
    return 0


def evaluate(batch, sessions, bars, ex, is_closed):
    """Per group: 5-session net % (unfilled names stay cash) and same-day open→close net %, once the data exist."""
    T = batch['day']
    X = F.add_sessions(sessions, T, HOLD, is_closed)
    last = sessions[-1] if sessions else ''
    out = {'day': T, 'exit_day': X, 'late': batch.get('late', False), 'groups': {}}
    if batch.get('late'):                             # frozen after the open: kept on file, never scored
        out['status'] = 'void_late'
        return out
    if last < T:
        out['status'] = 'waiting_entry'
        for g, syms in batch['groups'].items():
            out['groups'][g] = {'symbols': syms}
        return out
    mark = min(last, X)
    for g, syms in batch['groups'].items():
        rets, unfilled = F.position_returns(syms, bars, ex, T, mark)
        day1 = {}
        for s in rets:
            o, c = bars[s][T]['open'], bars[s][T]['close']
            day1[s] = (c / o - 1) * 100 - R.cost_pct(o, c, same_day=True)
        n = len(syms)
        out['groups'][g] = {'symbols': syms, 'n_filled': len(rets), 'unfilled': unfilled,
                            'positions': {s: round(p['net_pct'], 2) for s, p in rets.items()},
                            'net_pct': round(sum(p['net_pct'] for p in rets.values()) / n, 3) if n else None,
                            'day1_net_pct': round(sum(day1.values()) / n, 3) if n else None}
    out['status'] = 'closed' if last >= X else 'holding'
    out['mark_day'] = mark
    return out


def summarize(evals):
    closed = [e for e in evals if e['status'] == 'closed']
    summary = {}
    for g in GROUPS:
        vals = [e['groups'][g]['net_pct'] for e in closed if e['groups'].get(g, {}).get('net_pct') is not None]
        d1 = [e['groups'][g]['day1_net_pct'] for e in closed if e['groups'].get(g, {}).get('day1_net_pct') is not None]
        summary[g] = {'batches': len(vals), 'wins': sum(v > 0 for v in vals),
                      'mean_net_pct': round(sum(vals) / len(vals), 3) if vals else None,
                      'twd_per_1m_mean': round(sum(vals) / len(vals) * 10000) if vals else None,
                      'twd_per_1m_total': round(sum(vals) * 10000),
                      'day1_mean_net_pct': round(sum(d1) / len(d1), 3) if d1 else None}
    return {'closed_batches': len(closed), 'groups': summary}


def load_bars(first_day):
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? ORDER BY day", (first_day,))]
    bars, ex = {}, {}
    for s, d, o, c, rf in daily.execute('SELECT symbol, day, open, close, reference FROM bars WHERE day >= ?', (first_day,)):
        bars.setdefault(s, {})[d] = {'open': o, 'close': c, 'reference': rf}
    for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day >= ?', (first_day,)):
        if ref and ref > 0 and pc and pc > 0:
            ex.setdefault(s, []).append((d, pc / ref))
    daily.close()
    return sessions, bars, ex


def feed(now, publish=True):
    batches = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(OUT_DIR.glob('picks_*.json'))]
    if not batches:
        print('no picks yet')
        return 0
    sessions, bars, ex = load_bars(batches[0]['day'])
    is_closed = F.calendar_closed()
    evals = [evaluate(b, sessions, bars, ex, is_closed) for b in batches]
    data = {'schema_version': 1, 'rules_version': RULES_VERSION, 'generated_at': now.isoformat(timespec='seconds'),
            'rules': {'per_model': PER_MODEL, 'hold_sessions': HOLD, 'capital': CAPITAL, 'groups': list(GROUPS)},
            'summary': summarize(evals), 'batches': sorted(evals, key=lambda e: e['day'], reverse=True)}
    F.write_json(OUT_DIR / 'llm-paper-latest.json', data)
    if publish:
        from firebase_store import FirebaseStore
        FirebaseStore().root.child('public_feed').child('llm_paper').set(data)
    print_report(data)
    return 0


def print_report(data):
    s = data['summary']
    print('LLM 紙上測試（%s）已結束批次：%d' % (data['rules_version'], s['closed_batches']))
    print('%-11s %5s %5s %9s %12s %12s %9s' % ('組別', '批次', '賺錢', '平均淨%', '每百萬平均', '每百萬累計', '一日淨%'))
    for g, v in s['groups'].items():
        pct = lambda x: '-' if x is None else '%.2f' % x  # noqa: E731
        twd = lambda x: '-' if x is None else '{:+,}'.format(x)  # noqa: E731
        print('%-11s %5d %5d %9s %12s %12s %9s' % (g, v['batches'], v['wins'], pct(v['mean_net_pct']),
                                                  twd(v['twd_per_1m_mean']), twd(v['twd_per_1m_total']),
                                                  pct(v['day1_mean_net_pct'])))


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / '.env')            # API keys live only in the VM's project .env
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('pick', 'feed', 'report'))
    ap.add_argument('--force', action='store_true', help='pick: freeze even after 08:55 (marked late, never scored if after 09:00)')
    ap.add_argument('--no-publish', action='store_true')
    a = ap.parse_args()
    now = datetime.now(TPE)
    if a.cmd == 'pick':
        return pick(now, a.force)
    if a.cmd == 'feed':
        return feed(now, publish=not a.no_publish)
    print_report(json.loads((OUT_DIR / 'llm-paper-latest.json').read_text(encoding='utf-8')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
