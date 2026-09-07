def fetch_fugle_history(symbol: str, end_day: str) -> list[dict]:
    """
    從 Fugle MarketData API 取得股票日 K 歷史資料。
    API Key 由環境變數 FUGLE_API_KEY 讀取，
    並透過 X-API-KEY HTTP Header 傳送。
    """
    if not FUGLE_API_KEY:
        print(f"[WARN] Fugle {symbol} skipped: FUGLE_API_KEY is empty")
        return []

    end_date = parse_iso_date(end_day) or date.today()
    start_date = end_date - timedelta(days=360)

    _wait_for_fugle_rate_limit()

    url = f"{FUGLE_BASE}/historical/candles/{symbol}"
    params = {
        "from": start_date.isoformat(),
        "to": end_date.isoformat(),
        "timeframe": "D",
        "adjusted": "false",
        "fields": "open,high,low,close,volume,turnover",
        "sort": "asc",
    }
    headers = {
        "X-API-KEY": FUGLE_API_KEY,
        "Accept": "application/json",
    }

    try:
        print(
            f"[HTTP] Fugle {symbol} history "
            f"{start_date.isoformat()} -> {end_date.isoformat()}"
        )

        response = get_http_session().get(
            url,
            params=params,
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )

        if response.status_code == 401:
            print(
                f"[WARN] Fugle {symbol} history failed: "
                "401 Unauthorized — 請檢查 FUGLE_API_KEY"
            )
            return []

        if response.status_code == 403:
            print(
                f"[WARN] Fugle {symbol} history failed: "
                "403 Forbidden — API Key 可能沒有此 API 使用權限"
            )
            return []

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            print(
                f"[WARN] Fugle {symbol} history failed: "
                "429 Too Many Requests"
            )
            if retry_after:
                print(f"[WARN] Retry-After: {retry_after}")
            return []

        response.raise_for_status()
        payload = response.json()

    except requests.Timeout:
        print(f"[WARN] Fugle {symbol} history failed: timeout")
        return []

    except requests.ConnectionError as exc:
        print(
            f"[WARN] Fugle {symbol} history failed: "
            f"connection error: {exc}"
        )
        return []

    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        print(
            f"[WARN] Fugle {symbol} history failed: "
            f"HTTP {status_code}"
        )
        return []

    except ValueError as exc:
        print(
            f"[WARN] Fugle {symbol} history failed: "
            f"invalid JSON: {exc}"
        )
        return []

    except Exception as exc:
        print(f"[WARN] Fugle {symbol} history failed: {exc}")
        return []

    if not isinstance(payload, dict):
        print(f"[WARN] Fugle {symbol}: unexpected payload type")
        return []

    rows = payload.get("data")
    if not isinstance(rows, list):
        print(f"[WARN] Fugle {symbol}: no historical data returned")
        return []

    result = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        day = str(row.get("date") or "")[:10]
        o = safe_float(row.get("open"))
        h = safe_float(row.get("high"))
        l = safe_float(row.get("low"))
        c = safe_float(row.get("close"))
        v = safe_int(row.get("volume"))
        turnover = safe_float(row.get("turnover"))

        if not day or not parse_iso_date(day):
            continue

        if None in (o, h, l, c):
            continue

        if turnover is not None:
            amount = turnover
        elif v:
            amount = c * v
        else:
            amount = None

        result.append(
            {
                "time": day,
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": v,
                "amount": amount,
            }
        )

    result = normalize_kline(result, KLINE_DAYS)

    print(
        f"[OK] Fugle {symbol}: "
        f"{len(result)} historical candles"
    )

    return result
