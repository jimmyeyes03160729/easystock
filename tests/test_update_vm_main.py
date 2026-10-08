"""Run deploy/update_vm_main.sh against a throwaway repo with stubbed system commands."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which('bash')
GIT_ENV = dict(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')


def write(path, text, mode=0o755):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    path.chmod(mode)


@unittest.skipUnless(BASH, 'bash is required')
class UpdateVmMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = dict(os.environ, **GIT_ENV)
        bin_dir = self.tmp / 'bin'
        self.timer = self.tmp / 'timer-enabled'
        write(bin_dir / 'sudo', '#!/usr/bin/env bash\nexec "$@"\n')
        write(bin_dir / 'python3', '#!/usr/bin/env bash\ncat >/dev/null\n')
        write(bin_dir / 'systemctl', f'''#!/usr/bin/env bash
marker='{self.timer.as_posix()}'
case "$1" in
  is-enabled) test -f "$marker" ;;
  disable) rm -f "$marker" ;;
  enable) touch "$marker" ;;
  is-active) exit 1 ;;
esac
''')
        self.env['PATH'] = bin_dir.as_posix() + os.pathsep + self.env['PATH']
        origin, seed = self.tmp / 'origin.git', self.tmp / 'seed'
        self.git('init', '-q', '--bare', '-b', 'main', origin.as_posix())
        self.git('init', '-q', '-b', 'main', seed.as_posix())
        write(seed / '.gitignore', '.venv/\nrelease-info.json\n', 0o644)
        write(seed / 'app.py', 'VERSION = 1\n', 0o644)
        self.git('-C', seed.as_posix(), 'add', '-A')
        self.git('-C', seed.as_posix(), 'commit', '-qm', 'old')
        self.git('-C', seed.as_posix(), 'push', '-q', origin.as_posix(), 'main')
        self.vm = self.tmp / 'vm'
        self.git('clone', '-q', origin.as_posix(), self.vm.as_posix())
        self.old_head = self.head()
        write(seed / 'app.py', 'VERSION = 2\n', 0o644)
        write(seed / 'local_module.py', 'TRACKED = True\n', 0o644)
        for name in ('install_market_data', 'install_history_schedule', 'install_rebound_research',
                     'install_architecture_guardian', 'enable_collect_only'):
            write(seed / 'deploy' / f'{name}.sh', 'exit 0\n')
        self.git('-C', seed.as_posix(), 'add', '-A')
        self.git('-C', seed.as_posix(), 'commit', '-qm', 'new')
        self.git('-C', seed.as_posix(), 'push', '-q', origin.as_posix(), 'main')
        self.new_head = self.git('-C', seed.as_posix(), 'rev-parse', 'HEAD').strip()
        # VM-local state the updater must preserve or restore.
        write(self.vm / 'release-info.json', '{"release_id": "before"}\n', 0o644)
        write(self.vm / 'local_module.py', 'LOCAL = True\n', 0o644)
        for name in ('python3', 'python'):
            write(self.vm / '.venv' / 'bin' / name,
                  '#!/usr/bin/env bash\n[[ -n "$FAIL_ON" && ( "$1" == "$FAIL_ON" || "$2" == "$FAIL_ON" ) ]] && exit 1\nexit 0\n')
        script = (ROOT / 'deploy/update_vm_main.sh').read_text(encoding='utf-8')
        script = script.replace('/home/ubuntu/easystock-maintenance', (self.tmp / 'maint').as_posix())
        script = script.replace('cd /home/ubuntu/easystock\n', f'cd {self.vm.as_posix()}\n')
        self.script = self.tmp / 'update_vm_main.sh'
        write(self.script, script)
        self.timer.touch()

    def git(self, *args):
        return subprocess.run(['git', *args], check=True, capture_output=True, text=True, env=self.env).stdout

    def head(self):
        return self.git('-C', self.vm.as_posix(), 'rev-parse', 'HEAD').strip()

    def run_update(self, fail_on=''):
        env = dict(self.env, FAIL_ON=fail_on)
        # python3 is stubbed, so emulate its backup step: move the untracked file into the backup.
        moved = self.tmp / 'moved-local_module.py'
        shutil.move(str(self.vm / 'local_module.py'), str(moved))
        script = self.script.read_text(encoding='utf-8').replace(
            'git merge --ff-only origin/main\n',
            f'mkdir -p "$backup/untracked" && cp "{moved.as_posix()}" "$backup/untracked/local_module.py"\n'
            'git merge --ff-only origin/main\n', 1)
        write(self.script, script)
        return subprocess.run([BASH, self.script.as_posix()], capture_output=True, text=True,
                              encoding='utf-8', env=env, cwd=self.tmp)

    def test_failed_verification_rolls_back_checkout_then_restores_timer(self):
        result = self.run_update(fail_on='vm_runtime/tests/test_runtime_safety.py')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), self.old_head)
        self.assertEqual((self.vm / 'app.py').read_text(), 'VERSION = 1\n')
        self.assertEqual((self.vm / 'local_module.py').read_text(), 'LOCAL = True\n')
        self.assertIn('"before"', (self.vm / 'release-info.json').read_text())
        self.assertIn('已回滾到更新前的程式', result.stderr)
        self.assertTrue(self.timer.exists(), 'old, verified code may resume its schedule')

    def test_failure_after_migration_keeps_checkout_and_timer_off(self):
        result = self.run_update(fail_on='deploy/migrate_paper_daily_limit.py')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), self.new_head)
        self.assertFalse(self.timer.exists())
        self.assertIn('不自動恢復', result.stderr)

    def test_success_updates_and_restores_timer(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(), self.new_head)
        self.assertIn(self.new_head, (self.vm / 'release-info.json').read_text())
        self.assertTrue(self.timer.exists())


if __name__ == '__main__':
    unittest.main()
