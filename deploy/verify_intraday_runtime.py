#!/usr/bin/env python3
"""Verify the running intraday process uses the approved model path.

This intentionally prints only non-secret model/service diagnostics.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


EXPECTED_MODEL_PATH = '/home/ubuntu/easystock-learning-data/models/latest-approved.json'
SERVICE = 'easystock-intraday.service'


def parse_environ(payload: bytes) -> dict[bytes, bytes]:
    """Parse Linux /proc/<pid>/environ without decoding secret values."""
    return dict(
        item.split(b'=', 1)
        for item in payload.split(b'\0')
        if b'=' in item
    )


def main() -> int:
    if os.name == 'nt' or not Path('/proc').is_dir():
        print('FAIL: Linux /proc process environment is required', file=sys.stderr)
        return 1
    result = subprocess.run(
        ['systemctl', 'show', SERVICE, '--property=MainPID', '--value'],
        check=False, capture_output=True, text=True,
    )
    try:
        pid = int(result.stdout.strip())
    except ValueError:
        pid = 0
    if result.returncode != 0 or pid <= 0:
        print('FAIL: intraday MainPID is not active', file=sys.stderr)
        return 1
    environ_path = Path('/proc') / str(pid) / 'environ'
    try:
        values = parse_environ(environ_path.read_bytes())
    except OSError as exc:
        print(f'FAIL: cannot read MainPID environment: {type(exc).__name__}', file=sys.stderr)
        return 1
    model_path = values.get(b'AI_PAPER_MODEL_PATH', b'').decode('utf-8', 'replace')
    if model_path != EXPECTED_MODEL_PATH:
        print('FAIL: MainPID AI_PAPER_MODEL_PATH is not latest-approved.json', file=sys.stderr)
        return 1
    if values.get(b'LIVE_ENTRY_MODE', b'').decode() != 'model':
        print('FAIL: MainPID LIVE_ENTRY_MODE is not model', file=sys.stderr)
        return 1
    if values.get(b'LEARNING_ENABLED', b'').decode() not in {'1', 'true', 'True', 'yes', 'on'}:
        print('FAIL: MainPID LEARNING_ENABLED is not enabled', file=sys.stderr)
        return 1
    os.environ['AI_PAPER_MODEL_PATH'] = model_path
    learning_dir = values.get(b'LEARNING_DATA_DIR')
    if learning_dir:
        os.environ['LEARNING_DATA_DIR'] = learning_dir.decode('utf-8', 'replace')
    sys.path.insert(0, '/home/ubuntu/easystock')
    from daytrade_learning.model_runtime import DaytradeModel
    model = DaytradeModel()
    if model.artifact is None:
        print(f'FAIL: model_ready=False reason={model.reason}', file=sys.stderr)
        return 1
    print(f'MainPID={pid}')
    print(f'model_ready=True version={model.model_version} sha256={model.artifact_sha256}')
    print('AI_PAPER_MODEL_PATH=latest-approved.json')
    print('LIVE_ENTRY_MODE=model learning_enabled=True')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
