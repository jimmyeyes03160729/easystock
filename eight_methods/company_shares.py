"""Public official common-share metadata; never infer shares from par value."""
from datetime import datetime,timezone,timedelta
import json
import re
from pathlib import Path
import urllib.request

TPE=timezone(timedelta(hours=8))
SOURCES={'TWSE':'https://openapi.twse.com.tw/v1/opendata/t187ap03_L',
         'TPEX':'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'}


def source_day(value):
    value=str(value).replace('-','').replace('/','')
    if re.fullmatch(r'\d{7}',value):value=str(int(value[:3])+1911)+value[3:]
    if not re.fullmatch(r'\d{8}',value):raise ValueError('invalid_source_date')
    return datetime.strptime(value,'%Y%m%d').date().isoformat()


def normalize(rows,exchange,received):
    out={}
    for r in rows:
        code=str(r.get('公司代號') if exchange=='TWSE' else r.get('SecuritiesCompanyCode'))
        raw=r.get('已發行普通股數或TDR原股發行股數') if exchange=='TWSE' else r.get('IssueShares')
        try:
            shares=int(str(raw).replace(',',''));day=source_day(r.get('出表日期') if exchange=='TWSE' else r.get('Date'))
            if not re.fullmatch(r'[1-9]\d{3}',code) or shares<=0 or day>received[:10]:continue
        except (ValueError,TypeError):continue
        out[code]={'issued_common_shares':shares,'exchange':exchange,'asof_day':day,
                   'received_at':received,'source':SOURCES[exchange]}
    return out


def refresh(path):
    now=datetime.now(TPE).isoformat();rows={};errors={}
    for exchange,url in SOURCES.items():
        try:
            with urllib.request.urlopen(url,timeout=20) as response:payload=json.load(response)
            rows.update(normalize(payload,exchange,now))
        except Exception as exc:errors[exchange]=type(exc).__name__
    # Never destroy a usable cache because both sources failed.
    if not rows:raise RuntimeError('No official issued-share metadata; '+str(errors))
    value={'schema_version':1,'generated_at':now,'rows':rows,'errors':errors}
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)
    return {'symbols':len(rows),'errors':errors}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default='/home/ubuntu/easystock-eight-methods/company-shares.json');a=p.parse_args()
    print(json.dumps(refresh(a.output)))
