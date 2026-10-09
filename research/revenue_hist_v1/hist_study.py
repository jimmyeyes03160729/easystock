#!/usr/bin/env python3
"""REVENUE_HIST_V1 study: the frozen REVENUE_DRIFT_V1 code on event months 2015-01..2021-12.

Only constants are rebound; every rule comes from research/revenue_v1/rev_study.py. Fold majorities follow the
preregistration (>= 5 of the 7 full years 2015-2021).
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'revenue_v1'))
import rev_study as R  # noqa: E402

BASE = Path('/home/ubuntu/easystock-research/revenue_hist_v1')
FULL_FOLDS = (2015, 2016, 2017, 2018, 2019, 2020, 2021)
PRIMARY = 'S2_SUR|H20'


def configure(base=BASE):
    R.CUTOFF = '2022-03-31'
    R.DAILY_DB = str(base / 'daily' / 'market-daily.sqlite')
    R.REV_DB = base / 'data' / 'revenue.sqlite'
    R.OUT = base / 'output'
    R.FIRST_EVENT, R.LAST_EVENT = '2015-01', '2021-12'
    R.FOLDS = FULL_FOLDS + (2022,)
    parent = R.criteria

    def criteria(months):
        c, st = parent(months)
        f = st['folds']
        c['B'] = sum(1 for y in FULL_FOLDS if f[y]['top'] is not None and f[y]['top'] > 0) >= 5
        c['D'] = sum(1 for y in FULL_FOLDS if f[y]['excess'] is not None and f[y]['excess'] > 0) >= 5
        return c, st

    R.criteria = criteria


def verdict(classification):
    return {'STRONG': 'REPLICATED', 'RELATIVE_ONLY': 'PARTIAL'}.get(classification, 'NOT_REPLICATED')


def main():
    configure()
    R.main()
    decision = json.loads((R.OUT / 'REVENUE_DRIFT_DECISION.json').read_text())
    lines = []
    for key, v in decision['results'].items():
        top = v['stats']['mean_top_net_pct'] or 0
        lines.append('PER_1M %s top_net=%+.3f%% -> %+.0f TWD per 1,000,000 of buys per holding period' % (key, top, top * 10000))
    p = decision['results'][PRIMARY]['classification']
    lines.append('REPLICATION %s primary=%s classification=%s' % (verdict(p), PRIMARY, p))
    with open(R.OUT / 'FINAL_LINES.txt', 'a') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
