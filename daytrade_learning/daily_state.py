"""Pure date checks shared by startup and offline tests."""
from datetime import datetime,timezone,timedelta
TPE=timezone(timedelta(hours=8))


def rows(value):
    if isinstance(value,dict):return list(value.values())
    if isinstance(value,list):return value
    return []


def on_day(row, day):
    try:
        t=datetime.fromisoformat(str(row['entry_time']).replace('Z','+00:00'))
        if t.tzinfo is None:t=t.replace(tzinfo=TPE)
        return t.astimezone(TPE).date().isoformat()==day
    except (KeyError,ValueError,TypeError):return False


def prepare_rollover(old, payload):
    old=old or {}
    day=payload['scan_date']
    if any(not on_day(r,day) for r in rows(old.get('open_positions'))):
        raise RuntimeError('Previous-day or undated OPEN records require reconciliation; nothing cleared')
    if old.get('scan_date')==day:
        return {**old,**payload}
    result=dict(payload)
    result['open_positions']=old.get('open_positions') or {}
    closed=old.get('closed_trades') or {}
    if isinstance(closed,dict):
        result['closed_trades']={k:r for k,r in closed.items() if on_day(r,day)}
    else:
        result['closed_trades']={str(i):r for i,r in enumerate(rows(closed)) if on_day(r,day)}
    return result
