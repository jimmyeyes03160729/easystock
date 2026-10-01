"""History health must distinguish a saved checkpoint from a running worker."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

from easystock_admin.health import _history_collection_state

ROOT = Path(__file__).resolve().parents[1]


class HistoryResumeTests(unittest.TestCase):
    def test_saved_limit_is_waiting_with_next_schedule(self):
        workers={'available':True,'history_download':'inactive','history_download_timer':'active',
                 'history_download_next':'Thu 2026-10-01 14:15:00 CST'}
        state,detail=_history_collection_state({'stop_reason':'pair_limit'},workers)
        self.assertEqual(state,'idle')
        self.assertIn('14:15:00',detail)

    def test_unavailable_disabled_failed_and_running_workers(self):
        cases=[({'available':False},'idle'),
               ({'available':True,'history_download':'inactive','history_download_timer':'inactive'},'warning'),
               ({'available':True,'history_download':'failed','history_download_timer':'active'},'error'),
               ({'available':True,'history_download':'active'},'ok')]
        for reason in ('pair_limit','pair_limit_or_plan_complete','downloading'):
            for workers,expected in cases:
                with self.subTest(reason=reason,workers=workers):
                    self.assertEqual(_history_collection_state({'stop_reason':reason},workers)[0],expected)

    def test_safety_stops_are_not_reported_normal(self):
        for reason in ('quota_exhausted','quota_reserve','disk_reserve','transient_error','user_stopped'):
            with self.subTest(reason=reason):
                self.assertEqual(_history_collection_state({'stop_reason':reason},{'available':True})[0],'warning')
        self.assertEqual(_history_collection_state({'stop_reason':'credentials_missing'},{})[0],'error')

    def test_timer_install_preserves_paused_schedule_and_does_not_stop_workers(self):
        script=(ROOT/'deploy/install_history_schedule.sh').read_text()
        self.assertIn('bash deploy/install_history_schedule.sh',(ROOT/'deploy/update_vm_main.sh').read_text())
        stubs='''
systemctl() {
  printf 'systemctl %s\\n' "$*" >> "$TEST_ACTION_LOG"
  if [[ "$1" == is-active ]]; then [[ "$TEST_TIMER_ACTIVE" == 1 ]]; else return 0; fi
}
sudo() { printf 'sudo %s\\n' "$*" >> "$TEST_ACTION_LOG"; }
'''
        for active in (0,1):
            with self.subTest(active=active),tempfile.TemporaryDirectory() as folder:
                code=Path(folder)/'code';code.mkdir()
                log=Path(folder)/'actions'
                adapted=script.replace('/home/ubuntu/easystock-maintenance',folder+'/backups')
                adapted=adapted.replace('/home/ubuntu/easystock',str(code))
                subprocess.run(['bash'],input=stubs+adapted,text=True,capture_output=True,check=True,
                               env={**os.environ,'TEST_ACTION_LOG':str(log),'TEST_TIMER_ACTIVE':str(active)})
                actions=log.read_text()
                self.assertEqual('sudo systemctl restart easystock-history-download.timer' in actions,bool(active))
                self.assertIn('sudo systemctl daemon-reload',actions)
                self.assertNotIn('enable',actions)
                self.assertNotIn('stop ',actions)
                self.assertNotIn('.service',actions)

    @unittest.skipUnless(shutil.which('systemd-analyze'),'requires systemd calendar parser')
    def test_timer_continues_on_same_afternoon(self):
        text=(ROOT/'deploy/easystock-history-download.timer').read_text()
        calendar=next(line.split('=',1)[1] for line in text.splitlines() if line.startswith('OnCalendar='))
        result=subprocess.run(['systemd-analyze','calendar','--base-time=2026-10-01 06:01:50 UTC',
                               '--iterations=3',calendar],capture_output=True,text=True,check=True,
                              env={'PATH':'/usr/bin:/bin','TZ':'UTC','LC_ALL':'C'})
        for stamp in ('06:15:00 UTC','06:30:00 UTC','06:45:00 UTC'):
            self.assertIn(stamp,result.stdout)


if __name__=='__main__':
    unittest.main()
