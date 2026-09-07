#!/usr/bin/env python3
"""One-time historical K-line backfill for easystock.

Uses free official monthly historical endpoints:
- TWSE STOCK_DAY
- TPEx st43_result.php

This is deliberately separate from update_market.py so the daily workflow stays fast.
The script is resumable: stocks that already have TARGET_MIN_BARS are skipped.
It writes each stock independently to /market_data/kline/<symbol>.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any

import firebase_admin
import requests
from firebase_admin import credentials, db

FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "").strip().rstrip("/")
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
FIREBASE_ROOT_PATH = os.getenv("FIREBASE_ROOT_PATH", "market_data").strip("/") or "market_data"

HISTORY_MONTHS = max(3, int(os.getenv("HISTORY_MONTHS", "14")))
KLINE_DAYS = max(60, int(os.getenv("KLINE_DAYS", "250")))
TARGET_MIN_BARS = min(KLINE_DAYS, max(60, int(os.getenv("TARGET_MIN_BARS", "220"))))
HTTP_TIMEOUT = max(5.0, float(os.getenv("HISTORY_HTTP_TIMEOUT", "12")))
HTTP_WORKERS = max(1, min(8, int(os.getenv("HISTORY_HTTP_WORKERS", "3"))))
SHARD_INDEX = max(0, int(os.getenv("SHARD_INDEX", "0")))
SHARD_COUNT = max(1, int(os.getenv("SHARD_COUNT", "1")))

TWSE_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TPEX_HISTORY_URL = "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php"

_thread_local = threading.local()


def session() -> requests.Session:
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 easystock-history-backfill/0.62",
            "Accept": "application/json,text/plain,*/*",
        })
        _thread_local.session = s
    return s


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = re.sub(r"<[^>]+>", "", str(value))
    return text.replace("&nbsp;", " ").strip()


def safe_float(value: Any) -> float | None:
    text = safe_text(value).replace(",", "").replace("--", "").strip()
    if not text or text in {"-", "—", "N/A", "null", "None"}:
        return None
    text = re.sub(r"[^0-9.+-]", "", text)
    if not text or text in {"+", "-", "."}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def safe_int(value: Any) -> int | None:
    v = safe_float(value)
    return int(round(v)) if v is not None else None


def roc_date_to_iso(value: Any) -> str | None:
    text = safe_text(value).replace(".", "/").replace("-", "/")
    parts = text.split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = map(int, parts)
        if y < 1911:
            y += 1911
        return date(y, m, d).isoformat()
    except Exception:
        return None


def month_sequence(end_day: str | None, count: int) -> list[tuple[int, int]]:
    try:
        end = datetime.strptime((end_day or "")[:10], "%Y-%m-%d").date()
    except Exception:
        end = date.today()
    y, m = end.year, end.month
    out: list[tuple[int, int]] = []
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def fetch_json(url: str, *, params: dict[str, Any], label: str) -> Any:
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = session().get(url, params=params, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(0.6)
    raise RuntimeError(f"{label}: {last}")


def parse_twse_month(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []
    rows: list[dict[str, Any]] = []
    for row in payload.get("data") or []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        day = roc_date_to_iso(row[0])
        volume = safe_int(row[1])
        amount = safe_float(row[2])
        o, h, l, c = (safe_float(row[3]), safe_float(row[4]), safe_float(row[5]), safe_float(row[6]))
        if not day or None in (o, h, l, c):
            continue
        rows.append({
            "time": day,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": volume,
            "amount": amount,
        })
    return rows


def parse_tpex_month(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for row in payload.get("aaData") or []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        day = roc_date_to_iso(row[0])
        raw_volume = safe_int(row[1])
        raw_amount = safe_float(row[2])
        o, h, l, c = (safe_float(row[3]), safe_float(row[4]), safe_float(row[5]), safe_float(row[6]))
        if not day or None in (o, h, l, c):
            continue
        # TPEx st43 historical endpoint reports volume/amount in thousands.
        # Scale them to shares / NTD to match the daily OpenAPI schema used by update_market.py.
        volume = raw_volume * 1000 if raw_volume is not None else None
        amount = raw_amount * 1000 if raw_amount is not None else None
        rows.append({
            "time": day,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": volume,
            "amount": amount,
        })
    return rows


def normalize_kline(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = str(row.get("time") or row.get("date") or "")[:10]
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except Exception:
            continue
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        if None in (o, h, l, c):
            continue
        v = safe_int(row.get("volume"))
        a = safe_float(row.get("amount"))
        by_day[day] = {
            "time": day,
            "open": round(o, 4),
            "high": round(h, 4),
            "low": round(l, 4),
            "close": round(c, 4),
            "volume": v,
            "amount": a if a is not None else ((c * v) if v else None),
        }
    return [by_day[k] for k in sorted(by_day)][-KLINE_DAYS:]


def fetch_symbol_history(symbol: str, exchange: str, end_day: str | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for y, m in month_sequence(end_day, HISTORY_MONTHS):
        if exchange == "TWSE":
            payload = fetch_json(
                TWSE_HISTORY_URL,
                params={"response": "json", "date": f"{y}{m:02d}01", "stockNo": symbol},
                label=f"TWSE {symbol} {y}-{m:02d}",
            )
            result.extend(parse_twse_month(payload))
        else:
            payload = fetch_json(
                TPEX_HISTORY_URL,
                params={"d": f"{y - 1911}/{m:02d}", "stkno": symbol},
                label=f"TPEx {symbol} {y}-{m:02d}",
            )
            result.extend(parse_tpex_month(payload))
        time.sleep(0.04)
    return normalize_kline(result)


def init_firebase():
    if not FIREBASE_DATABASE_URL or not FIREBASE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing FIREBASE_DATABASE_URL or FIREBASE_SERVICE_ACCOUNT_JSON")
    payload = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(payload), {"databaseURL": FIREBASE_DATABASE_URL})
    return db.reference(f"/{FIREBASE_ROOT_PATH}")


def main() -> None:
    root = init_firebase()
    summary_map = root.child("summary").get() or {}
    kline_ref = root.child("kline")
    existing_map = kline_ref.get() or {}

    symbols = sorted(
        sym for sym, s in summary_map.items()
        if isinstance(s, dict) and str(sym).isdigit() and len(str(sym)) == 4
    )
    shard_symbols = [sym for idx, sym in enumerate(symbols) if idx % SHARD_COUNT == SHARD_INDEX]

    print(
        f"Historical backfill shard {SHARD_INDEX + 1}/{SHARD_COUNT}: "
        f"{len(shard_symbols)} symbols, months={HISTORY_MONTHS}, target>={TARGET_MIN_BARS} bars, workers={HTTP_WORKERS}"
    )

    skipped = 0
    work: list[str] = []
    for sym in shard_symbols:
        existing = normalize_kline(existing_map.get(sym) or [])
        if len(existing) >= TARGET_MIN_BARS:
            skipped += 1
        else:
            work.append(sym)

    print(f"Already sufficient: {skipped}; need backfill: {len(work)}")
    if not work:
        return

    completed = 0
    failed = 0

    def worker(sym: str):
        summary = summary_map.get(sym) or {}
        exchange = str(summary.get("exchange") or "TWSE")
        end_day = str(summary.get("updated_at") or "")[:10]
        old = normalize_kline(existing_map.get(sym) or [])
        hist = fetch_symbol_history(sym, exchange, end_day)
        merged = normalize_kline(hist + old)
        if len(merged) < 20:
            raise RuntimeError(f"history too short: {len(merged)} bars")
        # Per-symbol writes make the job resumable and safe across matrix shards.
        kline_ref.child(sym).set(merged)
        root.child("summary").child(sym).child("kline_count").set(len(merged))
        root.child("summary").child(sym).child("history_source").set("TWSE/TPEx official monthly history")
        return sym, len(old), len(hist), len(merged), exchange

    with ThreadPoolExecutor(max_workers=HTTP_WORKERS) as ex:
        futures = {ex.submit(worker, sym): sym for sym in work}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                sym, old_n, hist_n, merged_n, exchange = fut.result()
                completed += 1
                print(f"[OK] {sym} {exchange}: existing={old_n}, fetched={hist_n}, final={merged_n}")
            except Exception as exc:
                failed += 1
                print(f"[WARN] {sym}: {exc}")

    root.child("meta").child("history_backfill_last_run").set({
        "shard": SHARD_INDEX,
        "shard_count": SHARD_COUNT,
        "completed": completed,
        "failed": failed,
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "source": "TWSE STOCK_DAY + TPEx st43",
    })
    print(f"Backfill shard done: completed={completed}, failed={failed}, skipped={skipped}")
    if completed == 0 and failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
