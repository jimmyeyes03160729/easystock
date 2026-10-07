#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load the root calendar without importing this wrapper under the same name."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / 'market_calendar.py'
_spec = importlib.util.spec_from_file_location('easystock_root_market_calendar', _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

CalendarUnavailable = _module.CalendarUnavailable
now_tpe = _module.now_tpe
parse_date = _module.parse_date
fetch_twse_calendar = _module.fetch_twse_calendar
check_dgpa_typhoon_closure = _module.check_dgpa_typhoon_closure
get_extra_closed_dates = _module.get_extra_closed_dates
is_market_open = _module.is_market_open
main = _module.main

if __name__ == "__main__":
    main()
