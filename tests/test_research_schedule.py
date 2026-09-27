import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from learning_cycle import collection_ready


class ResearchScheduleTest(unittest.TestCase):
    def test_only_complete_same_day_collection_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            reports = Path(folder) / 'reports'
            reports.mkdir()
            path = reports / '2026-09-24.json'
            self.assertFalse(collection_ready(folder, '2026-09-24'))
            report = {'date':'2026-09-24','status':'ready',
                      'collection':{'status':'complete','downloaded':10,'failed':{},'scanner_errors':[]}}
            path.write_text(json.dumps(report))
            self.assertTrue(collection_ready(folder, '2026-09-24'))
            report['collection']['failed']={'2330':'Timeout'}
            path.write_text(json.dumps(report))
            self.assertFalse(collection_ready(folder, '2026-09-24'))
            report['collection']['failed']={}
            report['date']='2026-09-23'
            path.write_text(json.dumps(report))
            self.assertFalse(collection_ready(folder, '2026-09-24'))


if __name__ == '__main__':
    unittest.main()
