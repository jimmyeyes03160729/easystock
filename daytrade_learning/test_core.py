import copy
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from core import Store, gate, report, train


def event():
    return {'symbol':'TEST','observed_at':'2026-09-01T09:20:00+08:00',
        'quote_at':'2026-09-01T09:20:00+08:00','features_as_of':'2026-09-01T09:20:00+08:00',
        'price':107,'previous_close':100,'baseline_selected':True,'policy_version':'test-v1',
        'universe_version':'test-v1','settings':{'min_price':10,'max_price':150,'max_gain_pct':7},
        'features':{'gain_pct':7,'return_5m_pct':1,'volume_ratio':2,'vwap_distance_pct':1,'market_gain_pct':.5}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(str(Path(self.temp.name)/'test.sqlite'))
    def tearDown(self):
        self.store.db.close(); self.temp.cleanup()
    def test_gain_and_freshness(self):
        e=event(); self.assertTrue(gate(e,e['settings'])[0])
        e['price']=107.01; self.assertFalse(gate(e,e['settings'])[0])
        e=event(); e['quote_at']='2026-09-01T09:18:00+08:00'
        self.assertFalse(gate(e,e['settings'])[0])
    def test_future_and_conflicting_capture(self):
        e=event(); key=self.store.capture(e); self.assertEqual(key,self.store.capture(e))
        e['baseline_selected']=False
        with self.assertRaises(ValueError): self.store.capture(e)
        e=event(); e['features_as_of']='2026-09-01T09:21:00+08:00'
        with self.assertRaises(ValueError): self.store.capture(e)
    def test_missing_costs_and_outcome(self):
        key=self.store.capture(event())
        self.assertEqual(report(self.store,'2026-09-01')['missing_outcomes'],1)
        r={'id':key,'kind':'simulation','execution_policy':'next_quote_v1',
           'entry_at':'2026-09-01T09:20:02+08:00','exit_at':'2026-09-01T10:20:00+08:00',
           'entry_price':107,'exit_price':108,'shares':1000,'cost_twd':500}
        self.store.outcome(r)
        self.assertAlmostEqual(report(self.store,'2026-09-01')['simulation']['mean_net_return_pct'],500/107000*100)
        r['cost_twd']=0
        with self.assertRaises(ValueError): self.store.outcome(r)
    def test_sparse_data_blocks_model(self):
        self.assertEqual(train(self.store)['status'],'blocked')
    def test_bar_gaps_do_not_invent_surges(self):
        t=datetime.fromisoformat('2026-09-01T09:01:00+08:00')
        for i in [0,1,2,4,5]:
            at=(t+timedelta(minutes=i)).isoformat()
            self.store.bar({'symbol':'TEST','at':at,'available_at':at,'open':100+i,'high':100+i,'low':100+i,'close':100+i,'volume':100})
        self.assertEqual(report(self.store,'2026-09-01')['surges']['count'],0)
    def test_model_dates_and_no_promotion(self):
        start=datetime.fromisoformat('2026-01-01T09:20:00+08:00')
        for day in range(81):
            for j in range(8):
                e=event(); t=start+timedelta(days=day,minutes=j)
                e.update(observed_at=t.isoformat(),quote_at=t.isoformat(),features_as_of=t.isoformat(),symbol=str(j))
                e['features']['volume_ratio']=j+1
                key=self.store.capture(e)
                self.store.outcome({'id':key,'kind':'simulation','execution_policy':'test-v1',
                    'entry_at':(t+timedelta(seconds=2)).isoformat(),'exit_at':(t+timedelta(minutes=20)).isoformat(),
                    'entry_price':107,'exit_price':108 if j%2 else 106,'shares':1000,'cost_twd':100})
        result=train(self.store)
        self.assertEqual(result['status'],'candidate_only')
        self.assertLess(result['train_through'],result['gap_date'])
        self.assertLess(result['gap_date'],result['test_from'])
        self.assertFalse(result['deployment_allowed'])
        self.assertEqual(result['test_samples'],160)

if __name__=='__main__': unittest.main()
