"""One-time hash-guarded deployment. Run from the reviewed staging directory."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

LIVE=Path('/home/ubuntu/easystock')
STAGE=Path(__file__).resolve().parents[1]
FILES={
    'intraday_live.py':'d0a86f4e6b8e2b1910f521b948cc3483295d49bb501a0e2418b0c179f0a5c210',
    'line_stock_bot.py':'7d6cecef91ff43e6b1d34279fbc2cd309727acb5b1f6ec58b6612b68364134eb',
    'easystock_admin/conversations.py':'9b1f3413b32d750f1ae15e1e555a9a019dbcec2d0184e2fb0882b8a43f03f150',
    'easystock_admin/web.py':'16719d121d9e3ab4c1e981c3baa24c46aa12bd93b372a8290258034cea6b70e3',
    'easystock_admin/static/index.html':'6a8e8031d4075456409028ff50395ed01e5abfe69cba08010bdc4aea57b07c0a',
    'easystock_admin/static/admin.js':'0edf6d5b343755600c518d787105e3328fefcd3ba26ce98ab0b13ec8a392268d',
}
NEW=['easystock_admin/notifications.py','trade_notifications.py']
SERVICE='easystock-line-stock-bot.service'
ATTESTATIONS=[LIVE/'learning_status_engine_hashes.json',Path('/home/ubuntu/easystock-history-status-r1/reviewed_engine.json')]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def command(*args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
def backup_db(source,dest):
    with sqlite3.connect(source) as src,sqlite3.connect(dest) as dst:src.backup(dst)


def main():
    os.umask(0o077)
    if STAGE==LIVE or not str(STAGE).startswith('/home/ubuntu/easystock-maintenance/'):
        raise RuntimeError('Installer must run from maintenance staging')
    # Check process as well as service names; do not replace a running engine.
    running=subprocess.run(['pgrep','-f','[p]ython.*intraday_live.py'],capture_output=True).returncode==0
    if running:raise RuntimeError('Intraday engine is running; deploy after market close')
    for name,expected in FILES.items():
        if sha(LIVE/name)!=expected:raise RuntimeError('Production source changed: '+name)
    for name in NEW:
        if (LIVE/name).exists():raise RuntimeError('New target exists: '+name)
    for name in list(FILES)+NEW:
        if name.endswith('.py'):compile((STAGE/'vm_runtime'/name).read_text(),name,'exec')
    keep=os.environ.get('EASYSTOCK_CONFIRMED_GROUP_TAG','')
    retire=os.environ.get('EASYSTOCK_RETIRED_GROUP_TAG','')
    if len(keep)!=8 or len(retire)!=8 or keep==retire:raise RuntimeError('Explicit group confirmation required')
    dbpath=Path('/home/ubuntu/easystock-admin/state.sqlite')
    with sqlite3.connect(dbpath) as db:
        rows=db.execute("SELECT id,source_id FROM line_conversations WHERE kind='group'").fetchall()
    bytag={hashlib.sha256(sid.encode()).hexdigest()[:8]:key for key,sid in rows}
    if set(bytag)!={keep,retire} or len(rows)!=2:raise RuntimeError('Group inventory changed; review again')
    from dotenv import load_dotenv,dotenv_values
    credentials=Path('/home/ubuntu/easystock-telegram.env')
    if credentials.stat().st_mode & 0o077:raise RuntimeError('Telegram config must have private permissions')
    if not all(dotenv_values(credentials).get(k) for k in ('TELEGRAM_BOT_TOKEN','TELEGRAM_GROUP_ID')):
        raise RuntimeError('Telegram credentials missing')
    backup=STAGE/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    for name in FILES:
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(LIVE/name,dest)
    for path in ATTESTATIONS:shutil.copy2(path,backup/path.name)
    command('sudo','systemctl','stop',SERVICE)
    try:backup_db(dbpath,backup/'state.sqlite')
    except BaseException:
        command('sudo','systemctl','start',SERVICE)
        raise
    installed=[]
    try:
        for name in list(FILES)+NEW:
            dest=LIVE/name;dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=dest.with_name(dest.name+'.telegram-install');shutil.copyfile(STAGE/'vm_runtime'/name,tmp)
            tmp.chmod(0o600);tmp.replace(dest);installed.append(name)
        # Notification-only changes; no learned model or trading parameters applied.
        for path in ATTESTATIONS:
            known=json.loads(path.read_text());known.append(sha(LIVE/'intraday_live.py'))
            path.write_text(json.dumps(sorted(set(known))));path.chmod(0o600)
        load_dotenv(LIVE/'.env');load_dotenv('/home/ubuntu/easystock-admin.env',override=True)
        sys.path.insert(0,str(LIVE))
        from easystock_admin.store import Store
        from easystock_admin import conversations as c,notifications as n
        store=Store()
        if not all(n.telegram_config()):raise RuntimeError('Invalid Telegram configuration')
        with store.tx() as db:
            preferences=json.loads(db.execute('SELECT body FROM line_policy WHERE id=1').fetchone()[0])
            # Preserve effective controls on the only retained group, even if globals were off.
            db.execute('UPDATE line_conversations SET replies=replies * ?,push=push * ?,archived=0,version=version+1 WHERE id=?',
                       (bool(preferences['replies'] and preferences['groups']),bool(preferences['trade_push']),bytag[keep]))
            db.execute('UPDATE line_conversations SET replies=0,push=0,archived=1,version=version+1 WHERE id<>?',(bytag[keep],))
            db.execute('UPDATE line_policy SET body=?,version=version+1 WHERE id=1',(json.dumps(c.DEFAULTS),))
            db.execute('UPDATE telegram_policy SET push=1,version=version+1 WHERE id=1')
            db.execute('DELETE FROM binds')
            db.execute("DELETE FROM meta WHERE key='line_user'")
            store._audit(db,'deployment','group_only_migration',{'retained':bytag[keep],'retired':bytag[retire],'telegram_push':True})
        command('sudo','systemctl','start',SERVICE)
        command('sudo','systemctl','is-active','--quiet',SERVICE)
        import requests,time
        healthy=False
        for _ in range(10):
            try:healthy=requests.get('http://127.0.0.1:8088/healthz',timeout=2).status_code==200
            except requests.RequestException:pass
            if healthy:break
            time.sleep(1)
        if not healthy:raise RuntimeError('Webhook health check failed')
    except BaseException:
        command('sudo','systemctl','stop',SERVICE)
        for name in FILES:shutil.copy2(backup/name,LIVE/name)
        # Only remove files this installer created at explicit reviewed targets.
        for name in NEW:
            if name in installed:(LIVE/name).unlink()
        backup_db(backup/'state.sqlite',dbpath)
        for path in ATTESTATIONS:shutil.copy2(backup/path.name,path)
        command('sudo','systemctl','start',SERVICE)
        raise
    print('DEPLOYED; backup:',backup)
    print('Verified source hashes:',json.dumps({name:sha(LIVE/name) for name in list(FILES)+NEW}))


if __name__=='__main__':main()
