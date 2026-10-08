#!/usr/bin/env python3
"""Readiness gate: file existence only. Exit 0 when >= 80% of pool stock-days in the test windows are archived."""
import sys
import hv60_common as H

cov, days, pool = H.coverage()
H.log({'at': H.now(), 'coverage': round(cov, 4), 'test_window_days': days, 'pool': pool, 'gate': H.GATE_MIN})
sys.exit(0 if cov >= H.GATE_MIN else 1)
