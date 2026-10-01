"""D0-only candidate collection; no labels and no feed publication."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from range_rebound import RULE_VERSION, evaluate_financial, evaluate_technical
from . import DATASET_SCHEMA_VERSION, FEATURE_SCHEMA_VERSION
from .features import extract, near_miss_diagnostics

TPE = timezone(timedelta(hours=8))
SETTINGS = json.loads((Path(__file__).parent / 'settings.json').read_text(encoding='utf-8'))


def verified_financial(stock: dict | None, signal_date: str) -> dict:
    """Only trust a dated as-of snapshot with explicit publication evidence.

    Production's as_of field describes the accounting period/observation, not
    necessarily the public filing time; it alone is insufficient for PIT.
    """
    if not stock:
        return {'status':'unavailable','data_available':False}
    meta=stock.get('field_meta') or {}
    required=('rev_yoy','eps','operating_margin','debt_ratio')
    available_at=f'{signal_date}T22:30:00+08:00'
    for key in required:
        detail=meta.get(key) or {}
        published=detail.get('published_at')
        if not published:
            return {'status':'unavailable','data_available':False}
        try:
            published_at=datetime.fromisoformat(published.replace('Z','+00:00'))
            if published_at.tzinfo is None or published_at.astimezone(TPE)>datetime.fromisoformat(available_at):
                return {'status':'unavailable','data_available':False}
        except ValueError:
            return {'status':'unavailable','data_available':False}
    result=evaluate_financial(stock,signal_date)
    return {'status':result['status'],'data_available':True}


def collect(symbol: str, bars: list[dict], signal_date: str, *, stock: dict | None = None,
            amount_rank: float | None = None, strategy_version: str = RULE_VERSION,
            settings: dict = SETTINGS) -> dict | None:
    if not bars or bars[-1]['time'] != signal_date or any(b['time']>signal_date for b in bars):
        raise ValueError('candidate_future_or_missing_signal_bar')
    if strategy_version != RULE_VERSION:
        raise ValueError('unsupported_strategy_version')
    current=bars[-1]
    if current.get('amount') is None or current['amount']<settings['minimum_amount']:
        return None
    technical=evaluate_technical(bars,signal_date,current['close'])
    finance=verified_financial(stock,signal_date)
    if finance['status'] in ('failed','unsupported'):
        return None
    if technical['eligible']:
        kind='PASSED' if finance['status']=='passed' else 'PENDING'
        research=technical
    else:
        if technical.get('reason') in {
            '缺少日 K','日 K 少於 90 個交易日','K 線與行情日期不一致',
            'K 線結構或日期異常','價格跳空過大，需核對除權息與資料',
            '最新價與日 K 不一致',
        }:
            return None
        research=near_miss_diagnostics(bars,signal_date,tolerance=settings['near_miss_tolerance'])
        if research:
            kind='NEAR_MISS'
        else:
            # A stable, small rejected control sample is optional and has no
            # fabricated target/stop: controls are never trainable.
            digest=int(hashlib.sha256(f'{signal_date}:{symbol}'.encode()).hexdigest(),16)
            if digest % settings['rejected_control_hash_modulus']:
                return None
            kind='REJECTED_CONTROL'
            research={'failed_rule':technical.get('reason'),'eligible':False}
    features=extract(bars,signal_date,research,amount_rank=amount_rank)
    return {
        'dataset_schema_version':DATASET_SCHEMA_VERSION,
        'feature_schema_version':FEATURE_SCHEMA_VERSION,
        'strategy_version':strategy_version,
        'signal_date':signal_date,'signal_available_at':f'{signal_date}T22:30:00+08:00',
        'signal_timestamp_source':'conservative_research_cutoff_not_historical_publish_log',
        'symbol':symbol,'candidate_kind':kind,'financial_status':finance['status'],
        'financial_data_available':finance['data_available'],
        'historical_market_context_available':False,
        'source':'shioaji_daily_pit' if stock is None else 'asof_snapshot',
        'features':features,
        'evidence':{
            'rule_score':research.get('score'),'confirmation':research.get('confirmation'),
            'support_price':sum(research['support'])/2 if research.get('support') else None,
            'resistance_price':sum(research['resistance'])/2 if research.get('resistance') else None,
            'invalid_price':research.get('invalid'),'target_price':research.get('target'),
            'failed_rule':research.get('failed_rule') if kind=='NEAR_MISS' else None,
            'distance_to_threshold':research.get('distance_to_threshold') if kind=='NEAR_MISS' else None,
        },
    }
