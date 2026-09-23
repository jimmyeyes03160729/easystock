"""Trusted production adapter. No broker imports or order operations."""
import ast
import copy
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from common import APP, ROOT, STATE, SERVICE, now, read_json, write_json, digest

def environment():
    from dotenv import dotenv_values
    for path in (APP / '.env', Path('/home/ubuntu/easystock-admin.env')):
        for key, value in dotenv_values(path).items():
            if value is not None:
                os.environ.setdefault(key, value)

def database():
    import firebase_admin
    from firebase_admin import credentials, db
    environment()
    if not firebase_admin._apps:
        source = os.environ.get('FIREBASE_SERVICE_ACCOUNT_FILE')
        if source:
            source = Path(source)
            if not source.is_absolute():
                source = APP / source
            credential = credentials.Certificate(str(source))
        else:
            credential = credentials.Certificate(json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT_JSON']))
        firebase_admin.initialize_app(credential, {'databaseURL': os.environ.get('FIREBASE_DATABASE_URL', 'https://easystock-c237a-default-rtdb.firebaseio.com')})
    return db.reference('/market_data')

def ledger():
    environment()
    path = Path(os.environ.get('EASYSTOCK_ADMIN_DB', '/home/ubuntu/easystock-admin/state.sqlite'))
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con

def active():
    return subprocess.run(['systemctl', 'show', SERVICE, '-p', 'ActiveState', '--value'], capture_output=True, text=True, check=True).stdout.strip()

def inspect_state():
    root = database()
    raw = root.child('intraday_live').get() or {}
    remote = raw.get('open_positions') or {}
    if not isinstance(remote, dict):
        raise ValueError('OPEN schema invalid')
    with ledger() as con:
        positions = [dict(r) for r in con.execute('select symbol,entry_date,entry_price,shares from paper_trade_positions')]
        ghosts = []
        for symbol, row in remote.items():
            if not isinstance(row, dict):
                continue
            incomplete = row.get('status') == 'OPEN' and not any(row.get(k) for k in ('trade_id', 'entry_time', 'shares', 'entry_price'))
            stamp = str(row.get('last_update_at', ''))[:10]
            if not incomplete or stamp != raw.get('scan_date'):
                continue
            fills = con.execute('select count(*) from paper_trade_fills where symbol=? and trade_date=?', (symbol, stamp)).fetchone()[0]
            skipped = con.execute('select count(*) from paper_trade_events where symbol=? and date=? and action=?', (symbol, stamp, '略過')).fetchone()[0]
            if not fills and skipped and not any(p['symbol'] == symbol for p in positions):
                ghosts.append(symbol)
    valid = {k:v for k,v in remote.items() if k not in ghosts}
    local = {p['symbol']:p for p in positions}
    mismatch = set(valid) != set(local)
    for symbol in set(valid) & set(local):
        p, r = local[symbol], valid[symbol]
        try:
            mismatch |= int(p['shares']) != int(r.get('shares', -1)) or abs(float(p['entry_price'])-float(r.get('entry_price', -1))) > 1e-6
        except (ValueError, TypeError, AttributeError):
            mismatch = True
    manifest = read_json(ROOT/'baseline/manifest.json', {})
    syntax_errors, hashes = [], {}
    for name in ('firebase_store.py', 'intraday_live.py', 'position_manager.py'):
        data = (APP/name).read_bytes()
        hashes[name] = digest(data)
        try:
            ast.parse(data)
        except (SyntaxError, ValueError):
            syntax_errors.append(name)
    orders = subprocess.run(['systemctl','show',SERVICE,'-p','Environment','--value'],capture_output=True,text=True,check=True).stdout
    # A future mode/source change
    # disables unattended restarts rather than changing execution mode itself.
    paper_only = ('AI_PAPER_MODE=1' in orders
                  and hashes.get('intraday_live.py') == manifest.get('intraday_live.py')
                  and hashes.get('position_manager.py') == manifest.get('position_manager.py'))
    result = {'scan_date': raw.get('scan_date'), 'last_update_at': raw.get('last_update_at'),
        'session': raw.get('session'), 'radar_at': (raw.get('radar_meta') or {}).get('updated_at'),
        'service_active': active(),
        'service_substate': subprocess.run(['systemctl','show',SERVICE,'-p','SubState','--value'],capture_output=True,text=True,check=True).stdout.strip(),
        'ghost_symbols': sorted(ghosts), 'remote_positions': len(remote),
        'valid_remote_positions': len(valid), 'ledger_positions': len(positions),
        'ledger_mismatch': bool(mismatch), 'syntax_errors': syntax_errors, 'source_hashes': hashes,
        'restorable_syntax_error': syntax_errors == ['firebase_store.py'] and bool(manifest.get('firebase_store.py')),
        'orders_enabled': not paper_only}
    return result, raw

def quarantine():
    first, old = inspect_state()
    if first['service_active'] in ('active','activating','deactivating') or first['ledger_positions'] or first['valid_remote_positions'] or first['ledger_mismatch'] or not first['ghost_symbols']:
        raise RuntimeError('Quarantine preconditions no longer satisfied')
    root = database()
    key = 'guardian_' + now().strftime('%Y%m%dT%H%M%S%f')
    write_json(STATE/'backups'/f'{key}.json',old)
    archive = root.child('intraday_archive').child(key)
    archive.set(old)
    if archive.get() != old:
        raise RuntimeError('Archive verification failed')
    fresh, check = inspect_state()
    if check != old or fresh['ledger_positions'] or fresh['ledger_mismatch'] or fresh['ghost_symbols'] != first['ghost_symbols'] or fresh['service_active'] in ('active','activating','deactivating'):
        raise RuntimeError('State changed during quarantine')
    new = copy.deepcopy(old)
    for symbol in first['ghost_symbols']:
        new['open_positions'].pop(symbol)
    if not new['open_positions']:
        new.pop('open_positions')
    new['reconciliation'] = {'at':now().isoformat(),'reason':'Unfilled paper candidates verified against SQLite; archived, not settled as trades.','symbols':first['ghost_symbols'],'archive_key':key}
    def change(current):
        if current != old:
            raise RuntimeError('Concurrent Firebase change; quarantine aborted')
        return new
    root.child('intraday_live').transaction(change)
    after, value = inspect_state()
    if after['remote_positions'] or value.get('closed_trades') != old.get('closed_trades'):
        raise RuntimeError('Quarantine verification failed; inspect archive '+key)
    return {'archive_key':key,'symbols':first['ghost_symbols']}

if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'snapshot':
        print(json.dumps(inspect_state()[0],ensure_ascii=False))
    elif command == 'quarantine':
        print(json.dumps(quarantine(),ensure_ascii=False))
    elif command == 'publish':
        payload = json.load(sys.stdin)
        database().child('intraday_live').child('guardian_health').set(payload)
    else:
        raise SystemExit('unknown operation')
