#!/usr/bin/env python3
"""Fetch one forward revenue month into forward/revenue.sqlite (a copy of the sealed backtest database plus the new month)."""
import shutil, sqlite3, sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fetch_revenue as FR  # noqa: E402

month = sys.argv[1]
fwd = ROOT / 'forward'
fwd.mkdir(exist_ok=True)
if not (fwd / 'revenue.sqlite').exists():
    shutil.copy(ROOT / 'data' / 'revenue.sqlite', fwd / 'revenue.sqlite')
y, m = map(int, month.split('-'))
db = sqlite3.connect(fwd / 'revenue.sqlite')
db.execute('DELETE FROM revenue WHERE month = ?', (month,))
db.execute('DELETE FROM pages WHERE month = ?', (month,))
db.commit()
db.close()
FR.ROOT = fwd
FR.FIRST_MONTH = FR.LAST_MONTH = (y, m)
FR.main()
