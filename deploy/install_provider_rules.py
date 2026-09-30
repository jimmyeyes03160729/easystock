"""Apply only the two health read grants, preserving all existing RTDB rules."""
import json
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env')
credential = values.get('FIREBASE_SERVICE_ACCOUNT_FILE')
if not credential: raise SystemExit('Firebase service account file unavailable')
command = [sys.executable, str(root / 'tools/firebase_rules.py'), '--env-file', str(root / '.env'),
           '--service-account', credential, '--candidate', str(root / 'firebase.rules.json'),
           '--backup-dir', '/home/ubuntu/easystock-maintenance/firebase-rules', '--merge-health']
result = subprocess.run(command, check=True, capture_output=True, text=True)
identity = json.loads(result.stdout.splitlines()[0])
if identity['current_rules_sha256'] == identity['candidate_sha256']:
    print('Health rules already installed; unchanged.')
else:
    subprocess.run(command + ['--apply', '--expected-sha256', identity['current_rules_sha256']], check=True)
