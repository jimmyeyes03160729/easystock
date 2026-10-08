#!/usr/bin/env python3
"""REVENUE_FORWARD_V1: forward paper confirmation of REVENUE_DRIFT_V1 on revenue months >= 2026-09.

picks     freeze the decile portfolios on the deadline evening D(M); reads NO price after 2026-10-02
          (liquidity universe frozen as of 2026-10-02) and only trading-calendar membership after it.
evaluate  compute entry/exit returns; reads prices after 2026-10-02 and therefore refuses to run without the
          owner-created file EVAL_AUTHORIZED next to this script (see the preregistration).
"""
import argparse, json, math, re, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import rev_study as R  # noqa: E402  (frozen helpers: add_months, signals_for, sur, deciles, cost_pct)

CUTOFF = '2026-10-02'
DAILY_DB = R.DAILY_DB
FWD = ROOT / 'forward'
UNIVERSE_FILE = FWD / 'universe_frozen.json'
LOOKBACK, MIN_AMOUNT, MIN_PRICE = R.LOOKBACK, R.MIN_AMOUNT, R.MIN_PRICE
SIGNALS = ('S2_SUR', 'S1_YOY')
LIMIT_UP = 1.09


def is_deadline_evening(open_sessions, today):
    """True when today is the first session on or after the 10th of its month (D(M) for M = previous month)."""
    if today not in open_sessions or int(today[8:10]) < 10:
        return False
    first = today[:8] + '10'
    return not any(first <= d < today for d in open_sessions)


def revenue_month_for(today):
    return R.add_months(today[:7], -1)


def frozen_universe(daily):
    """Liquid common stocks as of CUTOFF (prices <= CUTOFF only)."""
    last = daily.execute("SELECT max(day) FROM sessions WHERE exchange='TWSE' AND status='open' AND day <= ?", (CUTOFF,)).fetchone()[0]
    bars = {}
    for s, d, c, a in daily.execute('SELECT symbol, day, close, amount FROM bars WHERE day <= ? AND day >= ?', (CUTOFF, '2026-08-01')):
        if R.COMMON.match(s):
            bars.setdefault(s, []).append((d, c, a))
    out = []
    for s, rows in bars.items():
        rows.sort()
        prior = rows[-LOOKBACK:]
        if prior[-1][0] == last and len(prior) == LOOKBACK and sum(r[2] for r in prior) / LOOKBACK >= MIN_AMOUNT and prior[-1][1] >= MIN_PRICE:
            out.append(s)
    return sorted(out), last


def load_revenue(db_path, month):
    db = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    rows = db.execute('SELECT symbol, month, revenue, last_year FROM revenue WHERE month <= ?', (month,)).fetchall()
    db.close()
    rev = {}
    for s, m, r, ly in rows:
        rev.setdefault(s, {})[m] = (r, ly)
    return rev


def cmd_picks(args):
    FWD.mkdir(exist_ok=True)
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    today = args.today or datetime.now().strftime('%Y-%m-%d')
    open_sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? AND day <= ?", (today[:8] + '01', today))]
    if not args.force and not is_deadline_evening(open_sessions, today):
        print('not a deadline evening:', today)
        return 0
    month = args.month or revenue_month_for(today)
    out = FWD / ('picks_%s.json' % month)
    if out.exists():
        print('picks already frozen:', out)
        return 0
    if UNIVERSE_FILE.exists():
        uni = json.loads(UNIVERSE_FILE.read_text())['symbols']
    else:
        uni, last = frozen_universe(daily)
        UNIVERSE_FILE.write_text(json.dumps({'as_of': last, 'cutoff': CUTOFF, 'rule': 'common 4-digit, 20-session mean amount >= 5e7, last close >= 10', 'symbols': uni}))
    rev = load_revenue(args.revenue_db, month)
    sig = R.signals_for(rev, month)
    picks = {'study': 'REVENUE_FORWARD_V1', 'month': month, 'deadline_session': today,
             'created_at': datetime.now().isoformat(timespec='seconds'), 'universe_size': len(uni), 'signals': {}}
    for name in ('S2_SUR', 'S1_YOY'):
        scores = {s: v for s, v in sig[name].items() if s in set(uni)}
        if len(scores) < 10:
            picks['signals'][name] = {'n_scored': len(scores), 'top': [], 'bottom': [], 'scored': sorted(scores)}
            continue
        top, bottom = R.deciles(scores)
        picks['signals'][name] = {'n_scored': len(scores), 'top': top, 'bottom': bottom, 'scored': sorted(scores)}
    out.write_text(json.dumps(picks, indent=1))
    print('frozen', out, {k: (v['n_scored'], len(v['top'])) for k, v in picks['signals'].items()})
    return 0


def cmd_evaluate(args):
    if not (ROOT / 'EVAL_AUTHORIZED').exists():
        print('EVAL_AUTHORIZED missing: this step reads prices after', CUTOFF, 'and needs the owner decision recorded in git.')
        return 3
    picks = json.loads((FWD / ('picks_%s.json' % args.month)).read_text())
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    sessions = [d for (d,) in daily.execute("SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' ORDER BY day")]
    D = picks['deadline_session']
    E = next((d for d in sessions if d > D), None)
    out = {'month': picks['month'], 'entry': E, 'results': {}}
    for h, n in (('H5', 5), ('H20', 20)):
        iE = sessions.index(E) if E in sessions else None
        if iE is None or iE + n - 1 >= len(sessions):
            out['results'][h] = 'NOT_YET_COMPLETE'
            continue
        X = sessions[iE + n - 1]
        syms = sorted({s for v in picks['signals'].values() for s in v['scored']})
        bars = {}
        for s, d, o, c, rf in daily.execute('SELECT symbol, day, open, close, reference FROM bars WHERE day BETWEEN ? AND ?', (E, X)):
            if s in set(syms):
                bars.setdefault(s, {})[d] = (o, c, rf)
        ex = {}
        for s, d, pc, ref in daily.execute('SELECT symbol, day, previous_close, reference FROM ex_rights WHERE day > ? AND day <= ?', (E, X)):
            if ref and ref > 0 and pc and pc > 0:
                ex.setdefault(s, []).append(pc / ref)
        ret = {}
        for s in syms:
            by = bars.get(s, {})
            if E not in by or not by[E][0] or by[E][0] <= 0 or (by[E][2] and by[E][0] >= LIMIT_UP * by[E][2]):
                continue
            exit_px = by[X][1] if X in by else by[max(d for d in by if d < X)][1]
            f = math.prod(ex.get(s, [1.0]))
            ret[s] = (exit_px * f / by[E][0] - 1) * 100 - R.cost_pct(by[E][0], exit_px, same_day=False)
        res = {'exit': X}
        for name, v in picks['signals'].items():
            ok = [s for s in v['scored'] if s in ret]
            top = [s for s in v['top'] if s in ret]
            if not top or not ok:
                continue
            u, t = sum(ret[s] for s in ok) / len(ok), sum(ret[s] for s in top) / len(top)
            res[name] = {'n_top': len(top), 'n_universe': len(ok), 'top_net_pct': t, 'universe_net_pct': u, 'excess_pct': t - u}
        out['results'][h] = res
    print(json.dumps(out, indent=1))
    (FWD / ('result_%s.json' % args.month)).write_text(json.dumps(out, indent=1))
    return 0


def cmd_due(args):
    """Print the revenue month to freeze when today is a deadline evening without frozen picks; exit 0, else exit 1."""
    daily = sqlite3.connect('file:%s?mode=ro' % DAILY_DB, uri=True)
    today = args.today or datetime.now().strftime('%Y-%m-%d')
    open_sessions = [d for (d,) in daily.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' AND day >= ? AND day <= ?", (today[:8] + '01', today))]
    month = revenue_month_for(today)
    if is_deadline_evening(open_sessions, today) and not (FWD / ('picks_%s.json' % month)).exists():
        print(month)
        return 0
    return 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('picks')
    p.add_argument('--revenue-db', default=str(FWD / 'revenue.sqlite'))
    p.add_argument('--today')
    p.add_argument('--month')
    p.add_argument('--force', action='store_true')
    d = sub.add_parser('due')
    d.add_argument('--today')
    e = sub.add_parser('evaluate')
    e.add_argument('--month', required=True)
    args = ap.parse_args()
    return {'picks': cmd_picks, 'evaluate': cmd_evaluate, 'due': cmd_due}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
