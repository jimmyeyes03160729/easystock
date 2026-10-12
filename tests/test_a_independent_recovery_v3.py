"""Causal/safety tests for offline hypotheses, not trading-profit validation."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import ast
import gzip
import hashlib
import json
import subprocess
import sys
import pytest

import daytrade_learning.a_recovery_v2 as common
import daytrade_learning.a_independent_recovery_v3 as core
from deploy.backtest_a_recovery_v2 import group_bars
from deploy.backtest_a_independent_recovery_v3 import (
    RecordedRadar, load_day, signals_for_day, simulate,
)

DAY = '2026-10-01'
TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 9, 30, 3, tzinfo=TPE)


def bars(kind='direct'):
    rows = [(79,79.6,78.8,79.2,100), (79.2,80,79.2,79.8,100),
            (79.8,80.2,79.5,80,100), (80,80.5,79.9,80.3,100),
            (80.8,81.4,80.8,81.2,100), (81.2,82.1,81,82,180)]
    if kind == 'pullback':
        rows[-2:] = [(80.3,80.45,79.7,80.1,60), (80.1,81,79.95,80.8,180)]
    start = NOW.replace(minute=0, second=0)
    return [dict(zip(('open','high','low','close','volume'), row),
                 date=(start + timedelta(minutes=i*5)).isoformat()) for i,row in enumerate(rows)]


def stock(rows=None, price=82):
    rows = rows or bars()
    ends = [common.aware(r['date']) + timedelta(minutes=5) for r in rows]
    at = NOW.replace(minute=31, second=0)
    minute = dict(open=price,high=price,low=price,close=price,volume=100)
    return dict(previous=81,b5=(rows,ends),b15=([],[]),
                minutes={at:minute,at.replace(hour=12,minute=55):dict(minute,open=83,high=83,low=83,close=83)})


def request(symbol='1111', pattern='direct'):
    return dict(symbol=symbol,pattern=pattern,at=NOW.isoformat(),
        id=f'{DAY}:{symbol}:09:30:03:{pattern}',
        execution_at=common.execution_time(NOW).isoformat(),price=82,previous=81,
        vwap=80,confirming_high=82.1,confirming_close=82,relative_volume=1.8,
        vwap_distance_pct=2.5,legacy_rule_score=10,legacy_rule_eligible=False,
        legacy_radar_status='not_recorded')


def test_direct_does_not_require_a_near_vwap_pullback():
    patterns,reason = core.entry_patterns(bars(),NOW,81)
    assert reason is None and 'direct' in patterns
    assert 'pullback' not in patterns


def test_red_pullback_is_allowed_and_support_scales_with_past_volatility():
    rows=bars('pullback'); assert rows[-2]['close']<rows[-2]['open']
    patterns,reason=core.entry_patterns(rows,NOW,81)
    assert reason is None and 'pullback' in patterns
    assert patterns['pullback']['support_zone'] > float(common.tick_size(patterns['pullback']['vwap']))


@pytest.mark.parametrize('failure',['not_low_open','unfinished','stale','missing_open','weak_volume','missing_bar'])
def test_invalid_or_unavailable_causal_evidence_cannot_signal(failure):
    rows=bars(); now=NOW; previous=81
    if failure=='not_low_open': previous=78
    elif failure=='unfinished': now=NOW.replace(second=0)-timedelta(seconds=1)
    elif failure=='stale': now=NOW+timedelta(minutes=1)
    elif failure=='missing_open': rows=rows[1:]
    elif failure=='weak_volume': rows[-1]['volume']=1
    else: rows.pop(2)
    assert not core.entry_patterns(rows,now,previous)[0]


def test_future_and_prior_day_cannot_change_independent_patterns():
    rows=bars(); future=dict(rows[-1],date=(NOW+timedelta(minutes=5)).isoformat(),close=900)
    old=dict(rows[0],date=(NOW-timedelta(days=1)).isoformat(),close=1)
    assert core.entry_patterns([old]+rows+[future],NOW,81)==core.entry_patterns(rows,NOW,81)


def test_independent_selection_and_order_ignore_all_old_score_and_radar_fields():
    signal=request(); changed=dict(signal,legacy_rule_score=99,legacy_rule_eligible=True,
                                 legacy_radar_status='in_recorded_radar',legacy_radar_eligible=True)
    for arm in ('direct','union'):
        assert core.selected_for_arm(signal,arm) and core.selected_for_arm(changed,arm)
        assert core.priority(signal)==core.priority(changed)
    assert not core.selected_for_arm(signal,'union_score68_control')
    assert core.selected_for_arm(changed,'union_score68_control')


@pytest.mark.parametrize('error_type',[ValueError,RuntimeError])
def test_legacy_rule_failure_never_drops_an_independent_signal(error_type):
    radar=SimpleNamespace(evidence=lambda symbol,now:({'legacy_radar_status':'not_recorded'},{}))
    def broken(*args,**kwargs): raise error_type('unavailable_old_features')
    signals,quality=signals_for_day({'1111':stock()},DAY,core,common,core.Policy(),radar,broken)
    assert signals and signals[0]['legacy_rule_eligible'] is None
    assert quality['legacy_score_unavailable_kept_signal'] == 1


@pytest.mark.parametrize('arm',core.ARMS)
def test_one_symbol_one_fill_and_next_minute_execution(arm):
    signals=[request(),request(pattern='pullback')]
    if arm=='union_score68_control':
        signals=[dict(s,legacy_rule_eligible=True) for s in signals]
    result=simulate({'1111':stock()},signals,DAY,arm,1,'low-first',core,common,core.Policy())
    assert result['closed_count']==1 and not result['unresolved']
    trade=result['trades'][0]
    assert trade['signal_at']<trade['entry_at']<=trade['exit_at']
    assert trade['entry_at']==common.execution_time(NOW).isoformat()
    assert trade['shares']%1000==0 and result['buy_used']<=300000
    assert trade['reason']=='force_exit'
    assert sum(d['status']=='hypothetical_fill' for d in result['decisions'])==1
    assert trade['signal_id'] in {s['id'] for s in signals}


def test_score_control_is_a_matched_extra_gate_not_an_old_live_system_replay():
    data={'1111':stock()}; signal=request()
    independent=simulate(data,[signal],DAY,'union',1,'low-first',core,common,core.Policy())
    control=simulate(data,[signal],DAY,'union_score68_control',1,'low-first',core,common,core.Policy())
    assert independent['closed_count']==1 and control['closed_count']==0


@pytest.mark.parametrize('price,reason',[(79,'execution_lost_vwap'),(83,'execution_chase'),
                                       (0,'outside_user_price_limits'),(2001,'outside_user_price_limits')])
def test_execution_guards_survive_independent_entry(price,reason):
    assert core.execution_guard(request(),price,1)==reason


def test_cost_gate_and_same_risk_policy_survive():
    signal=dict(request(),price=12,previous=12,vwap=11.9,confirming_high=12)
    assert core.execution_guard(signal,12,1)=='insufficient_net_cost_room'
    policy=core.Policy(); book=common.Portfolio('allocation_only',1,policy)
    at=common.execution_time(NOW); book.open(request(),82,at)
    book.segment('1111',82,79,at+timedelta(seconds=15))
    assert book.trades[0]['reason']=='hard_stop'


def test_paid_price_chase_limit_is_decimal_exact_and_includes_adverse_ticks():
    signal=request()
    assert core.execution_guard(signal,82.1,1) is None
    assert core.execution_guard(signal,82.2,1)=='execution_chase'
    assert core.execution_guard(signal,82.1,2)=='execution_chase'
    assert core.true_range_context([dict(open=80,high=81,low=79,close=80)],60)==21


def test_no_quote_never_invents_a_force_exit_or_replenishes_budget():
    data={'1111':stock()}; data['1111']['minutes'].pop(NOW.replace(hour=12,minute=55,second=0))
    result=simulate(data,[request()],DAY,'union',1,'low-first',core,common,core.Policy())
    assert result['unresolved']==['1111'] and result['closed_count']==0
    assert result['buy_used']>0 and result['max_drawdown_twd']>0


def test_delayed_liquidation_is_explicit_and_uses_first_available_trade_minute():
    data={'1111':stock()}; at=NOW.replace(hour=12,minute=55,second=0)
    row=data['1111']['minutes'].pop(at); data['1111']['minutes'][at+timedelta(minutes=2)]=row
    result=simulate(data,[request()],DAY,'union',1,'high-first',core,common,core.Policy())
    assert result['closed_count']==1 and not result['unresolved']
    assert result['trades'][0]['exit_at']==(at+timedelta(minutes=2)).isoformat()
    assert result['skips']['delayed_liquidation_trading_minute']==1


def test_recording_missing_stale_future_and_nonmember_are_not_fabricated():
    radar=RecordedRadar(None,DAY,{})
    assert radar.evidence('1111',NOW)[0]['legacy_radar_status']=='not_loaded'
    radar.times=[NOW+timedelta(seconds=1)]; radar.frames=[(radar.times[0],{},set())]
    assert radar.evidence('1111',NOW)[0]['legacy_radar_status']=='not_loaded'
    radar.times=[NOW-timedelta(seconds=31)]; radar.frames=[(radar.times[0],{},set())]
    assert radar.evidence('1111',NOW)[0]['legacy_radar_status']=='stale_recorded_snapshot'
    radar.times=[NOW]; radar.frames=[(NOW,{},set())]
    assert radar.evidence('1111',NOW)[0]['legacy_radar_eligible'] is False


def test_streamed_recorded_radar_hash_and_past_snapshot_are_verified(tmp_path):
    folder=tmp_path/DAY;folder.mkdir()
    raw=gzip.compress(json.dumps(dict(kind='radar',data=dict(now=NOW.isoformat(),
         rows=[dict(symbol='1111',surge_60s=2,amount_60s=2000000)]))).encode()+b'\n')
    (folder/'events.gz').write_bytes(raw)
    manifest=folder/'events.manifest.json'
    meta=dict(file='events.gz',complete=True,written=1,dropped=0,errors=0,
              sha256=hashlib.sha256(raw).hexdigest())
    manifest.write_text(json.dumps(meta),encoding='utf-8')
    helpers={'qualifies_volume_surge':lambda row:True,'score_volume_surge':lambda row:1}
    radar=RecordedRadar(tmp_path,DAY,helpers)
    assert radar.evidence('1111',NOW)[0]['legacy_radar_eligible'] is True
    assert radar.evidence('1111',NOW-timedelta(seconds=1))[0]['legacy_radar_status']=='not_recorded'
    assert radar.sources[0]['original_sha256']==meta['sha256']
    meta['sha256']='bad';manifest.write_text(json.dumps(meta),encoding='utf-8')
    bad=RecordedRadar(tmp_path,DAY,helpers)
    assert not bad.frames and bad.quality['invalid_recording_not_used']==1


def test_loader_validates_full_session_and_excludes_missing_reference(tmp_path):
    root=tmp_path/DAY;root.mkdir(); start=NOW.replace(minute=0,second=0)
    rows=[dict(at=(start+timedelta(minutes=i)).isoformat(),open=80,high=81,low=79,close=80,volume=10) for i in range(270)]
    pack=dict(date=DAY,symbol='1111',previous_close=dict(date='2026-09-30',price=81),bars=rows)
    (root/'1111.json').write_text(json.dumps(pack),encoding='utf-8')
    helpers=SimpleNamespace(group_bars=group_bars)
    data,quality,sources=load_day(tmp_path,DAY,helpers)
    assert len(data)==1 and len(sources)==1 and not quality
    pack['previous_close']['date']=DAY
    (root/'1111.json').write_text(json.dumps(pack),encoding='utf-8')
    assert not load_day(tmp_path,DAY,helpers)[0]


def test_frozen_policy_and_no_live_wiring():
    with pytest.raises(FrozenInstanceError): core.Policy().max_roundtrip_pct=9
    with pytest.raises(ValueError): core.Policy(pullback_atr_fraction=0)
    with pytest.raises(ValueError): core.Policy(context_bars=1.5)
    for path in ('intraday_live.py','vm_runtime/intraday_live.py','paper_account.py'):
        assert 'a_independent_recovery_v3' not in Path(path).read_text(encoding='utf-8')
    tree=ast.parse(Path('daytrade_learning/a_independent_recovery_v3.py').read_text(encoding='utf-8'))
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(n in {'shioaji','firebase_admin','sqlite3','paper_account','position_manager'} for n in imports)


def test_cli_isolated_end_to_end_and_refuses_overwrite(tmp_path):
    root=tmp_path/'bars'/DAY; root.mkdir(parents=True)
    start=NOW.replace(minute=0,second=0)
    rows=[]
    for i in range(270):
        price=79+i*.01
        rows.append(dict(at=(start+timedelta(minutes=i)).isoformat(),open=price,
                         high=price+.03,low=price-.02,close=price+.02,volume=100))
    (root/'1111.json').write_text(json.dumps(dict(date=DAY,
        previous_close=dict(date='2026-09-30',price=81),bars=rows)),encoding='utf-8')
    output=tmp_path/'results'
    command=[sys.executable,'-X','utf8','deploy/backtest_a_independent_recovery_v3.py',
             '--bars',str(tmp_path/'bars'),'--output',str(output)]
    run=subprocess.run(command,check=True,text=True,capture_output=True)
    summary=json.loads((output/'summary.json').read_text(encoding='utf-8'))
    assert summary['days']==1 and len(summary['reports'])==16
    assert not summary['deployment_gate']['deployment_allowed']
    assert not summary['live_data_written']
    day=json.loads((output/(DAY+'.json')).read_text(encoding='utf-8'))
    assert day['signals'] and all(s['legacy_radar_status']=='not_loaded' for s in day['signals'])
    assert summary['days']==1
    for result in day['results']:
        assert len(result['decisions'])==len(day['signals'])
        assert result['buy_used']<=1000000
    assert subprocess.run(command,text=True,capture_output=True).returncode!=0


def test_two_tick_cost_ceiling_cannot_admit_a_whole_lot_under_current_allocation():
    from decimal import Decimal
    quotes=[]
    for start,step,count in [('1','.01',900),('10','.05',800),('50','.1',500),('100','.5',400)]:
        quotes.extend(float(Decimal(start)+i*Decimal(step)) for i in range(count))
    quotes=[p for p in quotes if common.shifted(p,1,2)*1000<=300000]
    assert min(common.screening_cost(p,2) for p in quotes)>core.Policy().max_roundtrip_pct
