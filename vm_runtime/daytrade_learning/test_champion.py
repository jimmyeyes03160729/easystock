import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from daytrade_learning.features import FEATURES
from daytrade_learning.champion import run_close,shadow

PROFILE='profile-a'
def row(day,return_pct=1,radar=True):return {'date':day,'at':day+'T10:00:00+08:00','profile':PROFILE,'features':[0.1]*len(FEATURES),'net_return_pct':return_pct,'radar_selected':radar}
def model(day):return {'status':'candidate_only','version':'m-'+day,'trained_through':day,'profile':PROFILE,'threshold':.5,'features':FEATURES,'mean':[0]*len(FEATURES),'scale':[1]*len(FEATURES),'coef':[0]*len(FEATURES),'intercept':0,'validation_mode':'full_walk_forward','folds':[{'test_samples':40,'candidate':{'count':10,'mean_net_return_pct':1},'radar_benchmark':{'count':10,'mean_net_return_pct':.5},'brier':.1,'constant_brier':.2} for _ in range(3)]}

class Champion(unittest.TestCase):
 def setup(self,dates,latest=None):
  temp=tempfile.TemporaryDirectory();data=Path(temp.name);(data/'labels').mkdir();(data/'models').mkdir()
  for d in dates:(data/'labels'/(d+'.json')).write_text(json.dumps([row(d)]))
  if latest:(data/'models/latest-approved.json').write_text(json.dumps(latest))
  return temp,data
 def controls(self,days=2):return {'model_retrain_every_days':days,'forward_observe_days':20,'formal_candidate_for_live':False}
 def test_frozen_is_exclusive_and_old_latest_is_archived(self):
  temp,data=self.setup(['2026-09-25','2026-09-26'],model('2026-09-25'));frozen={**model('2026-09-20'),'status':'frozen_baseline'};(data/'models/frozen-baseline.json').write_text(json.dumps(frozen))
  with temp,patch('daytrade_learning.champion.train_candidate',return_value=model('2026-09-26')):
   result=run_close(data,'2026-09-26',self.controls(1));self.assertEqual(result['action'],'promoted');self.assertEqual(json.loads((data/'models/frozen-baseline.json').read_text())['version'],frozen['version']);self.assertTrue(list((data/'models/archive').glob('approved-2026-09-25.json')))
 def test_not_due_then_due_and_shadow_precedes_training(self):
  temp,data=self.setup(['2026-09-24','2026-09-25','2026-09-26'],model('2026-09-24'));order=[]
  with temp,patch('daytrade_learning.champion.shadow',side_effect=lambda *a,**k:order.append('shadow') or {'lines':{}}),patch('daytrade_learning.champion.train_candidate',side_effect=lambda *a,**k:order.append('train') or model('2026-09-26')) as train:
   first=run_close(data,'2026-09-25',self.controls(2));self.assertEqual(first['action'],'skipped_not_due');train.assert_not_called()
   # A separate close date reaches two labeled dates after the old model.
   second=run_close(data,'2026-09-26',self.controls(2));self.assertEqual(second['action'],'promoted');self.assertEqual(order[-2:],['shadow','train'])
 def test_same_day_is_idempotent(self):
  temp,data=self.setup(['2026-09-26'],None)
  with temp,patch('daytrade_learning.champion.train_candidate',return_value=model('2026-09-26')) as train:
   run_close(data,'2026-09-26',self.controls(1));again=run_close(data,'2026-09-26',self.controls(1));self.assertEqual(again['status'],'already_processed');self.assertEqual(train.call_count,1);self.assertEqual(len((data/'models/promotion-log.jsonl').read_text().splitlines()),1)
 def test_profile_mismatch_warns(self):
  temp,data=self.setup(['2026-09-26']);(data/'models/frozen-baseline.json').write_text(json.dumps({**model('2026-09-20'),'profile':'old'}))
  with temp:
   result=shadow(data,'2026-09-26',PROFILE,[row('2026-09-26')]);self.assertIn({'type':'profile_mismatch','line':'frozen_baseline'},result['warnings'])
 def test_shadow_failure_does_not_block_training(self):
  temp,data=self.setup(['2026-09-26'])
  with temp,patch('daytrade_learning.champion.shadow',side_effect=OSError('fail')),patch('daytrade_learning.champion.train_candidate',return_value=model('2026-09-26')):
   result=run_close(data,'2026-09-26',self.controls(1));self.assertEqual(result['action'],'promoted');self.assertEqual(result['errors'][0]['stage'],'shadow')
 def test_bootstrap_candidate_cannot_replace_rolling_model(self):
  temp,data=self.setup(['2026-09-26'],model('2026-09-25'));candidate=model('2026-09-26');candidate['validation_mode']='paper_bootstrap_time_split'
  with temp,patch('daytrade_learning.champion.train_candidate',return_value=candidate):
   result=run_close(data,'2026-09-26',self.controls(1));self.assertEqual(result['action'],'blocked');self.assertEqual(result['reason'],'promotion_gate_not_met')

if __name__=='__main__':unittest.main()
