#!/usr/bin/env python3
"""Read-only evidence audit/replay. Never writes research history or paper cash."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import subprocess
import sqlite3
from contextlib import closing
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daytrade_learning.episodes import read_trades
from position_manager import PositionManager

TPE = timezone(timedelta(hours=8))
GATES = ('market_pass', 'strategy_pass', 'model_pass', 'settings_pass',
         'fresh_quote_pass', 'entry_window_pass', 'radar_pass')


def cannot(*missing):
    return {'status':'cannot_reconstruct_without_lookahead', 'missing':list(missing),
            'historical_trades_written':0, 'paper_fills_written':0}


def replay(evidence, day, symbol):
    """Only an explicitly complete point-in-time timeline can be replayed.

    The caller must supply complete ticks and accepted/false predicates, including
    completed-bar technical decisions. Sparse journal samples and logs do not
    satisfy this contract. Coverage is an input attestation, not inferred here.
    """
    coverage = evidence.get('coverage', {})
    if not all(coverage.get(key) is True for key in
               ('complete_ticks','complete_predicates','complete_technical_decisions')):
        return cannot('complete ordered tick stream', 'post-close false/true setup evidence',
                      'point-in-time technical exit decisions')
    policy = evidence.get('exit_policy', {})
    if set(policy) - {'stop_loss_pct','take_profit_pct','trailing_activate_pct','trailing_pullback_pct',
                      'exit_mode','breakeven_activate_pct','breakeven_floor_pct','technical_exit_enabled'}:
        return cannot('recorded strategy exit policy only')
    result, last = [], None
    try:
        manager = PositionManager(research_mode=True, **policy)
        for row in evidence['events']:
            at = datetime.fromisoformat(row['at'])
            if at.tzinfo is None or at.astimezone(TPE).date().isoformat() != day:
                return cannot('same-day timezone-aware event timestamps')
            if last is not None and at < last:
                return cannot('events in original chronological order')
            last = at
            if row.get('symbol') != symbol:
                continue
            if any(key in row for key in ('day_high','day_low','close_price','future_bars')):
                return cannot('input free of future-derived entry evidence')
            kind = row['kind']
            event = None
            if kind == 'tick':
                event = manager.on_tick(symbol, row['price'], at)
            elif kind == 'strategy':
                completed_at = datetime.fromisoformat(row['bar_completed_at'])
                if completed_at.tzinfo is None or completed_at > at:
                    return cannot('technical decision using only completed bars')
                event = manager.on_strategy_result(symbol, row['result'], at)
            elif kind == 'predicate':
                gates = row['gates']
                if any(type(gates.get(key)) is not bool for key in GATES):
                    return cannot('all formal ENTRY gate results at each predicate observation')
                accepted = all(gates[key] for key in GATES)
                manager.observe_entry_predicate(symbol, accepted, at)
                if accepted:
                    quote = datetime.fromisoformat(row['quote_at'])
                    if quote.tzinfo is None or not 0 <= (at-quote).total_seconds() <= 30:
                        return cannot('fresh quote at the actual entry observation')
                    if row.get('decision_mode') == 'model':
                        decision = row['model_decision']
                        probability, threshold = float(decision['probability']), float(decision['threshold'])
                        if (not math.isfinite(probability) or not math.isfinite(threshold)
                                or threshold < .6 or probability < threshold
                                or not all(decision.get(key) is True for key in ('active','evaluated','approved','accepted'))):
                            return cannot('approved model acceptance at its original threshold')
                    elif row.get('decision_mode') != 'rules' or row.get('rule_eligible') is not True:
                        return cannot('formal rule or model acceptance evidence')
                    # This replay is a research counterfactual, never a paper fill.
                    event = manager.open_position(symbol, row.get('name',symbol),
                        row['price'], at, row.get('score'), row.get('reasons',[]),
                        decision_evidence={'entry_gate_evidence':gates})
            else:
                return cannot('recognized point-in-time event kind')
            if event:
                trade = event.get('position', event.get('trade'))
                result.append({key: (value.isoformat() if isinstance(value,datetime) else value)
                               for key,value in trade.items()
                               if key in ('symbol','status','entry_time','entry_price','exit_time',
                                          'exit_price','exit_reason','pnl_pct','mfe_pct','mae_pct')})
        if manager.positions:
            return cannot('complete evidence through strategy exit (episode remains OPEN)')
        if not result:
            return cannot('an accepted formal ENTRY predicate')
        return {'status':'deterministic_read_only_replay', 'coverage_basis':'caller_attested_complete_timeline',
                'episodes':result, 'closed_count':len(manager.closed_trades),
                'historical_trades_written':0, 'paper_fills_written':0}
    except (KeyError, ValueError, TypeError, OverflowError):
        return cannot('valid complete point-in-time event schema')


def audit(data, day, symbol, wallet=None):
    rows = [row for row in read_trades(Path(data)/'research.sqlite',day) if row['symbol']==symbol]
    if rows:
        return {'status':'persisted_research_evidence', 'count':len(rows),
                'episodes':[{key:row.get(key) for key in ('research_trade_id','episode_id','status',
                             'entry_time','exit_time','exit_reason','paper_execution','paper_skip_reason')}
                            for row in rows], 'historical_trades_written':0}
    journal = Path(data)/('journal-'+day+'.jsonl')
    counts = {}
    if journal.exists():
        with journal.open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if row.get('data',{}).get('symbol') == symbol:
                        counts[row.get('kind','unknown')] = counts.get(row.get('kind','unknown'),0)+1
                except (ValueError, TypeError):
                    continue
    # No secret-bearing log lines leave the audit: count only symbol-matched markers.
    log_counts = {}
    try:
        end = (datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()
        output = subprocess.run(['journalctl','-u','easystock-intraday.service','--since',day,
            '--until',end,'--no-pager','-o','cat'], capture_output=True,text=True,timeout=30)
        for line in output.stdout.splitlines():
            if symbol in line:
                for marker in ('[MODEL_DECISION]','[STRATEGY]','[ENTRY_DECISION]'):
                    if marker in line:
                        log_counts[marker] = log_counts.get(marker,0)+1
    except (OSError, subprocess.TimeoutExpired):
        pass
    paper_observations = []
    if wallet is not None and Path(wallet).is_file():
        try:
            with closing(sqlite3.connect(Path(wallet).resolve().as_uri()+'?mode=ro',uri=True)) as db:
                for stamp, price, reason in db.execute(
                    "SELECT time_str,price,reason FROM paper_trade_events "
                    "WHERE date=? AND symbol=? AND action='略過' ORDER BY created_at", (day,symbol)):
                    if '不足' in str(reason):
                        paper_observations.append({'at':str(stamp),'price':price,'reason':'insufficient_cash'})
        except (OSError, sqlite3.Error):
            pass
    return dict(cannot('complete ordered 3189 ticks at/after 10:33',
                       'formal ENTRY gate evidence and completed bars at 10:33',
                       'exit and false-to-true re-arm evidence before/at 12:07'),
                day=day,symbol=symbol,journal_counts=counts,log_marker_counts=log_counts,
                paper_cash_skip_count=len(paper_observations),
                paper_cash_skip_observations=paper_observations[:30],
                paper_observation_basis='execution attempts alone cannot reconstruct formal research episodes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',default='/home/ubuntu/easystock-learning-data')
    parser.add_argument('--day',default='2026-10-01')
    parser.add_argument('--symbol',default='3189')
    parser.add_argument('--wallet',type=Path,default=Path('/home/ubuntu/easystock-admin/state.sqlite'))
    parser.add_argument('--evidence',type=Path,help='complete, ordered captured timeline JSON; never minute-bar interpolation')
    args = parser.parse_args()
    result = (replay(json.loads(args.evidence.read_text()),args.day,args.symbol) if args.evidence
              else audit(args.data,args.day,args.symbol,args.wallet))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status'] != 'cannot_reconstruct_without_lookahead' else 2


if __name__ == '__main__':
    raise SystemExit(main())
