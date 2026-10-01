"""Dataset quality gate and private, inspectable audit output."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path

from . import DATASET_SCHEMA_VERSION, FEATURE_SCHEMA_VERSION, STRATEGY_VERSION
from .features import extract
from .schema import candidates, connect, database_path


def build_audit(db) -> dict:
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    rows=list(candidates(db))
    critical=[]; warnings=[]
    kinds=Counter(); labels=Counter(); yearly=Counter(); monthly=Counter(); by_symbol=Counter()
    near_miss=Counter(); versions=Counter(); missing=Counter()
    feature_count=Counter(); trainable=0; maturity=0; financial=0; market=0
    seen=set(); first=None; last=None
    bars_by_symbol=defaultdict(list)
    volume_available=0; bar_total=0
    for item in db.execute('SELECT symbol,day,bar FROM daily_bars ORDER BY symbol,day'):
        try:
            bar=json.loads(item['bar'])
            if item['day']>today: critical.append(f'future_kline_timestamp:{item["symbol"]}:{item["day"]}')
            bar_total+=1
            if bar.get('volume') is not None: volume_available+=1
            if bar['time']!=item['day'] or bar['low']<=0 or bar['high']<max(bar['open'],bar['close'],bar['low']) or bar['low']>min(bar['open'],bar['close']):
                critical.append(f'bad_ohlc:{item["symbol"]}:{item["day"]}')
            previous=bars_by_symbol[item['symbol']]
            if previous and previous[-1]>=item['day']:
                critical.append(f'non_monotonic_date:{item["symbol"]}:{item["day"]}')
            previous.append(item['day'])
        except (ValueError,KeyError,TypeError):
            critical.append(f'bad_ohlc:{item["symbol"]}:{item["day"]}')
    for key,snapshot,outcome in rows:
        day=snapshot['signal_date']; symbol=snapshot['symbol']; kind=snapshot['candidate_kind']
        first=min(first,day) if first else day; last=max(last,day) if last else day
        if day>today:critical.append(f'future_signal_date:{key}')
        kinds[kind]+=1; versions[snapshot['strategy_version']]+=1
        yearly[day[:4]]+=1; monthly[day[:7]]+=1; by_symbol[symbol]+=1
        if key in seen: critical.append(f'duplicate_identity:{key}')
        seen.add(key)
        if snapshot['signal_available_at'][:10]!=day or snapshot['signal_available_at'][:19]<f'{day}T13:30:00':
            critical.append(f'future_or_early_signal_timestamp:{key}')
        if snapshot.get('historical_market_context_available'):
            critical.append(f'future_market_context:{key}')
        if snapshot['financial_data_available']: financial+=1
        if snapshot.get('historical_market_context_available'):market+=1
        if kind=='NEAR_MISS': near_miss[snapshot['evidence']['failed_rule']]+=1
        if kind!='REJECTED_CONTROL' and (snapshot['evidence']['target_price'] is None or snapshot['evidence']['invalid_price'] is None):
            critical.append(f'missing_target_or_invalid:{key}')
        if 'label' in snapshot or 'entry_price' in snapshot:
            critical.append(f'candidate_contains_future_label:{key}')
        for name,value in snapshot['features'].items():
            feature_count[name]+=1
            if value is None: missing[name]+=1
        if outcome:
            label=outcome.get('label') or 'UNLABELED'; labels[label]+=1
            if outcome.get('label_maturity_date'): maturity+=1
            if outcome.get('trainable'): trainable+=1
            if outcome.get('entry_date') and outcome['entry_date']<=day:
                critical.append(f'label_before_signal:{key}')
            if outcome.get('entry_price') is not None:
                if snapshot['evidence']['target_price']<=outcome['entry_price']:
                    critical.append(f'target_le_entry:{key}')
                if snapshot['evidence']['invalid_price']>=outcome['entry_price']:
                    critical.append(f'invalid_ge_entry:{key}')
            if outcome.get('reason')=='entry_outside_bracket':
                warnings.append(f'entry_outside_bracket:{key}')
        else: labels['UNLABELED']+=1
    scans=db.execute('SELECT COUNT(*),COALESCE(SUM(symbols_scanned),0),COALESCE(SUM(symbols_expected),0),MIN(day),MAX(day) FROM scan_days').fetchone()
    distinct_scanned=db.execute('''SELECT COUNT(DISTINCT b.symbol) FROM daily_bars b
        JOIN scan_days s ON s.day=b.day''').fetchone()[0]
    if not financial: warnings.append('historical_financial_point_in_time_unavailable')
    if not market: warnings.append('historical_market_context_unavailable')
    if not rows: warnings.append('no_candidates')
    if not kinds['PASSED']:warnings.append('no_pit_verified_passed_candidates')
    for kind in ('PASSED','PENDING','NEAR_MISS'):
        if kinds[kind]<30:warnings.append(f'small_sample_category:{kind}')
    if scans[2] and scans[1]<scans[2]:
        warnings.append('partial_kline_coverage')
    total=len(rows)
    return {
        'dataset_schema_version':DATASET_SCHEMA_VERSION,'feature_schema_version':FEATURE_SCHEMA_VERSION,
        'strategy_version':STRATEGY_VERSION,'strategy_versions':dict(versions),
        'first_signal_date':first,'last_signal_date':last,
        'trading_days_scanned':scans[0],'symbols_scanned':distinct_scanned,
        'stock_days_scanned':scans[1],
        'scan_first_date':scans[3],'scan_last_date':scans[4],
        'total_rows':total,'candidate_kinds':dict(kinds),
        'mature_labels':maturity,'labels':dict(labels),'trainable_rows':trainable,
        'coverage':{
            'kline_bar_count':bar_total,'kline_scan_ratio':round(scans[1]/scans[2],4) if scans[2] else None,
            'volume_bar_ratio':round(volume_available/bar_total,4) if bar_total else None,
            'financial_pit_candidate_ratio':round(financial/total,4) if total else None,
            'historical_market_context_ratio':round(market/total,4) if total else None,
        },
        'missing_feature_rate':{name:round(missing[name]/count,4) for name,count in sorted(feature_count.items())},
        'candidate_distribution':{'year':dict(yearly),'month':dict(monthly),'symbol':dict(by_symbol)},
        'label_distribution':{name:round(labels[name]/total,4) if total else 0 for name in ('SUCCESS','FAIL','TIMEOUT','AMBIGUOUS','UNLABELED')},
        'near_miss_failed_rules':dict(near_miss),
        'data_quality':{
            'duplicate_ids':sum(x.startswith('duplicate_identity:') for x in critical),
            'future_leakage_violations':sum('future' in x or 'label_before_signal' in x for x in critical),
            'critical_count':len(critical),'warning_count':len(warnings),
            'critical_examples':critical[:30],'warnings':warnings[:100],
        },
    }


def markdown(report: dict) -> str:
    quality=report['data_quality']
    lines=['# Rebound AI Phase 1 Dataset Audit','',
           f"Strategy: `{report['strategy_version']}`; schema: {report['dataset_schema_version']}/{report['feature_schema_version']}",
           f"Signals: {report['first_signal_date']}–{report['last_signal_date']}; scanned sessions: {report['trading_days_scanned']}; symbols: {report['symbols_scanned']}; stock-days: {report['stock_days_scanned']}",
           f"Rows: {report['total_rows']}; trainable: {report['trainable_rows']}; mature: {report['mature_labels']}",
           '', '## Candidate kinds', '']
    lines += [f"- {k}: {report['candidate_kinds'].get(k,0)}" for k in ('PASSED','PENDING','NEAR_MISS','REJECTED_CONTROL')]
    lines += ['', '## Labels', '']
    lines += [f"- {k}: {report['labels'].get(k,0)}" for k in ('SUCCESS','FAIL','TIMEOUT','AMBIGUOUS','UNLABELED')]
    lines += ['', '## Coverage', '']
    lines += [f'- {k}: {v}' for k,v in report['coverage'].items()]
    lines += ['', '## Quality', '',f"- Critical: {quality['critical_count']}",f"- Warning: {quality['warning_count']}"]
    lines += [f'- {w}' for w in quality['warnings']]
    lines += ['', 'Historical financial numbers and new real-time market data were not backfilled without publication-time evidence.']
    return '\n'.join(lines)+'\n'


def write_audit(report: dict) -> None:
    root=database_path().parent
    root.mkdir(parents=True,exist_ok=True)
    (root/'rebound-dataset-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    (root/'rebound-dataset-audit.md').write_text(markdown(report),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    with connect() as db: report=build_audit(db)
    if not args.dry_run: write_audit(report)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    if report['data_quality']['critical_count']: raise SystemExit(2)


if __name__=='__main__':main()
