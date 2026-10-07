"""Rebound dataset v2: official whole-market daily replay with PIT context.

Separate SQLite (dataset-v2.sqlite) so v1 snapshots stay immutable. Each
stock is processed alone to fit a 1 GB VM. Nothing publishes a feed,
changes rebound_feed/Top 3 or trains a model.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta

from .audit import build_audit, write_audit
from .collector import SETTINGS, TPE, collect_v2
from .features import market_context
from .labels import update_labels
from .market_daily import (Client, connect as market_connect, fetch_day, fetch_ex_rights, future_bars,
                           load_histories, refresh_amount_ranks, weekdays)
from .schema import connect, database_path, save_candidate

FEATURE_SCHEMA_VERSION = 2
WINDOW = 252
MIN_BARS = 90


def dataset_path():
    return database_path().parent / 'dataset-v2.sqlite'


def scaled(bars: list[dict]) -> tuple[list[dict], list[float]]:
    """S_j = raw_j / C_j with C_j the product of factors up to j.

    For a reader at D0=k the adjusted prefix is S_j * C_k: a constant scale,
    and the rule is scale invariant, so S slices can be used directly while
    price_basis=C_k restores actual D0 price levels. C_k only uses events <= k.
    """
    out, cums, cum = [], [], 1.0
    for b in bars:
        cum *= b['adj_factor']
        out.append({'time': b['time'], 'open': b['open'] / cum, 'high': b['high'] / cum,
                    'low': b['low'] / cum, 'close': b['close'] / cum,
                    'volume': b['volume'], 'amount': b['amount']})
        cums.append(cum)
    return out, cums


def sessions(market) -> list[str]:
    return [r[0] for r in market.execute(
        "SELECT day FROM sessions WHERE exchange='TWSE' AND status='open' ORDER BY day")]


def build_context(market, days: list[str]) -> dict[str, dict]:
    closes: dict[str, dict[str, float]] = {'TAIEX': {}, 'TPEX': {}}
    for r in market.execute('SELECT day,name,close FROM indices'):
        closes.setdefault(r['name'], {})[r['day']] = r['close']
    up, down = Counter(), Counter()
    for _, _, bars in load_histories(market):
        series, _ = scaled(bars)
        for previous, bar in zip(series, series[1:]):
            if bar['close'] > previous['close'] * 1.0000001:
                up[bar['time']] += 1
            elif bar['close'] < previous['close'] * 0.9999999:
                down[bar['time']] += 1
    breadth = {d: round(up[d] / (up[d] + down[d]), 6) for d in days if up[d] + down[d]}
    return market_context(days, closes, breadth)


def amount_ranks(market, symbol: str) -> dict[str, float]:
    return {r[0]: r[1] for r in market.execute('SELECT day,rank FROM amount_ranks WHERE symbol=?', (symbol,))}


def run(market, db, start: str, end: str, *, symbols: list[str] | None = None,
        settings: dict = SETTINGS, progress: bool = True) -> dict:
    calendar = sessions(market)
    db.executemany('INSERT OR IGNORE INTO trading_days(day) VALUES(?)', ((d,) for d in calendar))
    db.execute('''CREATE TABLE IF NOT EXISTS v2_progress (
        symbol TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, PRIMARY KEY(symbol,start,end))''')
    db.commit()
    refresh_amount_ranks(market)
    context = build_context(market, calendar)
    done = {r[0] for r in db.execute('SELECT symbol FROM v2_progress WHERE start=? AND end=?', (start, end))}
    saved = reused = evaluated = 0
    kinds = Counter()
    names = symbols or [r[0] for r in market.execute('SELECT DISTINCT symbol FROM bars ORDER BY symbol')]
    for n, symbol in enumerate(names, start=1):
        if symbol in done:
            continue
        _, _, raw = next(load_histories(market, [symbol]))
        series, cums = scaled(raw)
        frozen = {r[0] for r in db.execute('''SELECT signal_date FROM candidates
            WHERE symbol=? AND feature_schema_version=?''', (symbol, FEATURE_SCHEMA_VERSION))}
        ranks = None
        for k, bar in enumerate(series):
            day = bar['time']
            if day < start or day > end or k + 1 < MIN_BARS:
                continue
            if day in frozen:
                reused += 1
                continue
            if bar['amount'] is None or bar['amount'] < settings['minimum_amount']:
                continue
            if ranks is None:
                ranks = amount_ranks(market, symbol)
            first = max(0, k - WINDOW + 1)
            unknown = sum(1 for b in raw[first + 1:k + 1] if b['adj_status'] == 'unknown')
            evaluated += 1
            row = collect_v2(symbol, series[first:k + 1], day, exchange=raw[k]['exchange'],
                             context=context.get(day, {}), price_basis=cums[k], adj_unknown=unknown,
                             amount_rank=ranks.get(day), settings=settings)
            if row:
                save_candidate(db, row)
                saved += 1
                kinds[row['candidate_kind']] += 1
        db.execute('INSERT OR IGNORE INTO v2_progress VALUES (?,?,?)', (symbol, start, end))
        db.commit()
        if progress and n % 50 == 0:
            print(f'[rebound-v2] {n}/{len(names)} symbols, saved {saved}, kinds {dict(kinds)}',
                  file=sys.stderr, flush=True)
    for day in (d for d in calendar if start <= d <= end):
        count = market.execute('SELECT COUNT(*) FROM bars WHERE day=?', (day,)).fetchone()[0]
        db.execute('''INSERT INTO scan_days(day,symbols_scanned,symbols_expected,source) VALUES(?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET symbols_scanned=excluded.symbols_scanned,
            symbols_expected=excluded.symbols_expected,source=excluded.source''',
                   (day, count, count, 'official_daily'))
    db.commit()
    return {'start': start, 'end': end, 'symbols': len(names), 'stock_days_evaluated': evaluated,
            'candidate_events': saved, 'candidate_snapshots_reused': reused, 'kinds': dict(kinds)}


def label(market, db) -> int:
    return update_labels(db, load_future=lambda symbol, day: future_bars(market, symbol, day),
                         skip_matured=True)


def audit(market, db, *, write: bool = True) -> dict:
    """Audit the historical partition only; reserved confirmation rows stay blinded."""
    reserved = SETTINGS['reserved_confirmation_start']
    report = build_audit(db, before=reserved)
    report['blinded_from'] = reserved
    report['dataset_schema_version'] = 2
    report['feature_schema_version'] = FEATURE_SCHEMA_VERSION
    report['symbols_scanned'] = market.execute('SELECT COUNT(DISTINCT symbol) FROM bars').fetchone()[0]
    report['coverage']['adj_unknown_candidate_ratio'] = None
    unknown = db.execute("SELECT COUNT(*) FROM candidates WHERE json_extract(snapshot,'$.adj_unknown_events_252d')>0 AND signal_date<?",
                         (reserved,)).fetchone()[0]
    if report['total_rows']:
        report['coverage']['adj_unknown_candidate_ratio'] = round(unknown / report['total_rows'], 4)
    # v2 bars live in market-daily.sqlite, not daily_bars; v1-only warnings do not apply.
    quality = report['data_quality']
    quality['warnings'] = [w for w in quality['warnings']
                           if w not in ('historical_market_context_unavailable', 'partial_kline_coverage')]
    quality['warning_count'] = len(quality['warnings'])
    if write:
        write_audit(report, name='rebound-dataset-v2-audit')
    return report


def daily(market, db) -> dict:
    """After-hours refresh: recent sessions, last five replays, labels, audit."""
    today = datetime.now(TPE).date()
    client = Client()
    for month in sorted({today.strftime('%Y-%m'), (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')}):
        fetch_ex_rights(market, client, month)
    for day in weekdays((today - timedelta(days=10)).isoformat(), today.isoformat()):
        fetch_day(market, client, day)
    recent = sessions(market)[-5:]
    if not recent:
        raise RuntimeError('no_official_sessions')
    run(market, db, recent[0], recent[-1], progress=False)
    label(market, db)
    report = audit(market, db)
    # Candidate counts, kinds and labels on reserved sessions are outcome-bearing:
    # report admin metadata only (pristine holdout REBOUND_V2_FUTURE_60D).
    return {'sessions_replayed': recent, 'blinded_from': report['blinded_from'],
            'audit_critical': report['data_quality']['critical_count']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('backfill', 'labels', 'audit', 'daily'))
    parser.add_argument('--from', dest='start', default='2023-01-03')
    parser.add_argument('--to', dest='end', default=datetime.now(TPE).date().isoformat())
    parser.add_argument('--symbols', help='comma-separated subset for sampling runs')
    args = parser.parse_args()
    with market_connect() as market, connect(dataset_path()) as db:
        if args.command == 'backfill':
            result = run(market, db, args.start, args.end,
                         symbols=args.symbols.split(',') if args.symbols else None)
        elif args.command == 'labels':
            result = {'labels_updated': label(market, db)}
        elif args.command == 'audit':
            report = audit(market, db)
            result = {k: report[k] for k in ('total_rows', 'trainable_rows', 'candidate_kinds', 'labels')}
            result['critical'] = report['data_quality']['critical_count']
        else:
            result = daily(market, db)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command in ('audit', 'daily') and result.get('critical', result.get('audit_critical')):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
