import ast,copy,unittest
from pathlib import Path
source=Path(__file__).with_name('firebase_store.py').read_text(encoding='utf-8')
tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FirebaseStore')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='update_position')
module=ast.Module(body=[ast.ClassDef(name='Store',bases=[],keywords=[],body=[method],decorator_list=[])],type_ignores=[])
ns={'safe_value':lambda v:v}; exec(compile(ast.fix_missing_locations(module),'<store>','exec'),ns)
class Ref:
 def __init__(self,value,retry=None): self.value=copy.deepcopy(value); self.retry=retry
 def child(self,key): return self
 def transaction(self,fn):
  if self.retry is not None: fn(copy.deepcopy(self.value)); self.value=copy.deepcopy(self.retry)
  self.value=fn(copy.deepcopy(self.value))
class Tests(unittest.TestCase):
 def setUp(self): self.p={'symbol':'2327','trade_id':'id1','entry_time':'2026-09-22T09:57:16+08:00','current_price':570,'status':'OPEN'}
 def run_update(self,current,retry=None):
  store=ns['Store'](); store.live=Ref(current,retry); store.update_position(self.p); return store.live.value
 def test_skipped_buy_does_not_create_open(self): self.assertIsNone(self.run_update(None))
 def test_existing_open_keeps_identity_and_shares(self):
  current={**self.p,'shares':1000,'current_price':560}; result=self.run_update(current)
  self.assertEqual(result['current_price'],570); self.assertEqual(result['shares'],1000); self.assertEqual(result['trade_id'],'id1')
 def test_closed_trade_not_reopened(self):
  current={**self.p,'status':'CLOSED'}; self.assertEqual(self.run_update(current),current)
 def test_other_trade_not_overwritten(self):
  current={**self.p,'trade_id':'id2'}; self.assertEqual(self.run_update(current),current)
 def test_other_entry_time_not_overwritten(self):
  current={**self.p,'entry_time':'2026-09-23T09:57:16+08:00'}; self.assertEqual(self.run_update(current),current)
 def test_incomplete_ghost_not_updated(self):
  current={'status':'OPEN','current_price':560}; self.assertEqual(self.run_update(current),current)
 def test_transaction_retry_preserves_new_trade(self):
  current={**self.p,'current_price':560}; new={**current,'trade_id':'id2'}; self.assertEqual(self.run_update(current,new),new)
 def test_missing_identity_rejected(self):
  self.p.pop('trade_id')
  with self.assertRaises(ValueError):self.run_update(None)
if __name__=='__main__':unittest.main()
