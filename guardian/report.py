"""Private report artifacts only. Never write repository or protected runtime data."""
import json
import os
from pathlib import Path
from .models import SEVERITIES
from .scanner import load_policy

MAX_REPORT = 4 * 1024 * 1024


def output_directory(root, output=None):
    directory = Path(output or os.environ.get('GUARDIAN_REPORT_DIR') or Path.home()/'.local/state/easystock-architecture-guardian').resolve()
    root = Path(root).resolve()
    if directory == root or directory.is_relative_to(root):
        raise ValueError('report_output_must_be_outside_repository')
    policy, _ = load_policy()
    for protected in policy['protected_output_prefixes']:
        protected_path=Path(protected).resolve()
        if directory == protected_path or directory.is_relative_to(protected_path):
            raise ValueError('protected_output_destination')
    # No symlink artifact directory or symlink overwrite. Private state is separate from old ops Guardian.
    original=Path(output or os.environ.get('GUARDIAN_REPORT_DIR') or directory).absolute()
    for parent in [original,*original.parents,*directory.parents]:
        if parent.is_symlink():raise ValueError('symlink_output_destination')
    return directory


def read_report(directory):
    path = Path(directory)/'guardian-report.json'
    if not path.exists():return None
    if path.is_symlink() or path.stat().st_size>MAX_REPORT:raise ValueError('invalid_report_file')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 1 or value.get('overall_status') not in ('SAFE','REVIEW','DANGER','UNKNOWN'):
        raise ValueError('invalid_report_schema')
    return value


def markdown(report):
    lines=['# Architecture Guardian', '', 'Observation only: no live enforcement, fix, promotion or deployment.', '',
           f"Status: {report['overall_status']} · commit: {report['commit']} · checked: {report['generated_at']}", '',
           ' | '.join(f'{s}: {report["counts"][s.lower()]}' for s in SEVERITIES), '',
           'Changed critical files: '+', '.join(report['changed_critical_files']), '']
    for row in report['findings']:
        lines += [f"## {row['id']} — {row['severity']}: {row['title']}", '',
                  'LIVE AUTO: '+('GUARDIAN BLOCKING CONDITION (advisory only)' if row['blocks_live_auto'] else 'Review only'), '',
                  row['impact'], '', row['recommendation'], '']
        lines += [f"- {e['path']}:{e['line']} — {e['detail']}" for e in row['evidence']]
        lines += ['', f"Fingerprint: {row['fingerprint']} · first: {row['first_seen']} · last: {row['last_seen']}", '']
    lines += ['## Resolved history', '']
    lines += [f"- {r['id']} {r['fingerprint']} resolved {r.get('resolved_at')}" for r in report.get('resolved_findings',[])]
    lines += ['', '## Limits', '', *report['limitations'], '']
    return '\n'.join(lines)


def write_artifact(root, directory, name, value):
    directory = output_directory(root, directory)
    if name not in ('guardian-report.json','guardian-report.md','review-bundle.json','review-prompt.txt','ai-review.json','security-summary.json','notification-state.json','test-status.json'):
        raise ValueError('unknown_artifact_name')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory.chmod(0o700)
    target = directory/name
    if target.is_symlink():raise ValueError('symlink_report_file')
    raw = value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)
    if len(raw.encode())>MAX_REPORT:raise ValueError('report_size_limit')
    temp = directory/(name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
        target.chmod(0o600)
    finally:
        if temp.exists():temp.unlink()


def save_report(root, directory, report):
    write_artifact(root,directory,'guardian-report.json',report)
    write_artifact(root,directory,'guardian-report.md',markdown(report))
