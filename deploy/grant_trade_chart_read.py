"""Grant public read access only to the new, price-only dated chart feed."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import firebase_admin
import requests
from firebase_store import FirebaseStore, FIREBASE_DATABASE_URL, FIREBASE_ROOT_PATH
from trade_chart_feed import records


def candidate(before, root):
    out = copy.deepcopy(before)
    rules = out['rules']
    if rules.get('.read') is not False or rules.get('.write') is not False or rules.get(root, {}).get('.read'):
        raise ValueError('unexpected_root_policy')
    rules.setdefault(root, {})['intraday_charts'] = {'$day': {'$symbol': {'.read': True, '.write': False}}}
    return out


def main(backup_dir):
    store = FirebaseStore()
    token = firebase_admin.get_app().credential.get_access_token().access_token
    headers = {'Authorization': 'Bearer ' + token}
    url = FIREBASE_DATABASE_URL.rstrip('/')
    endpoint = url + '/.settings/rules.json'

    def current():
        response = requests.get(endpoint, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()

    before = current(); after = candidate(before, FIREBASE_ROOT_PATH)
    directory = Path(backup_dir); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / ('chart-rules-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(before, f)
    if current() != before:
        raise RuntimeError('concurrent_policy_change')
    if after != before:
        requests.put(endpoint, headers=headers, json=after, timeout=20).raise_for_status()
    try:
        if current() != after:
            raise RuntimeError('policy_readback_mismatch')
        targets = records(store.live.get() or {})
        if not targets:
            raise RuntimeError('no_chart_acceptance_targets')
        for day, symbol in targets:
            response = requests.get(f'{url}/{FIREBASE_ROOT_PATH}/intraday_charts/{day}/{symbol}.json', params={'shallow': 'true'}, timeout=15)
            response.raise_for_status()
            if not isinstance(response.json(), dict) or 'minute_bars' not in response.json():
                raise RuntimeError('missing_chart_' + symbol)
        for node in ['', FIREBASE_ROOT_PATH, FIREBASE_ROOT_PATH+'/intraday_charts', FIREBASE_ROOT_PATH+'/intraday_archive', FIREBASE_ROOT_PATH+'/line_groups', FIREBASE_ROOT_PATH+'/daytrade_research']:
            if requests.get(f'{url}/{node}.json', params={'shallow': 'true'}, timeout=15).status_code not in (401, 403):
                raise RuntimeError('private_or_collection_read_policy_changed')
        print(f'Chart-only public read verified for {len(targets)} A/B symbols; all other rules preserved.')
    except Exception:
        if current() == after and before != after:
            requests.put(endpoint, headers=headers, json=before, timeout=20).raise_for_status()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', required=True)
    main(parser.parse_args().backup_dir)
