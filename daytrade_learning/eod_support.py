"""Bounded AI requests and stable cache keys; caller holds the existing EOD file lock."""
import hashlib
import json
import os
from pathlib import Path
from .research import save


def read_report(path):
    try:
        value=json.loads(Path(path).read_text())
        return value if isinstance(value,dict) else {}
    except FileNotFoundError:return {}
    # Corrupt data must not silently reset a request budget or overwrite a prior report.


def ai_input(report):
    result={k:v for k,v in report.items() if k not in ('ai','ai_cache','previous_ai','collection','status')}
    result['status']='ready' if result.get('sample_count') else 'no_live_samples'
    c=report.get('collection')
    if c is not None:
        result['collection']={k:c.get(k) for k in ('requested','downloaded','failed','scanner_errors','omitted_by_cap','scope')}
    return result


def report_status(report):
    c=report.get('collection',{})
    if c and not c.get('downloaded'):return 'failed'
    if c.get('failed') or c.get('scanner_errors') or report.get('ai',{}).get('status') in ('failed','skipped'):
        return 'partial'
    return 'ready' if report.get('sample_count') else 'no_live_samples'


def review_once(data,day,report,previous,reviewer,reset=False):
    payload=ai_input(report);model=os.getenv('GEMINI_REVIEW_MODEL','')
    key=hashlib.sha256(json.dumps({'input':payload,'model':model,'cache_version':1},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path=Path(data)/'ai'/('stable-'+day+'-'+key+'.json')
    record=read_report(path)
    if record.get('result',{}).get('status')=='ok':return record['result'],{'source':'cache','attempts':record.get('attempts',0)}
    old=previous.get('ai',{})
    if old.get('status')=='ok' and old.get('model')==model and ai_input(previous)==payload:
        save(path,{'result':old,'attempts':0,'source':'previous_report'})
        return old,{'source':'previous_report','attempts':0}
    attempts=0 if reset else int(record.get('attempts',0))
    if attempts>=2:
        return {'status':'failed','reason':'ai_attempt_limit','model':model},{'source':'attempt_limit','attempts':attempts}
    # Charge the attempt before the request, so a killed job cannot request indefinitely.
    attempts+=1
    save(path,{'attempts':attempts,'result':{'status':'failed','reason':'request_not_completed'}})
    try:answer=reviewer(payload)
    except Exception as exc:answer={'status':'failed','error_type':type(exc).__name__}
    save(path,{'attempts':attempts,'result':answer})
    return answer,{'source':'request','attempts':attempts}
