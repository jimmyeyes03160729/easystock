"""Synthetic causal selection fixtures, not historical profit evidence."""
from datetime import datetime, timedelta, timezone
from market_data.a_candidates import candidate, snapshot
from strategy_engine import evaluate_daytrade
from daytrade_learning.research import promote_candidate

NOW=datetime(2026,10,13,10,0,tzinfo=timezone(timedelta(hours=8)))


def row(**changes):
    args=dict(symbol='TEST',stock={'name':'測試','previous_close':100,'daytrade_eligibility':'Yes'},
        result={'eligible':True,'daytrade_score':75,'vetoes':[],'reasons':['站上VWAP','量能放大']},
        price=101,now=NOW,quote_at=NOW,limits={'min_price':1,'max_price':2000,'max_gain_pct':8},
        market_pass=True,entry_window=True,mode='rules',
        model={'active':True,'evaluated':True,'approved':True,'accepted':False,
               'probability':.2592,'model_version':'test'})
    return candidate(**{**args,**changes})


def test_rule_candidate_is_visible_despite_low_ai_score_but_is_not_a_fill():
    value=row()
    assert value['state']=='rule_ready' and value['model_role']=='advisory'
    assert value['execution']=='not_filled' and value['model_score']==.2592
    assert row(mode='model')['state']=='watch'


def test_stale_unknown_and_vetoed_candidates_cannot_claim_ready():
    assert row(quote_at=NOW-timedelta(seconds=31)) is None
    assert row(quote_at=NOW+timedelta(seconds=1)) is None
    assert row(market_pass=False)['state']=='watch'
    assert row(stock={'previous_close':100,'daytrade_eligibility':None})['state']=='watch'
    assert row(result={'daytrade_score':75,'eligible':False,'vetoes':['跌破VWAP']})['state']=='watch'
    assert row(limits=None)['state']=='watch'
    assert row(price=2099)['state']=='watch'


def test_watchlist_has_at_most_five_current_candidates_and_never_claims_fills():
    rows={str(i):{**row(), 'symbol':str(i),'rule_score':60+i} for i in range(10)}
    value=snapshot(rows,NOW,100)
    assert len(value['rows'])==5 and not value['filled']
    assert value['rows'][0]['symbol']=='9'
    assert snapshot(rows,NOW+timedelta(seconds=31))['rows']==[]


def recovery_bars():
    bars=[]
    for i in range(15):
        base=98+i*.4
        bars.append({'date':(NOW.replace(hour=9,minute=0)+timedelta(minutes=5*i)).isoformat(),
                     'open':base,'high':base+.35,'low':base-.15,'close':base+.3,
                     'volume':1000 if i<12 else 2200})
    return bars


def test_completed_low_open_recovery_adds_an_explicit_pattern_without_removing_vetoes():
    bars=recovery_bars()
    result=evaluate_daytrade(bars,bars[-3:],stock={'previous_close':100,'buy_ratio_60s':.7},market_level='GREEN')
    assert result['opening_recovery']
    assert '開低站回VWAP、低點墊高後放量轉強' in result['daytrade_reasons']
    red=evaluate_daytrade(bars,bars[-3:],stock={'previous_close':100,'buy_ratio_60s':.7},market_level='RED')
    assert not red['eligible'] and '市場紅燈' in red['vetoes']
    fade=evaluate_daytrade(bars,bars[-3:],stock={'previous_close':100,'buy_ratio_60s':.7},market_regime='FADE')
    assert not fade['eligible']
    high_open=evaluate_daytrade(bars,bars[-3:],stock={'previous_close':97,'buy_ratio_60s':.7})
    assert not high_open['opening_recovery']
    mixed=[{**bars[0],'date':'2026-10-12T09:00:00+08:00'}]+bars[1:]
    assert not evaluate_daytrade(mixed,bars[-3:],stock={'previous_close':100,'buy_ratio_60s':.7})['opening_recovery']


def test_zero_selection_model_cannot_replace_the_previous_model(tmp_path):
    models=tmp_path/'models';models.mkdir()
    latest=models/'latest-approved.json';latest.write_text('{"version":"previous"}')
    before=latest.read_bytes()
    invalid={'status':'candidate_only','folds':[{'candidate':{'count':0,'mean_net_return_pct':None}}]}
    result=promote_candidate(tmp_path,invalid)
    assert result['status']=='blocked' and latest.read_bytes()==before
    assert not (models/'archive').exists()
    invalid['folds'][0]['candidate']={'count':30,'mean_net_return_pct':-.1}
    assert promote_candidate(tmp_path,invalid)['status']=='blocked'
