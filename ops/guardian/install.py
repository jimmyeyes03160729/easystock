"""Idempotent service installation. Run as root after inspecting this package."""
import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=Path('/opt/easystock-guardian')
STATE=Path('/var/lib/easystock-guardian')
JOBS=Path('/var/lib/easystock-codex/jobs')
APP=Path('/home/ubuntu/easystock')
PYTHON=str(APP/'.venv/bin/python3')
assert os.geteuid()==0
ROOT.mkdir(exist_ok=True)
STATE.mkdir(exist_ok=True,mode=0o700)
STATE.chmod(0o700)
try:account=pwd.getpwnam('easystock-codex')
except KeyError:
    subprocess.run(['useradd','--system','--home-dir','/var/lib/easystock-codex','--shell','/usr/sbin/nologin','easystock-codex'],check=True)
    account=pwd.getpwnam('easystock-codex')
JOBS.mkdir(parents=True,exist_ok=True)
os.chown(JOBS.parent,account.pw_uid,account.pw_gid);os.chown(JOBS,account.pw_uid,account.pw_gid)
JOBS.parent.chmod(0o700)
for path in HERE.glob('*.py'):
    shutil.copy2(path,ROOT/path.name);(ROOT/path.name).chmod(0o644)
shutil.copy2('/tmp/easystock-codex-bin','/usr/local/bin/easystock-codex')
Path('/usr/local/bin/easystock-codex').chmod(0o755)
shutil.copy2('/tmp/codex-code-mode-host','/usr/local/bin/codex-code-mode-host')
Path('/usr/local/bin/codex-code-mode-host').chmod(0o755)
shutil.copy2('/tmp/easystock-codex-release.json',ROOT/'codex-release.json')
baseline=ROOT/'baseline';baseline.mkdir(exist_ok=True)
import hashlib
manifest={}
for name in ('firebase_store.py','intraday_live.py','position_manager.py'):
    # Preserve the first approved baseline across reinstalls.
    target=baseline/name
    if not target.exists():shutil.copy2(APP/name,target)
    manifest[name]=hashlib.sha256(target.read_bytes()).hexdigest()
(baseline/'manifest.json').write_text(json.dumps(manifest,indent=2))
# Trusted offline AST regression test reads the sibling adapter, not production.
shutil.copy2(baseline/'firebase_store.py',ROOT/'firebase_store.py')
confdir=Path('/etc/easystock-guardian');confdir.mkdir(exist_ok=True,mode=0o700)
conf=confdir/'config.json'
if not conf.exists():conf.write_text(json.dumps({'enabled':True,'telegram_enabled':True,'max_jobs_per_day':2,'model':'gpt-5.6-luna'},indent=2))
conf.chmod(0o600)
units={
'easystock-guardian.service':f'''[Unit]
Description=EasyStock bounded health monitor
After=network-online.target
[Service]
Type=oneshot
ExecStart={PYTHON} {ROOT}/supervisor.py
TimeoutStartSec=120
UMask=0077
Nice=10
MemoryMax=180M
''',
'easystock-guardian.timer':'''[Unit]
Description=EasyStock health check every minute
[Timer]
OnBootSec=45
OnUnitActiveSec=60
AccuracySec=5
[Install]
WantedBy=timers.target
''',
'easystock-guardian-proxy.service':f'''[Unit]
Description=EasyStock credential-isolating Codex gateway
After=network-online.target
[Service]
ExecStart={PYTHON} {ROOT}/proxy.py
Restart=on-failure
RestartSec=10
UMask=0077
MemoryMax=140M
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths={STATE}
[Install]
WantedBy=multi-user.target
''',
'easystock-guardian-worker.service':f'''[Unit]
Description=EasyStock bounded recovery controller
After=easystock-guardian-proxy.service
Requires=easystock-guardian-proxy.service
[Service]
Type=oneshot
ExecStart={PYTHON} {ROOT}/worker.py
TimeoutStartSec=720
MemoryMax=180M
Nice=15
UMask=0077
''',
'easystock-codex@.service':f'''[Unit]
Description=Isolated EasyStock Codex incident %i
After=easystock-guardian-proxy.service
Requires=easystock-guardian-proxy.service
[Service]
User=easystock-codex
Group=easystock-codex
EnvironmentFile={STATE}/caps/%i.env
ExecStart=/usr/bin/python3 {ROOT}/run_agent.py %i
RuntimeMaxSec=450
TimeoutStopSec=10
KillMode=control-group
MemoryMax=360M
MemorySwapMax=512M
CPUQuota=50%
TasksMax=48
Nice=15
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/easystock-codex
InaccessiblePaths={STATE} /etc/easystock-guardian /run/dbus /run/systemd/private
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ProtectProc=invisible
RestrictSUIDSGID=yes
LockPersonality=yes
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
IPAddressDeny=any
IPAddressAllow=localhost
''',
'easystock-guardian-calendar.service':f'''[Unit]
Description=Refresh official TWSE guardian calendar
[Service]
Type=oneshot
ExecStart={PYTHON} {ROOT}/calendar_update.py
TimeoutStartSec=40
UMask=0077
''',
'easystock-guardian-calendar.timer':'''[Unit]
Description=Refresh TWSE calendar every morning
[Timer]
OnCalendar=*-*-* 08:10:00 Asia/Taipei
Persistent=true
[Install]
WantedBy=timers.target
'''}
for name,value in units.items():Path('/etc/systemd/system',name).write_text(value)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemd-analyze','verify',*[str(Path('/etc/systemd/system',n)) for n in units]],check=True)
subprocess.run([PYTHON,str(ROOT/'test_guardian.py')],check=True)
subprocess.run([PYTHON,str(ROOT/'test_open_price_update.py')],check=True)
subprocess.run([PYTHON,str(ROOT/'calendar_update.py')],check=True)
subprocess.run(['systemctl','enable','--now','easystock-guardian-proxy.service','easystock-guardian-calendar.timer'],check=True)
print('Installed. Monitor timer is intentionally not yet enabled: run smoke/isolation checks first.')
