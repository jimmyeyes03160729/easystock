"""Run on Oracle VM after offline tests. Hash-guarded, backed-up source install."""
import ast
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

LIVE=Path('/home/ubuntu/easystock')
STAGE=Path('/home/ubuntu/easystock-maintenance/line-history-review')
SOURCE=STAGE/'vm_runtime'
FILES=['line_bot.py','line_group_manager.py','line_stock_bot.py','intraday_live.py','premarket_ai.py',
       'daytrade_summary_push.py','easystock_admin/store.py','easystock_admin/web.py',
       'easystock_admin/static/index.html','easystock_admin/static/admin.js']
NEW=['line_policy.py','easystock_admin/conversations.py',
     'history/collector_core.py','history/daily_history.py','history/history_status.py','history/train_history.py']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def command(*args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL)

def main():
    os.umask(0o077)
    original=json.loads((SOURCE/'source-manifest.json').read_text())['files']
    for path in FILES:
        if sha(LIVE/path)!=original[path]:raise RuntimeError('Production source changed: '+path)
    for path in NEW:
        if (LIVE/path).exists():raise RuntimeError('New target already exists: '+path)
    for path in FILES+NEW:
        if path.endswith('.py'):compile((SOURCE/path).read_text(),path,'exec')
    # Preserve the owner's existing identity while moving it out of source code.
    old=ast.parse((LIVE/'easystock_admin/store.py').read_text())
    owner=next(ast.literal_eval(n.value) for n in old.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OWNER' for t in n.targets))
    if not isinstance(owner,str) or not owner or '\n' in owner:raise ValueError('Unexpected owner configuration')
    backup=STAGE/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    backup.mkdir(mode=0o700)
    for path in FILES:
        dest=backup/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(LIVE/path,dest)
    env=Path('/home/ubuntu/easystock-admin.env');shutil.copy2(env,backup/'admin.env')
    for path in ['plan.json','progress.json']:
        shutil.copy2(Path('/home/ubuntu/easystock-history-expanded-data')/path,backup/path)
    dbpath=Path('/home/ubuntu/easystock-admin/state.sqlite')
    with sqlite3.connect(dbpath) as source,sqlite3.connect(backup/'state.sqlite') as dest:source.backup(dest)
    reviewed=Path('/home/ubuntu/easystock-history-status-r1/reviewed_engine.json')
    shutil.copy2(reviewed,backup/'reviewed_engine.json')
    command('sudo','systemctl','stop','easystock-line-stock-bot.service')
    try:
        from dotenv import dotenv_values
        values=dotenv_values(env)
        if not values.get('ADMIN_OWNER_EMAIL'):
            with env.open('a') as stream:stream.write('\nADMIN_OWNER_EMAIL='+owner+'\n')
            env.chmod(0o600)
        elif values['ADMIN_OWNER_EMAIL'].lower()!=owner.lower():raise ValueError('Configured owner differs')
        for path in FILES+NEW:
            dest=LIVE/path;dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=dest.with_name(dest.name+'.install-tmp');shutil.copyfile(SOURCE/path,tmp);tmp.chmod(0o600);tmp.replace(dest)
        known=json.loads(reviewed.read_text());known.append(sha(LIVE/'intraday_live.py'))
        reviewed.write_text(json.dumps(sorted(set(known))));reviewed.chmod(0o600)
        sys.path.insert(0,str(LIVE))
        from dotenv import load_dotenv
        load_dotenv(LIVE/'.env');load_dotenv(env,override=True)
        from easystock_admin.store import Store
        from easystock_admin import conversations as c
        from line_group_manager import get_active_groups
        store=Store();c.update(store,{'values':c.DEFAULTS,'version':c.state(store)['version']})
        for gid in get_active_groups():
            # No paid sends, no deletions. Previously confirmed intended group
            # remains enabled; the inaccessible older group is left disabled.
            key=c.observe(store,{'type':'group','groupId':gid})
            row=next(r for r in c.state(store)['conversations'] if r['id']==key)
            preferred=os.environ.get('EASYSTOCK_CONFIRMED_GROUP_TAG','')
            intended=bool(preferred) and hashlib.sha256(gid.encode()).hexdigest().startswith(preferred)
            c.update_conversation(store,key,{'label':'使用中群組' if intended else '舊群組（停用推播）',
                'replies':True,'push':intended,'version':row['version']})
        # Seed a previously linked owner without exposing the LINE user ID.
        with store.tx() as db:
            row=db.execute("SELECT value FROM meta WHERE key='line_user'").fetchone()
        if row:c.observe(store,{'type':'user','userId':row[0]})
        command('sudo','systemctl','start','easystock-line-stock-bot.service')
        command('sudo','systemctl','is-active','--quiet','easystock-line-stock-bot.service')
    except BaseException:
        for path in FILES:shutil.copy2(backup/path,LIVE/path)
        shutil.copy2(backup/'admin.env',env);shutil.copy2(backup/'reviewed_engine.json',reviewed)
        command('sudo','systemctl','start','easystock-line-stock-bot.service')
        raise
    for name in ['easystock-history-download.service','easystock-history-download.timer',
                 'easystock-history-train.service','easystock-history-train.timer']:
        command('sudo','install','-m','644',str(STAGE/'deploy'/name),'/etc/systemd/system/'+name)
    command('sudo','mkdir','-p','/etc/systemd/system/easystock-history-status.service.d')
    command('sudo','install','-m','644',str(STAGE/'deploy/history-status-override.conf'),
            '/etc/systemd/system/easystock-history-status.service.d/override.conf')
    command('sudo','systemctl','daemon-reload')
    command('sudo','systemctl','enable','--now','easystock-history-download.timer','easystock-history-train.timer')
    command('sudo','systemctl','start','easystock-history-status.service')
    print('Installed sources and timers. Backup:',backup)

if __name__=='__main__':main()
