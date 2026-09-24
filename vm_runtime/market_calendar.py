#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Forwarding / compatibility wrapper for market_calendar in vm_runtime."""
from pathlib import Path
import sys

# Ensure root directory is in sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from market_calendar import (
    now_tpe,
    parse_date,
    fetch_twse_calendar,
    check_dgpa_typhoon_closure,
    get_extra_closed_dates,
    is_market_open,
    main,
)

if __name__ == "__main__":
    main()
