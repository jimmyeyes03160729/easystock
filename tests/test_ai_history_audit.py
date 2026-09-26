"""Audit output must omit secrets and distinguish log matches from fills."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('audit',Path(__file__).resolve().parents[1]/'deploy/audit_ai_history.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_only_allowlisted_environment(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'env';p.write_text('SJ_SECRET_KEY=never-print\nLIVE_ENTRY_MODE=rules\n')
            self.assertEqual(audit.env_values(p),{'LIVE_ENTRY_MODE':'rules'})

    def test_weights_not_in_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'model.json';p.write_text(json.dumps({'model_version':'old','coef':[123],
                'approved':False,'training':{'trained_through':'2026-09-10'},'api_key':'never-print'}))
            result=audit.model_metadata(p)
            self.assertNotIn('never-print',json.dumps(result))
            self.assertNotIn('coef',result['metadata'])
            self.assertEqual(result['metadata']['training.trained_through'],'2026-09-10')

    def test_raw_exception_message_not_exposed(self):
        raw=json.dumps({'__REALTIME_TIMESTAMP':'1789574400000000',
                        'MESSAGE':'RuntimeError: token=never-print [MODEL] paper-adaptive-2026-09-10-old'})
        with patch.object(audit,'command',return_value=(0,raw)):
            result=audit.log_summary('fixture','2026-09-10')
        self.assertNotIn('never-print',json.dumps(result))
        self.assertEqual(sum(r['RuntimeError'] for r in result['by_day'].values()),1)


if __name__=='__main__':unittest.main()
