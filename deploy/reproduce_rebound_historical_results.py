"""Reproduce frozen P2/P3/P4 code using ONLY the bounded temporary snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

COMMITS = {'P2': ('93649dd', 'research'), 'P3': ('99c4d51', 'research_horizon'),
           'P4': ('1fef953', 'research_filter')}
SOURCE_CODE = Path('/home/ubuntu/easystock')
SOURCE_RESULTS = Path('/home/ubuntu/easystock-learning-data/rebound')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    history = root / 'history'
    manifest = json.loads((history / 'manifest.json').read_text())
    if manifest['before'] != '2026-10-07' or manifest['labels_read'] is not False:
        raise ValueError('unbounded_reproduction_input')
    report = {'source_labels_read': False, 'holdout_read': False, 'studies': {}}
    for study, (commit, module) in COMMITS.items():
        code, data = root / f'legacy-{study.lower()}', root / f'legacy-{study.lower()}-data'
        code.mkdir(exist_ok=False)
        data.mkdir(exist_ok=False)
        archive = subprocess.Popen(['git', '-C', str(SOURCE_CODE), 'archive', commit], stdout=subprocess.PIPE)
        subprocess.run(['tar', '-x', '-C', str(code)], stdin=archive.stdout, check=True)
        archive.stdout.close()
        if archive.wait():
            raise RuntimeError('legacy_archive_failed')
        for filename in ('dataset-v2.sqlite', 'market-daily.sqlite'):
            shutil.copy2(history / filename, data / filename)  # ONLY the bounded snapshot
        original = next((SOURCE_RESULTS / f'phase{study[-1]}').glob(f'REBOUND_{study}_*-result.json'))
        original_bytes = original.read_bytes()  # known historical-only result, not a database
        (root / f'{study}-original.json').write_bytes(original_bytes)
        output = root / f'{study}-reproduced.json'
        env = dict(os.environ, EASYSTOCK_REBOUND_DATA_DIR=str(data), OMP_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   PYTHONPATH='/home/ubuntu/easystock-learning-venv/lib/python3.10/site-packages')
        print(f'Reproducing {study} at {commit} on bounded history', flush=True)
        subprocess.run(['/home/ubuntu/easystock/.venv/bin/python', '-m', f'rebound_learning.{module}',
                        '--output', str(output)], cwd=code, env=env, check=True)
        expected = hashlib.sha256(original_bytes).hexdigest()
        # file_digest is unavailable on the VM's Python 3.10.
        actual = hashlib.sha256(output.read_bytes()).hexdigest()
        report['studies'][study] = {'commit': commit, 'original_sha256': expected,
                                    'reproduced_sha256': actual, 'byte_identical': expected == actual}
        print(json.dumps(report['studies'][study]), flush=True)
    (root / 'legacy-reproduction.json').write_text(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
