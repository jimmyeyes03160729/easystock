from datetime import datetime
import pytest
from runway_v2.lanes import LaneSuite

@pytest.mark.parametrize('lane,time',[('B1','09:03:00'),('B2','11:00:00'),('B3','09:20:00')])
def test_all_lanes_limit_rebound_to_one_small_long_and_keep_exits_active(tmp_path,lane,time):
    now=datetime.fromisoformat('2026-10-15T'+time+'+08:00')
    s=LaneSuite(tmp_path/'s.sqlite',sender=lambda *_:None,offline=True,active_lanes=(lane,))
    try:
        s.advance(now)
        s.market={'valid':True,'gate_action':'PASS','observed_at':now.timestamp(),
                  'rebound_mode':True,'entry_valid_until':now.timestamp()+3}
        s.rows={code:{'symbol':code,'observed_at':now.timestamp()} for code in ('2330','2317')}
        s._signal=lambda *args:({'direction':1,'entry_price':90,'stop_price':88,'target':92},None)
        s._book=lambda *args:{'bid':89.9,'ask':90,'bv':100,'av':100}
        s.advance(now)
        positions=s.state[lane]['positions']
        assert len(positions)==1 and next(iter(positions.values()))['shares']==1000
        assert next(iter(positions.values()))['market_entry_mode']=='REBOUND'
        s.market['gate_action']='BLOCK'
        s._book=lambda *args:{'bid':88,'ask':88.1,'bv':100,'av':100}
        s.advance(now)
        assert not s.state[lane]['positions'] and len(s.state[lane]['trades'])==1
    finally:s.worker.shutdown(wait=True)

def test_expired_rebound_permission_cannot_open_position(tmp_path):
    now=datetime.fromisoformat('2026-10-15T09:03:00+08:00')
    s=LaneSuite(tmp_path/'s.sqlite',sender=lambda *_:None,offline=True)
    try:
        s.advance(now);s.rows={'2330':{'observed_at':now.timestamp()}}
        s.market={'valid':True,'gate_action':'PASS','observed_at':now.timestamp(),'entry_valid_until':now.timestamp()-1}
        s._signal=lambda *args:pytest.fail('Expired permission must be rejected before strategy evaluation')
        s.advance(now);assert not s.state['B1']['positions']
    finally:s.worker.shutdown(wait=True)
