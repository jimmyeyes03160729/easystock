#!/usr/bin/env python3
"""Compatibility entry point for the verified Oracle VM premarket implementation."""
from pathlib import Path
import runpy
import sys


def main():
    runtime = Path(__file__).resolve().parent / 'vm_runtime'
    # Keep .env at the caller's existing project root; credentials are never copied.
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit('Install the Linux VM dependencies: pip install -r vm_runtime/requirements.txt') from None
    load_dotenv(Path(__file__).resolve().with_name('.env'))
    sys.path.insert(0, str(runtime))
    runpy.run_path(str(runtime / 'premarket_ai.py'), run_name='__main__')


if __name__ == '__main__':
    main()
