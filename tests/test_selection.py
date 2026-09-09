"""Regression checks for invalid picks, freshness, shared rules, and overnight bars."""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_parsers  # Existing offline Firebase stub, when SDK is not installed.
import strategy_rules as rules
import scan_intraday as scan
m = test_parsers.m


def good_stock():
    row = {'symbol':'TEST','category':'半導體','updated_at':'2026-09-09',
           'price':105,'open':102,'sma20':100,'sma60':95,'near_high_ratio':.95,
           'sharpe20':1.5,'volume_ratio':1.5,'recent_min_low_3':99,'momo20':1.1,
           'range_position':.85,'amount':100_000_000,'kline_count':250,
           'roe':20,'eps':5,'fcf':100,'debt_ratio':20,'pe':10,'yield_pct':6,
           'dividend_continuity_years':5}
    row['field_meta'] = {k:{'as_of':'2026-09-09'} for k in ['roe','eps','fcf','debt_ratio','pe','yield_pct','dividend_continuity_years']}
    return row


def test_missing_is_not_qualified():
    row=good_stock(); row['fcf']=None
    d=rules.stock_decisions(row,'2026-09-09')['strategies']
    assert d['SWING']['eligible'] and d['REBOUND']['eligible']
    assert not d['LONG']['eligible']
    assert not rules.long_decision({'price':50,'yield_pct':8},'2026-09-09')['eligible']


def test_weak_trend_and_overshoot():
    row=good_stock(); row.update(sma20=110,sma60=120,sharpe20=-1)
    d=rules.stock_decisions(row,'2026-09-09')['strategies']
    assert not d['SWING']['eligible'] and not d['REBOUND']['eligible']
    row=good_stock(); row['price']=120
    assert not rules.stock_decisions(row,'2026-09-09')['strategies']['SWING']['eligible']


def test_strict_long_and_financial_sector():
    row=good_stock(); assert rules.long_decision(row,'2026-09-09')['eligible']
    for key, value in [('pe',-2),('eps',0),('fcf',0),('dividend_continuity_years',1),('category','金融保險')]:
        bad=dict(row); bad[key]=value
        assert not rules.long_decision(bad,'2026-09-09')['eligible'],key


def test_low_liquidity_short_history_mixed_date():
    for key,value in [('amount',1000),('kline_count',30),('updated_at','2026-09-08')]:
        row=good_stock();row[key]=value
        assert not any(x['eligible'] for x in rules.stock_decisions(row,'2026-09-09')['strategies'].values())
    row=good_stock();row['kline_count']=249
    assert not rules.stock_decisions(row,'2026-09-09')['strategies']['SWING']['eligible']


def test_shared_historical_rules():
    f={'close':105,'open':102,'ma20':100,'ma60':95,'near_high':.95,'sharpe':1.5,
       'vol_ratio':1.5,'recent_min_low':99,'momo20':1.1,'range_position':.85}
    for strategy in ['swing','rebound']:
        a=rules.technical_decision(strategy,f)
        assert m.strategy_signal_and_score(strategy,f)==(a['eligible'],a['score'])
        bad={**f,'vol_ratio':None}
        assert not m.strategy_signal_and_score(strategy,bad)[0]


def test_fallback_date_does_not_slide():
    row={'fcf':123,'updated_at':'2026-01-01','field_meta':{'fcf':{'as_of':'2026-01-01'}}}
    for i in range(1,121):
        day=(date(2026,1,1)+timedelta(days=i)).isoformat()
        value,_=m.choose_metric(None,row,'fcf',day);assert value==123
        row['updated_at']=day
    assert m.previous_metric(row,'fcf','2026-05-02') is None
    assert m.previous_metric({'fcf':123,'updated_at':'2026-09-09'},'fcf','2026-09-09') is None


def test_no_fictional_portfolio_metrics():
    rows=[{'symbol':'A','exit_date':'2026-09-09','net_return':.05,'gross_return':.06},
          {'symbol':'B','exit_date':'2026-09-09','net_return':-.02,'gross_return':-.01}]
    stats=m._base_trade_stats(rows,10)
    assert stats['max_drawdown'] is None and stats['sharpe'] is None
    assert stats['avg_return']==1.5


def bar(t,close=100):
    return {'date':t.isoformat(),'open':99,'high':101,'low':98,'close':close,'volume':1000}


def test_candle_freshness_and_partial_exclusion():
    now=datetime(2026,9,9,13,6,tzinfo=scan.TPE)
    rows=[bar(now.replace(hour=12,minute=55)),bar(now.replace(minute=0)),bar(now.replace(minute=5)),bar(now-timedelta(days=1))]
    clean=scan.completed_today_bars(rows,now)
    assert len(clean)==2 and scan.candle_time(clean[-1]['date']).minute==0
    assert scan.completed_today_bars([bar(now-timedelta(hours=1))],now)==[]


def test_clock_aligned_15m():
    t=datetime(2026,9,9,12,0,tzinfo=scan.TPE)
    rows=[bar(t+timedelta(minutes=i)) for i in [0,5,10,20,25,30]]
    out=scan.aggregate_15m(rows)
    assert len(out)==1 and scan.candle_time(out[0]['date']).minute==0


def test_hard_vwap_veto():
    row={'overnight_score':90,'overnight_reasons':['a','b'],'vetoes':['距VWAP過遠']}
    assert not scan.eligible_overnight(row)
    row['vetoes']=[];assert scan.eligible_overnight(row)


def test_proxy_units_and_no_ranking_effect():
    a=scan.historical_edge_score({'backtest':{'daytrade_proxy':{'signals':30,'profit_factor':1.2,'avg_return':.02}}})
    b=scan.historical_edge_score({'backtest':{'daytrade_proxy':{'signals':30,'profit_factor':1.2,'avg_return':.5}}})
    assert a<b
    t=datetime(2026,9,9,9,0,tzinfo=scan.TPE)
    rows=[bar(t+timedelta(minutes=5*i),100+i*.05) for i in range(48)]
    stock=good_stock()
    a=scan.overnight_features(rows,scan.aggregate_15m(rows),stock,'YELLOW')['overnight_score']
    stock['backtest']={'daytrade_proxy':{'signals':1000,'profit_factor':10,'avg_return':5}}
    b=scan.overnight_features(rows,scan.aggregate_15m(rows),stock,'YELLOW')['overnight_score']
    assert a==b and 0<=a<=100


def test_finite_numbers_only():
    for v in ['',True,False,float('inf'),float('nan'),'unknown']:
        assert rules.number(v) is None


# Callable by the release validation command; all external I/O replaced in-process.
def test_publication_without_external_writes():
    import copy
    from unittest.mock import patch
    data={'summary':{},'kline':{},'history':{},'meta':{},'intraday_live':{'keep':'unchanged'}}
    operations=[]
    class Ref:
        def __init__(self,path=()):self.path=path
        def child(self,k):return Ref(self.path+(str(k),))
        def get(self,shallow=False):
            value=data
            for k in self.path:value=value.get(k,{}) if isinstance(value,dict) else {}
            return {k:True for k in value} if shallow else copy.deepcopy(value)
        def set(self,value):
            target=data
            for k in self.path[:-1]:target=target.setdefault(k,{})
            target[self.path[-1]]=copy.deepcopy(value);operations.append(self.path)
        def update(self,values):
            target=data
            for k in self.path:target=target.setdefault(k,{})
            for k,v in values.items():
                if v is None:target.pop(k,None)
                else:target[k]=copy.deepcopy(v)
            operations.append(self.path)
        def delete(self):
            target=data
            for k in self.path[:-1]:target=target.get(k,{})
            target.pop(self.path[-1],None)
    q={'symbol':'1111','name':'test','date':'2026-09-09','close':100,'open':99,'high':101,'low':98,'amount':100_000_000,'volume':1_000_000,'exchange':'TWSE'}
    q2={**q,'symbol':'2222','exchange':'TPEx'}
    with patch.object(m,'validate_environment'),patch.object(m,'init_firebase',return_value=Ref()),patch.object(m,'fetch_many',return_value={}),patch.object(m,'parse_twse_quotes',return_value={'1111':q}),patch.object(m,'parse_tpex_quotes',return_value={'2222':q2}),patch.object(m,'FUGLE_API_KEY',''):
        m.main()
    active=data['active_release'];rel=data['releases'][active]
    assert rel['meta']['release_id']==active
    assert all(x['release_id']==active for x in rel['summary'].values())
    assert data['intraday_live']=={'keep':'unchanged'}
    assert operations.index(('active_release',)) > operations.index(('releases',active,'meta'))
    assert data['meta']['rule_version']==rules.RULE_VERSION
    assert data['selection_history']['2026-09-09']['stocks']
    print('PASS atomic publication dry-run; no external writes')


if __name__=='__main__':
    tests=[v for k,v in globals().copy().items() if k.startswith('test_') and callable(v)]
    for test in tests:
        test();print('PASS',test.__name__)
    print(f'{len(tests)} selection regression tests passed')

