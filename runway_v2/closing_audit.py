"""Offline audit of the two forward B1 arms; never promotes strategy settings."""
import json
from datetime import datetime
from pathlib import Path
from .closing_pool import TRIAL,load,write
from .lanes import TPE
from .replay import load_day,replay_events,live_state,normalized,trade_metrics

def audit(root,day):
    root=Path(root);pool=load(root,day);control_path=root/'controls'/(day+'.json')
    control=json.loads(control_path.read_text(encoding='utf-8')) if control_path.exists() else None
    result={'trial':TRIAL,'day':day,'mode':'independent_shadow_paper','pool':pool,'control':control,
            'updated_at':datetime.now(TPE).isoformat(),'arms':{},'status':'EXCLUDED','reasons':[]}
    if pool.get('status')!='READY':result['reasons'].append('缺少完整有效的前日尾盤凍結名單')
    if not control or len(control.get('symbols',[]))!=len(pool.get('symbols',[])):
        result['reasons'].append('對照名單未凍結或两組數目不同')
    if not result['reasons']:
        for name in ('control','closing'):
            events,profile,errors=load_day(root/(name+'-recordings')/day)
            reasons=profile.get('eligibility',{}).get('B1',{}).get('reasons',['缺完整錄製'])
            symbols=set(control['symbols'] if name=='control' else pool['symbols'])
            seen={'tick':set(),'bidask':set()}
            if not reasons:
                for event in events:
                    if event['kind'] in seen:seen[event['kind']].add(event['data']['symbol'])
                if any(symbols-seen[k] for k in seen):reasons=reasons+['名單存在沒有實際逐筆或五檔的股票']
            arm={'input_profile':profile,'reasons':reasons,'status':'EXCLUDED'}
            if not reasons:
                baseline=replay_events(events);actual=live_state(root/(name+'.sqlite'),day)
                if baseline['mismatched_clocks'] or actual is None or normalized(actual)!=normalized(baseline['state']):
                    arm['reasons']=['離線逐次重播與當時模擬結果不一致']
                elif baseline['state']['B1']['positions']:
                    arm['reasons']=['尚有待報價平倉持倉']
                else:
                    arm['status']='OBSERVED_FORWARD_PAPER'
                    arm['baseline']=trade_metrics(baseline['state']['B1']['trades'])
                    arm['extra_one_tick_each_side']=trade_metrics(baseline['state']['B1']['trades'],extra_ticks=1)
                    arm['delay_500ms']=trade_metrics(replay_events(events,500)['state']['B1']['trades'])
                    arm['delay_1500ms']=trade_metrics(replay_events(events,1500)['state']['B1']['trades'])
            result['arms'][name]=arm
        if all(a['status']=='OBSERVED_FORWARD_PAPER' for a in result['arms'].values()):
            result['status']='OBSERVED_FORWARD_PAPER';result['net_pnl_difference']=result['arms']['closing']['baseline']['net_pnl']-result['arms']['control']['baseline']['net_pnl']
        else:result['reasons'].append('至少一組來源或重播核對不合格，不比較輸贏')
    write(root/'audits'/(day+'.json'),result);write(root/'audit-latest.json',result)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',default='/home/ubuntu/easystock-b1-closing');p.add_argument('--day');a=p.parse_args()
    result=audit(a.root,a.day or datetime.now(TPE).date().isoformat())
    print(json.dumps({'day':result['day'],'status':result['status'],'reasons':result['reasons']},ensure_ascii=False))
