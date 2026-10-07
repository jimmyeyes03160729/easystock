"""Independent after-hours research refresh; never touches live feeds."""
from __future__ import annotations

import json
from .audit import build_audit,write_audit
from .backfill import DEFAULT_SOURCE,load_archives,run,selected_days
from .labels import update_labels
from .schema import connect
from .market_daily import connect as market_connect
from .official import daily as official_daily, dataset_path


def main():
    days=selected_days(DEFAULT_SOURCE,None,None,5)
    if not days: raise RuntimeError('no_history_calendar_dates')
    histories=load_archives(DEFAULT_SOURCE,days)
    plan=json.loads((DEFAULT_SOURCE/'plan.json').read_text(encoding='utf-8'))
    with connect() as db:
        collected=run(db,histories,days,trading_days=plan['dates'],expected_symbols=len(plan['symbols']))
        labelled=update_labels(db)
        audit=build_audit(db)
    write_audit(audit)
    print(json.dumps({'collected':collected,'labels_updated':labelled,
                      'audit_critical':audit['data_quality']['critical_count']}))
    # v2 (official whole-market daily) runs after v1 is committed, so a v2
    # source outage never blocks the frozen v1 dataset.
    with market_connect() as market, connect(dataset_path()) as db2:
        v2=official_daily(market,db2)
    print(json.dumps({'v2':v2},ensure_ascii=False))
    if audit['data_quality']['critical_count'] or v2['audit_critical']:raise SystemExit(2)


if __name__=='__main__':main()
