"""Commit diff inspection, with no checkout, patch application or deployment."""
from .models import finding
from .scanner import load_policy, scan
from .source import git, revision


def review(root, base, head, previous=None):
    base, head = revision(root,base),revision(root,head)
    changed = set(filter(None,git(root,'diff','--name-only','--no-renames',base,head,'--').decode().splitlines()))
    report = scan(root,commit=head,scope=changed,changed=changed,previous=previous)
    policy,_ = load_policy()
    # Deliberately review modifications, not declare every strategy change a violation.
    sensitive = [p for p in changed if p.removeprefix('vm_runtime/') in ('strategy_engine.py','strategy_rules.py','market_risk.py','intraday_live.py','position_manager.py','easystock_admin/order_service.py','easystock_admin/live_console.py','daytrade_learning/model_runtime.py','daytrade_learning/champion.py','daytrade_learning/research.py','rebound_learning/model.py')]
    rows = report['findings'] + [finding(policy,'DIFF-001',p,1,'boundary-change') for p in sorted(sensitive)]
    from .models import build_report
    result=build_report(rows,head,previous,complete=report['scanner_complete'],scope=changed,changed=changed,policy=policy)
    result.update(base_commit=base,head_commit=head,changed_files=sorted(changed))
    return result
