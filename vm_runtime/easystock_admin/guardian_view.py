"""Owner-only projection of a private artifact; never starts a scan or a recovery."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from guardian.ai_review import redact
from guardian.models import safe_path,SEVERITIES
from guardian.report import read_report


def snapshot():
    empty={'overall_status':'UNKNOWN','report_status':'NOT_AVAILABLE','generated_at':None,'commit':None,
           'counts':{s.lower():0 for s in SEVERITIES},'findings':[],'resolved_findings':[],
           'review_required':False,'changed_critical_files':[],'blocking_condition':False,'enforcement':False}
    try:
        directory=Path(os.environ.get('GUARDIAN_REPORT_DIR') or '/home/ubuntu/easystock-architecture-guardian')
        report=read_report(directory)
        if report is None:return empty
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(report['generated_at'])).total_seconds()
        current=0<=age<=26*3600
        root=Path(__file__).resolve().parents[1]
        if root.name=='vm_runtime':root=root.parent
        release=root/'release-info.json'
        if release.is_file() and release.stat().st_size<20000:
            current=current and json.loads(release.read_text()).get('source_commit')==report['commit']
        def rows(items):
            result=[]
            for row in items[:100]:
                if row.get('severity') not in SEVERITIES:continue
                clean={k:redact(row.get(k,''))[:2000] for k in ('id','title','impact','recommendation','first_seen','last_seen','resolved_at','fingerprint')}
                clean.update(severity=row['severity'],blocks_live_auto=row.get('blocks_live_auto') is True)
                clean['evidence']=[{'path':safe_path(e.get('path','')),'line':e.get('line') if type(e.get('line')) is int else 0,'detail':redact(e.get('detail',''))[:500]} for e in row.get('evidence',[])[:5]]
                result.append(clean)
            return result
        findings=rows(report.get('findings',[]))
        counts={s.lower():int(report.get('counts',{}).get(s.lower(),0)) for s in SEVERITIES}
        if any(not 0<=n<=10000 for n in counts.values()):raise ValueError('counts')
        commit=report.get('commit')
        import re
        commit=commit if isinstance(commit,str) and re.fullmatch(r'[a-f0-9]{40,64}',commit) else 'UNKNOWN'
        return {**empty,'overall_status':report['overall_status'] if current else 'UNKNOWN',
                'report_status':'CURRENT' if current else 'STALE_OR_DIFFERENT_COMMIT','generated_at':report['generated_at'],
                'commit':commit,'counts':counts,'findings':findings,'resolved_findings':rows(report.get('resolved_findings',[])),
                'review_required':report.get('review_required') is True,'changed_critical_files':[safe_path(p) for p in report.get('changed_critical_files',[])[:100]],
                'blocking_condition':any(r['blocks_live_auto'] for r in findings)}
    except Exception:return {**empty,'report_status':'REPORT_UNAVAILABLE'}
