import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from easystock_admin.store import Store, Conflict
from easystock_admin import conversations as c

GROUP={'type':'group','groupId':'C'+'1'*32}
USER={'type':'user','userId':'U'+'2'*32}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'state.db',{'min_price':1,'max_price':100,'max_gain_pct':5})
    def tearDown(self):self.temp.cleanup()
    def approve(self):
        key=c.observe(self.store,GROUP)
        with self.store.tx() as db:db.execute('UPDATE line_conversations SET archived=0 WHERE id=?',(key,))
        return key
    def test_default_free_replies_and_registered_trade_only(self):
        self.assertFalse(c.allowed(self.store,GROUP))
        self.assertFalse(c.allowed(self.store,GROUP,'trade'))
        key=self.approve()
        self.assertFalse(c.allowed(self.store,GROUP,'trade'))
        c.update_conversation(self.store,key,{'replies':True,'push':True,'label':'Group','version':1})
        self.assertTrue(c.allowed(self.store,GROUP,'trade'))
        self.assertFalse(c.allowed(self.store,GROUP,'other'))
    def test_group_personal_independent(self):
        c.update(self.store,{'values':{**c.DEFAULTS,'groups':False},'version':1})
        self.assertFalse(c.allowed(self.store,GROUP))
        self.assertFalse(c.allowed(self.store,USER))
        with self.assertRaises(Conflict):c.update(self.store,{'values':c.DEFAULTS,'version':1})
    def test_individual_persists_and_masks_identifiers(self):
        key=self.approve()
        c.update_conversation(self.store,key,{'replies':False,'push':False,'label':'Test','version':1})
        c.observe(self.store,GROUP)
        self.assertFalse(c.allowed(self.store,GROUP))
        self.assertFalse(c.allowed(self.store,GROUP,'trade'))
        self.assertNotIn(GROUP['groupId'],str(c.state(self.store)))
    def test_policy_failure_sends_nothing(self):
        from line_policy import push_allowed
        with patch('easystock_admin.store.Store',side_effect=RuntimeError):
            self.assertFalse(push_allowed(GROUP['groupId'],'trade'))
    def test_strict_types(self):
        with self.assertRaises(ValueError):c.update(self.store,{'values':{**c.DEFAULTS,'replies':'false'},'version':1})
        self.assertIsNone(c.observe(self.store,{'type':'user','userId':'bad'}))
    def test_archived_cannot_be_revived_by_webhook_or_legacy_api(self):
        key=c.observe(self.store,GROUP)
        c.observe(self.store,GROUP)
        self.assertEqual(c.state(self.store)['conversations'],[])
        self.assertFalse(c.allowed(self.store,GROUP))
        with self.assertRaises(Conflict):c.update_conversation(self.store,key,{'replies':True,'push':True,'label':'Revive','version':1})
    def test_personal_and_other_push_cannot_be_reenabled(self):
        self.assertIsNone(c.observe(self.store,USER))
        for field in ('users','other_push'):
            with self.assertRaises(ValueError):c.update(self.store,{'values':{**c.DEFAULTS,field:True},'version':1})

if __name__=='__main__':unittest.main()
