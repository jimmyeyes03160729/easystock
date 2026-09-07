#!/usr/bin/env python3
"""One-time/resumable Fugle historical K-line backfill for EasyStock.

Reads symbols from Firebase /market_data/summary, fetches daily candles from
Fugle historical API, and stores the latest 250 bars under /market_data/kline.
Already-complete symbols are skipped, so the job can safely be re-run.
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import date, timedelta
from typing import Any

import firebase_admin
import requests
from firebase_admin import credentials, db

FIREBASE_DATABASE_URL = os.environ.get("FIREBASE_DATABASE_URL", "").strip().rstrip("/")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
FIREBASE_ROOT_PATH = os.environ.get("FIREBASE_ROOT_PATH", "market_data").strip().strip("/") or "market_data"
FUGLE_API_KEY = os.environ.get("FUGLE_API_KEY", "").strip()

TARGET_BARS = max(60, int(os.environ.get("BACKFILL_TARGET_BARS", "250")))
MIN_EXISTING_BARS = max(1, int(os.environ.get("BACKFILL_MIN_EXISTING_BARS", "220")))
MAX_SYMBOLS = max(1, int(os.environ.get("BACKFILL_MAX_SYMBOLS", "500")))
HTTP_TIMEOUT = max(5.0, float(os.environ.get("HTTP_TIMEOUT", "12")))
FUGLE_MIN_INTERVAL_SECONDS = max(1.02, float(os.environ.get("FUGLE_MIN_INTERVAL_SECONDS", "1.10")))
MAX_RETRIES = max(1, int(os.environ.get("FUGLE_MAX_RETRIES", "4")))

FUGLE_HISTORY_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}"
USER_AGENT = "Mozilla/5.0 (compatible; easystock/0.63-fugle-backfill; +https://github.com/jimmyeyes03160729/easystock)"
_last_fugle_call = 0.0


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_kline(rows: list[dict] | None) -> list[dict]:
    by_day: dict[str, dict] = {}
    for row in rows or []:
        day = str(row.get("time") or row.get("date") or "")[:10]
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        if not day or None in (o, h, l, c):
            continue
        v = safe_int(row.get("volume"))
        amount = safe_float(row.get("amount") if "amount" in row else row.get("turnover"))
        if amount is None and v is not None:
            amount = c * v
        by_day[day] = {
            "time": day,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": v,
            "amount": round(amount, 2) if amount is not None else None,
        }
    return [by_day[k] for k in sorted(by_day)][-TARGET_BARS:]


def init_firebase() -> None:
    if not FIREBASE_DATABASE_URL:
        raise RuntimeError("Missing FIREBASE_DATABASE_URL")
    if not FIREBASE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing FIREBASE_SERVICE_ACCOUNT_JSON")
    if not FUGLE_API_KEY:
        raise RuntimeError("Missing FUGLE_API_KEY")

    payload = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(payload),
            {"databaseURL": FIREBASE_DATABASE_URL},
        )


def wait_for_rate_limit() -> None:
    global _last_fugle_call
    elapsed = time.monotonic() - _last_fugle_call
    if elapsed < FUGLE_MIN_INTERVAL_SECONDS:
        time.sleep(FUGLE_MIN_INTERVAL_SECONDS - elapsed)
    _last_fugle_call = time.monotonic()


def fetch_fugle_history(session: requests.Session, symbol: str) -> list[dict]:
    # Fugle requires a query range strictly shorter than one year.
    end_date = date.today()
    start_date = end_date - timedelta(days=364)
    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timeframe": "D",
        # Keep raw prices so the historical series matches the official daily
        # bars appended by update_market.py after the backfill.
        "adjusted": "false",
        "fields": "open,high,low,close,volume,turnover",
        "sort": "asc",
    }
    headers = {"X-API-KEY": FUGLE_API_KEY, "User-Agent": USER_AGENT}

    for attempt in range(1, MAX_RETRIES + 1):
        wait_for_rate_limit()
        try:
            response = session.get(
                FUGLE_HISTORY_URL.format(symbol=symbol),
                params=params,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                print(f"[WARN] {symbol}: network error after {attempt} attempts: {exc}")
                return []
            time.sleep(min(8.0, 1.5 * attempt + random.random()))
            continue

        if response.status_code == 200:
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else []
            return normalize_kline(rows or [])

        if response.status_code == 404:
            print(f"[WARN] {symbol}: Fugle returned 404 (no history in requested range)")
            return []

        if response.status_code == 429:
            retry_after = safe_float(response.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else min(15.0, 3.0 * attempt)
            print(f"[RATE] {symbol}: 429, retrying after {delay:.1f}s")
            time.sleep(delay)
            continue

        if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
            time.sleep(min(8.0, 1.5 * attempt + random.random()))
            continue

        body = response.text[:180].replace("\n", " ")
        print(f"[WARN] {symbol}: HTTP {response.status_code}: {body}")
        return []

    return []


def symbol_order(summary: dict[str, dict]) -> list[str]:
    def key(item: tuple[str, dict]) -> tuple[int, str]:
        sym, data = item
        try:
            rank = int((data or {}).get("hot_rank") or (data or {}).get("rank") or 999999)
        except (TypeError, ValueError):
            rank = 999999
        return rank, sym

    return [sym for sym, _ in sorted(summary.items(), key=key)][:MAX_SYMBOLS]


def main() -> None:
    init_firebase()
    root = db.reference(f"/{FIREBASE_ROOT_PATH}")
    summary = root.child("summary").get() or {}
    if not isinstance(summary, dict) or not summary:
        raise RuntimeError(f"Firebase /{FIREBASE_ROOT_PATH}/summary is empty; run Daily Stock Data Update first")

    symbols = symbol_order(summary)
    print(f"Fugle backfill start: {len(symbols)} symbols, target {TARGET_BARS} bars, skip >= {MIN_EXISTING_BARS} bars")

    completed = skipped = failed = 0
    session = requests.Session()

    for idx, symbol in enumerate(symbols, start=1):
        kline_ref = root.child("kline").child(symbol)
        existing = normalize_kline(kline_ref.get() or [])
        if len(existing) >= MIN_EXISTING_BARS:
            skipped += 1
            if idx % 25 == 0 or idx == len(symbols):
                print(f"[{idx}/{len(symbols)}] {symbol}: skip ({len(existing)} bars)")
            continue

        fetched = fetch_fugle_history(session, symbol)
        if not fetched:
            failed += 1
            print(f"[{idx}/{len(symbols)}] {symbol}: no history, kept {len(existing)} existing bars")
            continue

        # Merge so today's official TWSE/TPEx bar wins if the same date exists.
        merged_map = {row["time"]: row for row in fetched}
        for row in existing:
            merged_map[row["time"]] = row
        merged = normalize_kline(list(merged_map.values()))
        kline_ref.set(merged)
        completed += 1
        print(f"[{idx}/{len(symbols)}] {symbol}: wrote {len(merged)} bars")

    root.child("meta").child("history_backfill").set(
        {
            "provider": "Fugle",
            "completed_at": date.today().isoformat(),
            "target_bars": TARGET_BARS,
            "min_existing_bars": MIN_EXISTING_BARS,
            "symbols_scanned": len(symbols),
            "symbols_backfilled": completed,
            "symbols_skipped": skipped,
            "symbols_failed": failed,
            "adjusted": False,
        }
    )
    print(f"Backfill complete: backfilled={completed}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    main()
