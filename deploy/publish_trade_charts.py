"""Publish cached same-day price charts only; no broker login or trading actions."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from firebase_store import FirebaseStore
from trade_chart_feed import publish_cached

if __name__ == '__main__':
    print('Cached trade charts:', publish_cached(FirebaseStore(), os.environ.get('LEARNING_DATA_DIR', '/home/ubuntu/easystock-learning-data')))
