"""Bounded read-only IPC subscription probe on the existing E.SUN socket.

Does not log in, start the intraday engine, enable dual mode, or place orders.
Only its own owner-tagged request is replaced during cleanup.
"""
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0,'/home/ubuntu/easystock')
from market_data.health import atomic,timestamp

DIRECTORY=Path('/home/ubuntu/easystock-market-data')
SYMBOLS=['2480','3231','3702','5483','6116','6505']


def inactive():
    return subprocess.run(['systemctl','is-active','--quiet','easystock-intraday.service'],stdout=subprocess.DEVNULL).returncode!=0


def read(name):
    p=DIRECTORY/name
    if p.stat().st_size>512*1024:raise ValueError('oversized_file')
    x=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(x,dict):raise ValueError('invalid_file')
    return x


def main(output):
    if output.exists():raise ValueError('refuse_existing_output')
    request=DIRECTORY/'b-books-request.json';owner='bounded-probe-'+str(uuid.uuid4())
    if not inactive():raise ValueError('intraday_active')
    if request.exists():
        old=read(request.name);at=timestamp(old.get('generated_at'))
        if at and 0 <= (datetime.now(timezone.utc)-at).total_seconds()<=15:raise ValueError('another_request_active')
    snapshots=[];stop=None;started=datetime.now(timezone.utc).isoformat();cleanup=False
    try:
        until=time.monotonic()+30
        while time.monotonic()<until:
            if not inactive():stop='intraday_became_active';break
            if request.exists() and snapshots and read(request.name).get('owner_id')!=owner:
                stop='request_owner_changed';break
            health=read('esun.json')
            if not all(health.get(k) is True for k in ['connected','authenticated','parser_ok']):
                stop='provider_not_healthy';break
            atomic(request,dict(schema_version=1,owner_id=owner,generated_at=datetime.now(timezone.utc).isoformat(),symbols=SYMBOLS,pinned=[]))
            books=read('esun-books.json');at=timestamp(books.get('generated_at'))
            if not at or not 0 <= (datetime.now(timezone.utc)-at).total_seconds()<=2:
                stop='collector_snapshot_stale';break
            states=books.get('states',{})
            snapshots.append(dict(at=datetime.now(timezone.utc).isoformat(),connected=books.get('connected'),
                index_subscriptions=health.get('subscription_count'),reconnect_count=health.get('reconnect_count'),
                acknowledged=sum(states.get(s)=='active' for s in SYMBOLS),book_rows=len(books.get('books',{}))))
            time.sleep(1)
    finally:
        if request.exists() and read(request.name).get('owner_id')==owner:
            atomic(request,dict(schema_version=1,owner_id=owner,generated_at=datetime.now(timezone.utc).isoformat(),symbols=[],pinned=[]))
            until=time.monotonic()+10
            while time.monotonic()<until:
                if not read('esun-books.json').get('states'):cleanup=True;break
                time.sleep(.5)
    report=dict(started_at=started,ended_at=datetime.now(timezone.utc).isoformat(),symbols=SYMBOLS,
        stop_reason=stop,snapshots=snapshots,cleanup_acknowledged=cleanup,provider='esun',
        probe_uses_existing_socket=True,new_login=False,intraday_started=False,dual_mode_enabled=False,
        live_gate_passed=False,execution_allowed=False,
        caveat='After-hours ACK/cancellation and collector health only, not fresh live books, quantity calibration or opening B1 coverage.')
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='snapshots'}),flush=True)
    print(json.dumps(dict(samples=len(snapshots),max_acks=max((x['acknowledged'] for x in snapshots),default=0),
        book_rows=max((x['book_rows'] for x in snapshots),default=0),reconnect_counts=sorted(set(x['reconnect_count'] for x in snapshots)))),flush=True)
    return 0 if stop is None and cleanup else 1


if __name__=='__main__':raise SystemExit(main(Path(sys.argv[1])))
