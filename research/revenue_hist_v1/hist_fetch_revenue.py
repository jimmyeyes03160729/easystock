#!/usr/bin/env python3
"""REVENUE_HIST_V1: run the unchanged REVENUE_DRIFT_V1 fetcher for revenue months 2014-01..2021-12."""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'revenue_v1'))
import fetch_revenue as F  # noqa: E402

F.ROOT = Path(sys.argv[1])
F.FIRST_MONTH, F.LAST_MONTH = (2014, 1), (2021, 12)

if __name__ == '__main__':
    F.main()
