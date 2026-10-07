"""Read-only scan orchestration and validated machine-readable policy."""
import json
import re
from pathlib import Path
from .models import SEVERITIES, build_report, finding
from .rules import architecture, inspect_file
from .source import read_sources, revision, git

PACKAGE = Path(__file__).parent


def load_policy(path=None):
    # JSON is a YAML 1.2 subset; no unsafe YAML constructor or extra runtime dependency.
    path = Path(path) if path else PACKAGE / 'policy.yaml'
    policy = json.loads(path.read_text(encoding='utf-8'))
    required = ('rules','critical_paths','forbidden_dependencies','mirror_manifest','sensitive_patterns','live_guards','holdout_protections','public_exposure_rules')
    if policy.get('schema_version') != 1 or any(k not in policy for k in required) or policy.get('capabilities') != ['SCAN','ANALYZE','REPORT','NOTIFY']:
        raise ValueError('invalid_guardian_policy')
    for rule, spec in policy['rules'].items():
        if not re.fullmatch(r'[A-Z]+-[0-9]{3}',rule) or spec.get('severity') not in SEVERITIES or type(spec.get('blocks_live_auto')) is not bool:
            raise ValueError('invalid_guardian_rule')
    if Path(policy['mirror_manifest']).name != policy['mirror_manifest']:
        raise ValueError('invalid_manifest_path')
    manifest = json.loads((path.parent / policy['mirror_manifest']).read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('invalid_manifest')
    classified = [*manifest['byte_equivalent'],*manifest['allowed_different'],*manifest['runtime_only']]
    if len(classified) != len(set(classified)) or any(Path(p).is_absolute() or '..' in Path(p).parts for p in classified):
        raise ValueError('invalid_manifest_entries')
    for pattern in [*policy['sensitive_patterns']['tokens'],policy['sensitive_patterns']['placeholder'],policy['sensitive_patterns']['key_names'],policy['public_exposure_rules']['private_infrastructure']]:
        re.compile(pattern)
    return policy, manifest


def scan_files(files, policy, manifest, scope=None):
    findings, parsed = [], {}
    for path, raw in files.items():
        if scope is not None and path not in scope:
            continue
        # Byte-identical manifested mirrors are one implementation, not two violations.
        if path.startswith('vm_runtime/') and path[11:] in manifest['byte_equivalent'] and files.get(path[11:]) == raw:
            continue
        rows, structure = inspect_file(path, raw, policy)
        findings.extend(rows)
        if structure: parsed[path] = structure
    findings.extend(architecture(files, parsed, manifest, policy, scope))
    return findings


def scan(root, *, policy_path=None, previous=None, commit=None, scope=None, changed=(), at=None):
    policy = None
    try:
        policy, manifest = load_policy(policy_path)
        head = revision(root, commit or 'HEAD')
        if not changed and scope is None:
            parents=git(root,'rev-parse',head+'^@').decode().splitlines()
            if parents:
                changed=git(root,'diff','--name-only','--no-renames',parents[0],head,'--').decode().splitlines()
        working_changes=[] if commit else git(root,'diff','--name-only','--no-renames','HEAD','--').decode().splitlines()
        changed=sorted(set(changed)|set(working_changes))
        files = read_sources(root, head if commit else None)
        findings = scan_files(files, policy, manifest, scope)
        baseline = json.loads((Path(policy_path).parent if policy_path else PACKAGE).joinpath('guardian-baseline.json').read_text(encoding='utf-8'))
        accepted = {r['fingerprint'] for r in baseline.get('accepted', []) if isinstance(r,dict) and r.get('reason')}
        for row in findings:
            if row['fingerprint'] in accepted:
                row['baseline_accepted'] = row['severity'] in policy['baseline_allowed']
                if not row['baseline_accepted']:row['baseline_rejected'] = True
        # Even accepted Medium/Low remain visible and REVIEW; baseline cannot manufacture SAFE.
        report=build_report(findings,head,previous,scope=scope,changed=changed,policy=policy,at=at)
        report['source_state']='WORKTREE_CHANGED' if working_changes else 'COMMIT_TREE'
        return report
    except Exception:
        # No stack trace, source text, arbitrary filename, or exception detail in reports.
        fallback = policy or {'rules':{'SCAN-001':{'severity':'HIGH','category':'DEPLOYMENT_INTEGRITY','title':'Scanner could not complete','impact':'Incomplete inspection is not safety evidence.','recommendation':'Review scanner configuration privately.','evidence':'Scan incomplete; exception details omitted.','blocks_live_auto':True}},'critical_paths':[]}
        row = finding(fallback,'SCAN-001','guardian/scanner.py',1,'scan-incomplete')
        return build_report([row],'UNKNOWN',previous,complete=False,scope=scope,changed=changed,policy=fallback,at=at)
