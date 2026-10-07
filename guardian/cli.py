"""Observation-only CLI. Exit 0 means completed, not permission to trade."""
import argparse
import json
from pathlib import Path
from .scanner import load_policy, scan
from .report import output_directory, read_report, save_report, write_artifact


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path.cwd())
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('scan','diff','report','bundle'):
        p=sub.add_parser(name);p.add_argument('--output-dir',type=Path);p.add_argument('--json',action='store_true')
        if name in ('scan','diff'):p.add_argument('--strict',action='store_true')
        if name=='scan':p.add_argument('--notify',action='store_true')
        if name=='diff':p.add_argument('--base',required=True);p.add_argument('--head',default='HEAD')
    sub.add_parser('validate-policy')
    p=sub.add_parser('security-summary');p.add_argument('--input',type=Path,required=True);p.add_argument('--output-dir',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='validate-policy':
            policy,manifest=load_policy();print(json.dumps({'status':'VALID','rules':len(policy['rules']),'required_mirrors':len(manifest['byte_equivalent'])}));return 0
        directory=output_directory(args.repo,args.output_dir)
        if args.command=='diff' and args.output_dir is None:directory=directory/'diff'
        if args.command=='security-summary':
            from .ai_review import security_summary
            if args.input.stat().st_size>16*1024*1024 or args.input.is_symlink():raise ValueError('input_limit')
            write_artifact(args.repo,directory,'security-summary.json',security_summary(json.loads(args.input.read_text())))
            return 0
        previous=read_report(directory)
        if args.command=='scan':report=scan(args.repo,previous=previous)
        elif args.command=='diff':
            from .diff_review import review
            report=review(args.repo,args.base,args.head,previous)
        else:report=previous
        if report is None:
            print(json.dumps({'overall_status':'UNKNOWN','report_status':'NOT_AVAILABLE'}));return 2
        if args.command in ('scan','diff'):save_report(args.repo,directory,report)
        if args.command=='bundle':
            from .ai_review import bundle,PROMPT
            write_artifact(args.repo,directory,'review-bundle.json',bundle(args.repo,report,directory))
            write_artifact(args.repo,directory,'review-prompt.txt',PROMPT)
        if args.command=='scan' and args.notify:
            from .notify import notify
            report['notification']=notify(args.repo,directory,report)
        print(json.dumps(report,ensure_ascii=False) if args.json else json.dumps({k:report[k] for k in ('overall_status','counts','commit','review_required','changed_critical_files')}))
        if not report['scanner_complete']:return 2
        if getattr(args,'strict',False) and report['findings']:return 1
        return 0
    except Exception:
        print(json.dumps({'overall_status':'UNKNOWN','error_code':'GUARDIAN_OPERATION_UNAVAILABLE'}));return 2


if __name__=='__main__':raise SystemExit(main())
