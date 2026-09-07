#!/usr/bin/env python3
"""Resumable Fugle historical backfill for EasyStock v0.71.

Purpose
-------
* Keep `/market_data/kline/{symbol}` lightweight for the browser (latest 250 bars).
* Keep `/market_data/history/{symbol}` separately for research validation (3 or 5 years).
* Re-running is safe: symbols with enough history are skipped.

Fugle historical candle ranges are intentionally queried in sub-year chunks.
The same API key is rate-limited globally by this job, so this workflow is
one-time/resumable and is NOT part of the normal daily update.
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

BACKFILL_YEARS = max(3, min(5, int(os.environ.get("BACKFILL_YEARS", "3"))))
DISPLAY_BARS = max(60, int(os.environ.get("DISPLAY_KLINE_BARS", "250")))
TARGET_BARS = max(DISPLAY_BARS, int(os.environ.get("BACKFILL_TARGET_BARS", str(BACKFILL_YEARS * 252))))
MIN_EXISTING_BARS = max(DISPLAY_BARS, int(os.environ.get("BACKFILL_MIN_EXISTING_BARS", str(int(TARGET_BARS * 0.92)))))
MAX_SYMBOLS = max(1, int(os.environ.get("BACKFILL_MAX_SYMBOLS", "500")))
HTTP_TIMEOUT = max(5.0, float(os.environ.get("HTTP_TIMEOUT", "12")))
FUGLE_MIN_INTERVAL_SECONDS = max(1.02, float(os.environ.get("FUGLE_MIN_INTERVAL_SECONDS", "1.10")))
MAX_RETRIES = max(1, int(os.environ.get("FUGLE_MAX_RETRIES", "4")))
CHUNK_DAYS = 360

FUGLE_HISTORY_URL = "https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{symbol}"
USER_AGENT = "Mozilla/5.0 (compatible; easystock/0.71-fugle-backfill; +https://github.com/jimmyeyes03160729/easystock)"
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


def normalize_rows(rows: list[dict] | dict | None, limit: int | None = None) -> list[dict]:
    by_day: dict[str, dict] = {}
    source = rows.values() if isinstance(rows, dict) else (rows or [])
    for row in source:
        if not isinstance(row, dict):
            continue
        day = str(row.get("time") or row.get("date") or "")[:10]
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        if len(day) != 10 or None in (o, h, l, c):
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
    ordered = [by_day[k] for k in sorted(by_day)]
    return ordered[-limit:] if limit and limit > 0 else ordered


def init_firebase() -> None:
    if not FIREBASE_DATABASE_URL:
        raise RuntimeError("Missing FIREBASE_DATABASE_URL")
    if not FIREBASE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing FIREBASE_SERVICE_ACCOUNT_JSON")
    if not FUGLE_API_KEY:
        raise RuntimeError("Missing FUGLE_API_KEY")
    payload = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(payload), {"databaseURL": FIREBASE_DATABASE_URL})


def wait_for_rate_limit() -> None:
    global _last_fugle_call
    elapsed = time.monotonic() - _last_fugle_call
    if elapsed < FUGLE_MIN_INTERVAL_SECONDS:
        time.sleep(FUGLE_MIN_INTERVAL_SECONDS - elapsed)
    _last_fugle_call = time.monotonic()


def fetch_chunk(session: requests.Session, symbol: str, start_date: date, end_date: date) -> list[dict]:
    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timeframe": "D",
        # Unadjusted keeps continuity with TWSE/TPEx official daily bars appended later.
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
            return normalize_rows(rows or [])
        if response.status_code == 404:
            return []
        if response.status_code == 429:
            retry_after = safe_float(response.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else min(20.0, 4.0 * attempt)
            print(f"[RATE] {symbol}: 429, wait {delay:.1f}s")
            time.sleep(delay)
            continue
        if 500 <= response.status_code < 600 and attempt < MAX_RETRIES:
            time.sleep(min(8.0, 1.5 * attempt + random.random()))
            continue
        print(f"[WARN] {symbol}: HTTP {response.status_code}: {response.text[:160].replace(chr(10), ' ')}")
        return []
    return []


def fetch_history(session: requests.Session, symbol: str) -> list[dict]:
    # Add buffer because 252 trading days occupy more than 365 calendar days.
    end_date = date.today()
    start_date = end_date - timedelta(days=int(BACKFILL_YEARS * 365.25) + 120)
    cursor = start_date
    rows: list[dict] = []
    while cursor <= end_date:
        chunk_end = min(end_date, cursor + timedelta(days=CHUNK_DAYS))
        rows.extend(fetch_chunk(session, symbol, cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return normalize_rows(rows, TARGET_BARS)


def symbol_order(summary: dict[str, dict]) -> list[str]:
    def key(item: tuple[str, dict]) -> tuple[int, str]:
        sym, data = item
        try:
            rank = int((data or {}).get("hot_rank") or 999999)
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
    print(
        f"Fugle research-history backfill: years={BACKFILL_YEARS}, target={TARGET_BARS} bars, "
        f"skip >= {MIN_EXISTING_BARS}, symbols={len(symbols)}"
    )

    completed = skipped = failed = 0
    session = requests.Session()
    for idx, symbol in enumerate(symbols, start=1):
        history_ref = root.child("history").child(symbol)
        kline_ref = root.child("kline").child(symbol)
        existing_history = normalize_rows(history_ref.get() or [])
        existing_display = normalize_rows(kline_ref.get() or [])
        existing = normalize_rows(existing_history + existing_display, TARGET_BARS)
        if len(existing) >= MIN_EXISTING_BARS:
            skipped += 1
            if idx % 20 == 0 or idx == len(symbols):
                print(f"[{idx}/{len(symbols)}] {symbol}: skip ({len(existing)} bars)")
            continue

        fetched = fetch_history(session, symbol)
        if not fetched:
            failed += 1
            print(f"[{idx}/{len(symbols)}] {symbol}: no history; kept {len(existing)} bars")
            continue

        merged_map = {row["time"]: row for row in fetched}
        # Existing official bars win on duplicate dates.
        for row in existing:
            merged_map[row["time"]] = row
        merged = normalize_rows(list(merged_map.values()), TARGET_BARS)
        history_ref.set(merged)
        kline_ref.set(merged[-DISPLAY_BARS:])
        root.child("summary").child(symbol).update({"history_count": len(merged), "kline_count": min(DISPLAY_BARS, len(merged))})
        completed += 1
        print(f"[{idx}/{len(symbols)}] {symbol}: history={len(merged)}, display={min(DISPLAY_BARS, len(merged))}")

    root.child("meta").child("history_backfill").set({
        "provider": "Fugle",
        "completed_at": date.today().isoformat(),
        "years": BACKFILL_YEARS,
        "target_bars": TARGET_BARS,
        "min_existing_bars": MIN_EXISTING_BARS,
        "symbols_scanned": len(symbols),
        "symbols_backfilled": completed,
        "symbols_skipped": skipped,
        "symbols_failed": failed,
        "adjusted": False,
        "purpose": "rolling-forward research validation; browser chart remains latest 250 bars",
    })
    print(f"Backfill complete: backfilled={completed}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    main()
