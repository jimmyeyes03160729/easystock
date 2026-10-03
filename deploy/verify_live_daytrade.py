"""Read-only allowlisted live evidence report. No broker/Firebase calls."""
import argparse
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def report(day, market_dir, research_path):
    from market_data.diagnostics import _source, _count, SOURCES, CONDITIONS, REASONS
    rows=[]
    path=Path(market_dir)/('market-gate-'+day+'.jsonl')
    if path.exists():
        for line in path.open(encoding='utf-8'):
            try:
                raw=json.loads(line)
                if str(raw.get('checked_at',''))[:10]!=day:
                    continue
                rows.append({
                    'timestamp':raw.get('checked_at'), 'trading_date':day,
                    'premarket_level':raw.get('premarket_level'),
                    'premarket_reason':raw.get('premarket_reason'),
                    'selected_source':raw.get('selected_source') if raw.get('selected_source') in SOURCES else None,
                    'data_health':raw.get('data_health'), 'market_risk':raw.get('market_level'),
                    'gate_action':'BLOCK' if raw.get('market_level') in ('RED','UNKNOWN') else 'PASS',
                    'gate_reason':raw.get('gate_reason') if raw.get('gate_reason') in (*REASONS,'market_risk_pass') else 'unknown',
                    'market_condition_reason':raw.get('market_condition_reason') if raw.get('market_condition_reason') in CONDITIONS else 'unknown',
                    'sources':{key:_source((raw.get('sources') or {}).get(key)) for key in SOURCES},
                    'block_counts':{key:_count((raw.get('entry_block_evaluations') or {}).get(key)) for key in REASONS},
                    'radar_candidate_count':_count(raw.get('radar_candidate_count')),
                    'model_ready':raw.get('model_ready') is True})
            except (ValueError, TypeError):
                continue
    trades=[]
    if Path(research_path).is_file():
        from daytrade_learning.episodes import read_trades
        trades=read_trades(research_path,day)
    from learning_status import trade_summary
    return {'date':day,'status':'READY_FOR_LIVE_VALIDATION',
            'qualification':'Human review of full-session coverage and natural events required; fixtures are not live evidence.',
            'market_observations':rows, 'research':trade_summary({},day,trades),
            'natural_daily_limit_skips':sum(t.get('paper_skip_reason')=='daily_buy_limit_exceeded' for t in trades)}


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True)
    parser.add_argument('--market-dir',default='/home/ubuntu/easystock-market-data')
    parser.add_argument('--research',default='/home/ubuntu/easystock-learning-data/research.sqlite')
    args=parser.parse_args()
    from datetime import date
    date.fromisoformat(args.date)
    print(json.dumps(report(args.date,args.market_dir,args.research),ensure_ascii=False,indent=2))
