"""Inspect/apply an RTDB public allowlist using credentials that stay on the VM.

No market data writes or messaging. --apply requires the current rules digest.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import requests
from dotenv import dotenv_values
from google.auth.transport.requests import Request
from google.oauth2 import service_account


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--service-account', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--backup-dir', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    candidate = json.loads(Path(args.candidate).read_text())
    root = candidate['rules']
    if root.get('.read') is not False or root.get('.write') is not False or root.get('market_data', {}).get('.read'):
        raise RuntimeError('Candidate must deny root reads/writes and avoid a market_data read grant')
    url = dotenv_values(args.env_file)['FIREBASE_DATABASE_URL'].rstrip('/')
    if not url.startswith('https://'):
        raise RuntimeError('HTTPS database URL required')
    cred = service_account.Credentials.from_service_account_file(args.service_account, scopes=[
        'https://www.googleapis.com/auth/firebase.database',
        'https://www.googleapis.com/auth/userinfo.email',
    ])
    cred.refresh(Request())
    headers = {'Authorization': 'Bearer ' + cred.token}
    endpoint = url + '/.settings/rules.json'
    def current_rules():
        response = requests.get(endpoint, headers=headers, timeout=20)
        if not response.ok:
            raise RuntimeError('Rules read HTTP ' + str(response.status_code))
        return response.json()
    before = current_rules()
    print(json.dumps({'current_rules_sha256': digest(before), 'candidate_sha256': digest(candidate)}))
    if not args.apply:
        return
    if not args.expected_sha256 or digest(before) != args.expected_sha256:
        raise RuntimeError('Rules changed or no expected digest supplied; inspect again')
    backup_dir = Path(args.backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / ('firebase-rules-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(before, out, indent=2)
    print('Previous rules backup: ' + str(backup))
    # Recheck after the backup, immediately before changing the rules.
    if digest(current_rules()) != args.expected_sha256:
        raise RuntimeError('Concurrent rules change detected; stopped')
    response = requests.put(endpoint, headers=headers, json=candidate, timeout=20)
    if not response.ok:
        raise RuntimeError('Rules apply HTTP ' + str(response.status_code))
    try:
        if current_rules() != candidate:
            raise RuntimeError('Rules readback differs')
        active_response = requests.get(url+'/market_data/active_release.json', timeout=20)
        if not active_response.ok:
            raise RuntimeError('Public release pointer denied')
        active = active_response.json()
        public = ['meta','summary','backtests','kline/2330','intraday_live','intraday_picks',
                  'premarket_brief','daytrade_learning_status','history_training_status','dual_review_status','public_feed']
        if isinstance(active, str):
            public += ['releases/'+active+'/'+n for n in ('meta','summary','backtests','kline/2330')]
        for node in public:
            # Shallow reads check authorization without downloading histories or trades.
            status = requests.get(url+'/market_data/'+node+'.json', params={'shallow':'true'}, timeout=20).status_code
            if status != 200:
                raise RuntimeError('Public node denied: '+node+' HTTP '+str(status))
        for node in ['/', '/market_data', '/market_data/line_groups', '/market_data/paper_game',
                     '/market_data/history', '/market_data/selection_history', '/market_data/overnight_history',
                     '/market_data/intraday_archive', '/market_data/daytrade_research']:
            status = requests.get(url+node+'.json', params={'shallow':'true'}, timeout=20).status_code
            if status not in (401,403):
                raise RuntimeError('Private path still readable: '+(node or '/'))
        status = requests.get(url+'/market_data/line_groups.json', headers=headers, params={'shallow':'true'}, timeout=20).status_code
        if status != 200:
            raise RuntimeError('Service account private read failed')
    except Exception:
        # Restore only our own failed deployment, never overwrite a concurrent change.
        if current_rules() == candidate:
            restored = requests.put(endpoint, headers=headers, json=before, timeout=20)
            print('Rollback HTTP ' + str(restored.status_code))
        raise
    print('Verified: public endpoints readable; private/root reads denied; service account still works. No data writes.')


if __name__ == '__main__':
    main()
