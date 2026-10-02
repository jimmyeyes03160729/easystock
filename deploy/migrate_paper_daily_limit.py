#!/usr/bin/env python3
"""Probe an SQLite copy, or apply an additive migration with a verified backup."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import paper_ledger

TABLES=('paper_trade_fills','paper_trade_logs','paper_trade_positions','paper_trade_events')


def evidence(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('SQLite integrity check failed')
    result={}
    for table in TABLES:
        cols=[r[1] for r in db.execute(f'PRAGMA table_info({table})')]
        if not cols:
            result[table]={'columns':[],'rows':0,'digest':None}
            continue
        rows=[list(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
        result[table]={'columns':cols,'rows':len(rows),
            'digest':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}
    return result


def migrate_verified(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        before=evidence(db)
        paper_ledger.migrate(db)
        for table,value in before.items():
            if not value['columns']:
                continue
            columns=','.join('"'+c+'"' for c in value['columns'])
            rows=[list(r) for r in db.execute(f'SELECT {columns} FROM {table} ORDER BY rowid')]
            digest=hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
            if len(rows)!=value['rows'] or digest!=value['digest']:
                raise RuntimeError('Migration changed existing evidence: '+table)
        after=evidence(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {'integrity_before':'ok','integrity_after':'ok','existing_rows_unchanged':True,
        'before_counts':{k:v['rows'] for k,v in before.items()},
        'after_counts':{k:v['rows'] for k,v in after.items()},'semantics_version':paper_ledger.SEMANTICS}


def run(database, apply=False, backup_dir=None):
    database=Path(database).resolve()
    if not database.is_file():
        raise RuntimeError('Paper database missing; no empty replacement will be created')
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as src:
        cols={r[1] for r in src.execute('PRAGMA table_info(paper_trade_settings)')}
        row=src.execute('SELECT semantics_version FROM paper_trade_settings WHERE id=1').fetchone() if 'semantics_version' in cols else None
        before_version=row[0] if row and row[0] else 'legacy'
    if apply:
        backup_dir=Path(backup_dir or database.parent/'migration-backups')
        backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        backup=backup_dir/('daily-limit-before-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup)) as dst:
            src.backup(dst)
            evidence(dst)
        backup.chmod(0o600)
        with closing(sqlite3.connect(database,timeout=15)) as db:
            result=migrate_verified(db)
        result.update(applied=True,backup=str(backup),source_semantics_before=before_version,
                      source_semantics_after=paper_ledger.SEMANTICS)
        (backup.with_suffix('.json')).write_text(json.dumps(result,indent=2)+'\n')
        backup.with_suffix('.json').chmod(0o600)
        return result
    with tempfile.TemporaryDirectory(prefix='paper-limit-migration-') as folder:
        copy=Path(folder)/'state.sqlite'
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(copy)) as dst:
            src.backup(dst)
            result=migrate_verified(dst)
        return dict(result,applied=False,source_read_only=True,
                    source_semantics_before=before_version,source_semantics_after=before_version)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=Path('/home/ubuntu/easystock-admin/state.sqlite'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup-dir',type=Path)
    args=parser.parse_args()
    print(json.dumps(run(args.database,args.apply,args.backup_dir),ensure_ascii=False,indent=2))
