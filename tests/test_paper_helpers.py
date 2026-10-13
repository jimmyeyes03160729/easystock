import pytest
import paper_helpers as F
from llm_paper import run as L

def test_ai_imports_neutral_helpers_and_holiday_dates():
    assert L.F is F and L.R is F.R
    assert F.add_sessions(['2026-10-08'],'2026-10-09',2,{'2026-10-09'}.__contains__)=='2026-10-13'
    assert F.next_session(['2026-10-08'],'2026-10-08',{'2026-10-09'}.__contains__)=='2026-10-12'

def test_ai_price_returns_limit_up_ex_rights_and_json(tmp_path):
    bars={'2330':{'2026-10-12':{'open':50,'close':50,'reference':50},'2026-10-13':{'open':48,'close':48,'reference':48}},
          '2317':{'2026-10-12':{'open':55,'close':55,'reference':50}}}
    returns,unfilled=F.position_returns(['2330','2317'],bars,{'2330':[('2026-10-13',50/48)]},'2026-10-12','2026-10-13')
    assert unfilled==['2317']
    assert returns['2330']['net_pct']==pytest.approx(-F.R.cost_pct(50,48,same_day=False))
    p=tmp_path/'result.json';F.write_json(p,{'name':'台積電'});assert '台積電' in p.read_text(encoding='utf-8')
