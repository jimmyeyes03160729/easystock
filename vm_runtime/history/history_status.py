#!/usr/bin/env python3
"""Publish allowlisted offline history progress; never publish paths, PIDs or models."""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sys

HISTORY=Path('/home/ubuntu/easystock-history-pilot-output')
ARCHIVE=Path('/home/ubuntu/easystock-history-expanded-data')
LIVE=Path('/home/ubuntu/easystock')
ACTIVE={'snapshotting','replaying','training'}


def read(path,errors,code):
    try:
        if path.stat().st_size>5*1024*1024:raise ValueError('too_large')
        value=json.loads(path.read_text())
        if not isinstance(value,dict):raise ValueError('not_object')
        return value
    except FileNotFoundError:return {}
    except (OSError,ValueError):errors.append(code);return {}


def count(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None


def number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def running(root):
    try:
        with (root/'run.lock').open('r') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);return False
            except BlockingIOError:return True
    except FileNotFoundError:return False
    except OSError:return None


def metric(obj):
    if not isinstance(obj,dict):return None
    rate=number(obj.get('positive_markout_rate'))
    return {'samples':count(obj.get('samples')),
            'positive_markout_rate':rate if rate is not None and 0<=rate<=1 else None,
            'mean_net_markout_pct':number(obj.get('mean_net_markout_pct'))}


def compute(history,archive,now,is_running,engine_known=False):
    errors=[];s=read(history/'status.json',errors,'status_unreadable')
    a=read(archive/'progress.json',errors,'archive_unreadable')
    run_id=s.get('run_id','');valid_id=isinstance(run_id,str) and bool(re.fullmatch(r'\d{8}T\d{12}Z',run_id))
    started=None
    if valid_id:
        try:started=datetime.strptime(run_id,'%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc).isoformat()
        except ValueError:valid_id=False
    phase=s.get('state','not_started')
    if phase not in ACTIVE|{'completed','failed','interrupted','not_started'}:phase='unknown'
    if is_running is None:phase='unknown'
    elif phase in ACTIVE and not is_running:phase='interrupted'
    elif is_running and phase not in ACTIVE:phase='unknown'
    training={};report={}
    if phase=='completed' and valid_id:
        expected=history/'runs'/run_id/'report.json'
        # Reject status pointers outside this exact run; never follow arbitrary paths.
        if s.get('report')!=str(expected):errors.append('report_identity_mismatch')
        else:
            report=read(expected,errors,'report_unreadable')
            if report.get('version')!='quote-markout-pilot-1' or report.get('deployment_allowed') is not False:
                errors.append('unrecognized_report');report={}
            if not report:errors.append('report_missing_or_invalid')
    t=report.get('training',{})
    if not isinstance(t,dict):t={};errors.append('training_unreadable')
    training_status=t.get('status')
    if training_status not in ('blocked','experimental_candidate'):training_status=None
    reason=t.get('reason','')
    reason_code='other'
    if isinstance(reason,str):
        if reason.startswith('Need 26'):reason_code='insufficient_dates'
        elif reason.startswith('Need 200'):reason_code='insufficient_samples'
        elif 'scikit-learn' in reason:reason_code='dependency_missing'
    training={'status':training_status,'reason_code':reason_code if training_status=='blocked' else None,
              'test_samples':count(t.get('test_samples')),
              'model_selected':metric(t.get('model_selected')),'all_windows':metric(t.get('all_windows'))}
    run={'state':phase,'started_at':started,
         'processed_files':count(s.get('processed_files')),'archive_files':count(s.get('archive_files')),
         'labeled_samples':count(s.get('labeled_samples')),
         'labeled_dates':count(report.get('labeled_dates'))}
    return {'schema_version':1,'updated_at':now.isoformat(),'run':run,'training':training,
            'archive':{**{k:count(a.get(k)) for k in ('archived_stock_days','target_stock_days','failed_stock_days')},
                       'stop_reason':a.get('stop_reason') if a.get('stop_reason') in ('quota_exhausted','quota_reserve','pair_limit','run_budget','pair_failed_inspect_before_retry','pair_limit_or_plan_complete','downloading','outside_window','disk_reserve','user_stopped','transient_error','available_range_scanned_with_gaps','credentials_missing') else 'error' if str(a.get('stop_reason','')).startswith('error_') else None,
                       'requested_start':'2010-01-01','available_start':'2020-03-02',
                       'planned_start':a.get('planned_start') if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(a.get('planned_start',''))) else None,
                       'review_required_stock_days':count(a.get('review_required_stock_days')),
                       'schedule':'每日 14:00–22:00（台北）', 'training_schedule':'每日 22:10（台北）'},
            'model_application':{'status':'not_applied' if engine_known else 'unknown','basis':'reviewed_live_engine_hash'},
            'data_errors':sorted(set(errors))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    known=json.loads(Path('/home/ubuntu/easystock-history-status-r1/reviewed_engine.json').read_text())
    try:matched=hashlib.sha256((LIVE/'intraday_live.py').read_bytes()).hexdigest() in known
    except OSError:matched=False
    result=compute(HISTORY,ARCHIVE,datetime.now(timezone.utc),running(HISTORY),matched)
    if args.publish:
        sys.path.insert(0,str(LIVE))
        from firebase_store import FirebaseStore
        FirebaseStore().root.child('history_training_status').set(result)
        print('History summary published:',result['run']['state'])
    else:print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
