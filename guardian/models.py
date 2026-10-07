"""Controlled evidence, deterministic identity and report lifecycle."""
import hashlib
import json
import re
from fnmatch import fnmatch
from datetime import datetime, timezone

SEVERITIES = ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_path(path):
    path = str(path).replace('\\', '/')
    if not re.fullmatch(r'[A-Za-z0-9_./-]{1,240}', path) or path.startswith('/') or '..' in path.split('/'):
        return '[redacted-path]'
    return path


def finding(policy, rule, path, line, anchor, detail=None, other=None):
    spec = policy['rules'][rule]
    path = safe_path(path)
    fingerprint = hashlib.sha256(json.dumps([rule, path, anchor], sort_keys=True).encode()).hexdigest()
    evidence = [{'path': path, 'line': int(line), 'detail': detail or spec['evidence']}]
    if other:
        evidence.append({'path': safe_path(other[0]), 'line': int(other[1]), 'detail': spec['evidence']})
    return {'id': rule, 'severity': spec['severity'], 'category': spec['category'],
            'title': spec['title'], 'evidence': evidence, 'impact': spec['impact'],
            'recommendation': spec['recommendation'], 'blocks_live_auto': spec['blocks_live_auto'],
            'fingerprint': fingerprint}


def build_report(findings, commit, previous=None, *, complete=True, scope=None, changed=(), policy=None, at=None):
    at = at or now()
    previous = previous or {}
    history = {row['fingerprint']: dict(row) for row in previous.get('history', [])}
    # Support migration from reports without the explicit history array.
    history.update({row['fingerprint']: dict(row) for row in previous.get('findings', []) if row['fingerprint'] not in history})
    active = {row['fingerprint']: dict(row) for row in findings}
    for fp, row in active.items():
        row.update(first_seen=history.get(fp, {}).get('first_seen', at), last_seen=at, state='ACTIVE')
        history[fp] = row
    if complete:
        for fp, row in history.items():
            if fp not in active and row.get('state') != 'RESOLVED' and (scope is None or any(e['path'] in scope for e in row.get('evidence', []))):
                row.update(state='RESOLVED', resolved_at=at)
    counts = {level.lower(): sum(r['severity'] == level for r in active.values()) for level in SEVERITIES}
    status = 'UNKNOWN' if not complete else 'DANGER' if counts['critical'] else 'REVIEW' if active else 'SAFE'
    critical = [p for p in changed if policy and any(fnmatch(p, pattern) for pattern in policy['critical_paths'])]
    return {'schema_version': 1, 'generated_at': at, 'commit': commit, 'overall_status': status,
            'counts': counts, 'findings': sorted(active.values(), key=lambda r: (SEVERITIES.index(r['severity']), r['fingerprint'])),
            'history': sorted(history.values(), key=lambda r: r['fingerprint']),
            'resolved_findings': sorted((r for r in history.values() if r.get('state') == 'RESOLVED'), key=lambda r: r['fingerprint']),
            'review_required': bool(critical), 'changed_critical_files': sorted(map(safe_path, critical)),
            'scope': 'full' if scope is None else 'diff', 'scanner_complete': complete,
            'limitations': ['Static review is not a proof of all execution paths, absence of leakage, or LIVE readiness. No enforcement or auto-fix.']}
