"""Reviewed, selective deployment with private backup and automatic rollback."""
from datetime import datetime,timezone
import hashlib,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path

LIVE=Path('/home/ubuntu/easystock')
STAGE=Path(__file__).resolve().parents[1]
OLD={'line_stock_bot.py':'31c093d0d1dbfa5cf3160ca787b07a843fdfdcda2d9532e8af50e259fbd5ee9e',
     'easystock_admin/notifications.py':'2ab4a112adccee95b9b4cd76a6382bbf6d2395dfc2920becea595ce30d7c5638',
     'easystock_admin/static/index.html':'30b485c9033a718fe1c8d66338fb00935520f8055ccda05d3f920c421ae94ed1',
     'easystock_admin/static/admin.js':'2e76854b9a2145b8bc725a22112436eb18c6488d0332016db6563ab4b05c7496'}
NEW=['telegram_queries.py','telegram_stock_bot.py']
WEB='easystock-line-stock-bot.service'
BOT='easystock-telegram-stock-bot.service'
DB=Path('/home/ubuntu/easystock-admin/state.sqlite')

def command(*args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL)
def copy_db(src,dst):
    with sqlite3.connect(src) as source,sqlite3.connect(dst) as dest:source.backup(dest)

def main():
    os.umask(0o077)
    if not str(STAGE).startswith('/home/ubuntu/easystock-maintenance/'):raise RuntimeError('Invalid staging directory')
    for name,expected in OLD.items():
        if hashlib.sha256((LIVE/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('Changed source: '+name)
    for name in NEW:
        if (LIVE/name).exists():raise RuntimeError('New file exists: '+name)
    unit=Path('/etc/systemd/system')/BOT
    if unit.exists():raise RuntimeError('Service already exists')
    for name in list(OLD)+NEW:
        if name.endswith('.py'):compile((STAGE/'vm_runtime'/name).read_text(),name,'exec')
    backup=STAGE/('backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));backup.mkdir(mode=0o700)
    for name in OLD:
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(LIVE/name,dest)
    command('sudo','systemctl','stop',WEB)
    try:copy_db(DB,backup/'state.sqlite')
    except BaseException:
        command('sudo','systemctl','start',WEB);raise
    installed=[];unit_installed=False
    try:
        for name in list(OLD)+NEW:
            dest=LIVE/name;tmp=dest.with_name(dest.name+'.query-install')
            shutil.copyfile(STAGE/'vm_runtime'/name,tmp);tmp.chmod(0o600);tmp.replace(dest);installed.append(name)
        sys.path.insert(0,str(LIVE))
        from easystock_admin.store import Store
        store=Store()
        with store.tx() as db:
            db.execute('UPDATE telegram_policy SET replies=1,version=version+1 WHERE id=1')
            store._audit(db,'deployment','telegram_group_queries',{'replies':True})
        command('sudo','systemctl','start',WEB)
        import requests
        for attempt in range(15):
            try:
                if requests.get('http://127.0.0.1:8088/healthz',timeout=2).status_code==200:break
            except requests.RequestException:pass
            time.sleep(1)
        else:raise RuntimeError('Query backend failed health check')
        command('sudo','install','-m','644',str(STAGE/'deploy'/BOT),str(unit));unit_installed=True
        command('sudo','systemctl','daemon-reload')
        command('sudo','systemctl','enable','--now',BOT)
        # A completed poll proves the bot authenticated and consumed updates.
        started=time.time()
        for attempt in range(35):
            with store.tx() as db:row=db.execute("SELECT value FROM meta WHERE key='telegram_last_poll'").fetchone()
            if row and float(row[0])>=started:break
            time.sleep(1)
        else:raise RuntimeError('Telegram poller did not become ready')
    except BaseException:
        if unit_installed:
            subprocess.run(['sudo','systemctl','disable','--now',BOT],stdout=subprocess.DEVNULL)
            command('sudo','rm',str(unit))
            command('sudo','systemctl','daemon-reload')
        command('sudo','systemctl','stop',WEB)
        for name in OLD:shutil.copy2(backup/name,LIVE/name)
        for name in NEW:
            if name in installed:(LIVE/name).unlink()
        copy_db(backup/'state.sqlite',DB)
        command('sudo','systemctl','start',WEB)
        raise
    print('DEPLOYED; backup:',backup)
    print('Telegram query poller ready; existing LINE/push settings preserved')

if __name__=='__main__':main()
