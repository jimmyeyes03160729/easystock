"""Copy only pre-holdout rows into a new private replay directory.

No source labels, future signals or future bars are selected. Source files are
opened read-only; neither SQLite backup nor a raw file copy is permitted here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

BEFORE = '2026-10-07'
SOURCE_ROOT = Path('/home/ubuntu/easystock-learning-data/rebound')


def copy_table(source, target, table, columns, date_column):
    schema = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if schema is None:
        raise ValueError(f'missing_source_table:{table}')
    target.execute(schema[0])
    projection = ','.join('NULL AS label' if c == 'label' else c for c in columns)
    query = f'SELECT {projection} FROM {table} WHERE {date_column}<? ORDER BY {date_column}'
    rows = source.execute(query, (BEFORE,))
    count = 0
    while batch := rows.fetchmany(5000):
        target.executemany(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', batch)
        count += len(batch)
    maximum = target.execute(f'SELECT MAX({date_column}) FROM {table}').fetchone()[0]
    if maximum and maximum >= BEFORE:
        raise AssertionError('snapshot_boundary_violation')
    return {'rows': count, 'latest': maximum}


def prepare(source_root: Path, output: Path) -> dict:
    source_root, output = source_root.resolve(), output.resolve()
    if output == source_root or source_root in output.parents:
        raise ValueError('audit_output_must_be_outside_source')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    specs = {
        'dataset-v2.sqlite': (
            ('candidates', ('id', 'strategy_version', 'feature_schema_version', 'signal_date', 'symbol', 'candidate_kind', 'snapshot', 'label'), 'signal_date'),
            ('trading_days', ('day',), 'day'),
        ),
        'market-daily.sqlite': (
            ('bars', ('symbol', 'day', 'exchange', 'open', 'high', 'low', 'close', 'volume', 'amount', 'reference'), 'day'),
            ('ex_rights', ('symbol', 'day', 'previous_close', 'reference'), 'day'),
            ('tpex_next_reference', ('symbol', 'day', 'reference'), 'day'),
        ),
    }
    manifest = {'before': BEFORE, 'labels_read': False, 'source_read_only': True, 'files': {}}
    for filename, tables in specs.items():
        source = sqlite3.connect((source_root / filename).as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(output / filename)
        try:
            # Pin a consistent source read transaction across all exported tables.
            source.execute('BEGIN')
            counts = {table: copy_table(source, target, table, columns, date_column)
                      for table, columns, date_column in tables}
            if filename == 'market-daily.sqlite':
                target.execute('CREATE INDEX bars_day ON bars(day)')
            else:
                target.execute('CREATE INDEX candidate_date ON candidates(signal_date)')
            target.commit()
        finally:
            source.close()
            target.close()
        digest = hashlib.sha256((output / filename).read_bytes()).hexdigest()
        manifest['files'][filename] = {'sha256': digest, 'tables': counts}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(SOURCE_ROOT, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
