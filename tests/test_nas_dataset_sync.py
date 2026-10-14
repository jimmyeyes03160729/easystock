"""Static guards for the NAS backtest-dataset sync (ops/nas/sync_datasets.sh)."""
import shutil
import subprocess
from pathlib import Path

import pytest

NAS = Path(__file__).resolve().parents[1] / 'ops' / 'nas'
SCRIPT = NAS / 'sync_datasets.sh'


@pytest.mark.skipif(shutil.which('bash') is None, reason='bash not available')
@pytest.mark.parametrize('name', ['sync_datasets.sh', 'healthcheck.sh', 'docker-entrypoint.sh'])
def test_scripts_parse(name):
    subprocess.run(['bash', '-n', str(NAS / name)], check=True)


def test_copy_only_and_scoped_cleanup():
    text = SCRIPT.read_text(encoding='utf-8')
    code = [line for line in text.splitlines() if not line.lstrip().startswith('#')]
    rsync_calls = [line for line in code if line.lstrip().startswith('rsync ')]
    assert len(rsync_calls) == 3
    # A VM-side deletion must never propagate to the NAS copy.
    assert not any('--delete' in line for line in code)
    # The only VM deletion is this run's own snapshot under the dedicated root.
    assert text.count('shutil.rmtree(') == 1
    assert "allowed_root = pathlib.Path('/home/ubuntu/easystock-sync-snapshots')" in text
    assert "target = root / ('datasets-' + stamp)" in text
    assert 'disk_usage(root).free < need + 3 * 1024 ** 3' in text


def test_scheduled_and_packaged():
    cron = (NAS / 'easystock-backup.cron').read_text(encoding='utf-8')
    assert cron.endswith('\n')
    assert '45 15 * * * root /bin/bash /opt/easystock/ops/nas/sync_datasets.sh' in cron
    docker = (NAS / 'Dockerfile').read_text(encoding='utf-8')
    assert 'sync_datasets.sh' in docker.split('COPY sync_from_vm.sh', 1)[1].splitlines()[0]
    assert 'datasets-sync.log' in (NAS / 'docker-entrypoint.sh').read_text(encoding='utf-8')
