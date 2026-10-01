"""Read-only summary for operations; no model or feed side effects."""
from __future__ import annotations

import json
from .schema import connect


def status():
    with connect() as db:
        return {'candidates':db.execute('SELECT COUNT(*) FROM candidates').fetchone()[0],
                'scan_days':db.execute('SELECT COUNT(*) FROM scan_days').fetchone()[0],
                'daily_bars':db.execute('SELECT COUNT(*) FROM daily_bars').fetchone()[0]}


if __name__=='__main__': print(json.dumps(status()))
