import datetime as dt
import json
import urllib.request
from common import STATE, now, write_json

def fetch(year):
    url = f'https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear={year-1911}'
    data = json.load(urllib.request.urlopen(url, timeout=25))
    if data.get('stat', '').lower() != 'ok' or not data.get('data'):
        raise ValueError('TWSE calendar unavailable')
    closed = []
    for row in data['data']:
        day = dt.date.fromisoformat(row[0])
        if day.year != year:
            raise ValueError('TWSE returned wrong year')
        # First/last trading days are informative entries, not holidays.
        if not any(x in row[1] for x in ('開始交易', '最後交易')):
            closed.append(day.isoformat())
    if len(closed) < 10:
        raise ValueError('Incomplete annual calendar')
    return {'year': year, 'closed': sorted(closed), 'source': url, 'updated_at': now().isoformat()}

if __name__ == '__main__':
    year = now().year
    write_json(STATE / f'calendar-{year}.json', fetch(year))
    print('calendar updated', year)
