"""Run independently of the VM, e.g. GitHub Actions. Reads public health only."""
import datetime as dt
import json
import urllib.request

URL='https://easystock-c237a-default-rtdb.firebaseio.com/market_data/intraday_live/guardian_health.json'

def check(data, stamp=None):
    if not isinstance(data,dict):raise RuntimeError('Guardian heartbeat missing')
    stamp=stamp or dt.datetime.now(dt.timezone.utc)
    value=dt.datetime.fromisoformat(data['checked_at'].replace('Z','+00:00'))
    elapsed=(stamp-value).total_seconds()
    if elapsed < -60 or elapsed > 600:raise RuntimeError('VM guardian heartbeat stale: '+str(round(elapsed))+' seconds')
    if data.get('status')=='degraded':raise RuntimeError('Guardian reports degraded: '+','.join(data.get('issues',[])))
    print('Guardian reachable:',data['checked_at'],data['status'])

if __name__=='__main__':
    check(json.load(urllib.request.urlopen(URL,timeout=20)))
