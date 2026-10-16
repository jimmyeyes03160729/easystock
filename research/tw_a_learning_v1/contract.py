"""Pure point-in-time features for ordinary Taiwan stocks, not trade signals.

Callers must separately establish dataset provenance and calendar/eligibility
evidence. These checks cannot authenticate a caller's supplied metadata.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re

TPE = timezone(timedelta(hours=8))
SCHEMA = "tw-a-learning-v1"
FEATURES = (
    "gain_pct", "return_5m_pct", "surge_60s", "buy_ratio_60s", "amount_60s",
    "market_return_60s_pct", "market_return_5m_pct", "relative_return_5m_pct",
    "market_drawdown_from_high_pct", "minutes_since_open", "spread_pct",
    "day_volume_lots",
)


class ContractError(ValueError):
    pass


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise ContractError("invalid_timestamp") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(hours=8):
        raise ContractError("explicit_taiwan_timezone_required")
    return result.astimezone(TPE)


def number(value):
    if value is None or isinstance(value, bool):
        raise ContractError("missing_or_invalid_number")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ContractError("missing_or_invalid_number") from exc
    if not math.isfinite(result):
        raise ContractError("missing_or_invalid_number")
    return result


def known_at(value, decision, *, max_age_seconds=None, same_day=True):
    at = timestamp(value)
    age = (decision - at).total_seconds()
    if age < 0 or (same_day and at.date() != decision.date()):
        raise ContractError("future_or_wrong_day_source")
    if max_age_seconds is not None and age > max_age_seconds:
        raise ContractError("stale_source")
    return at


def stock_identity(row):
    if (row.get("market") != "TW" or row.get("venue") not in ("TWSE", "TPEX")
            or row.get("instrument_type") != "COMMON_STOCK"
            or not re.fullmatch(r"[1-9][0-9]{3}", str(row.get("symbol", "")))):
        raise ContractError("taiwan_common_stock_required")
    return str(row["symbol"])


def valid_price(value):
    """Validate the ordinary-stock schedule; never round a bad feed silently."""
    number(value)
    try:
        p = Decimal(str(value))
        if p <= 0:
            raise ContractError("invalid_price")
        tick = next((Decimal(t) for upper, t in (
            (10, ".01"), (50, ".05"), (100, ".1"), (500, ".5"), (1000, "1")
        ) if p < upper), Decimal("5"))
        if p % tick:
            raise ContractError("off_tick_price")
    except InvalidOperation as exc:
        raise ContractError("invalid_price") from exc
    return float(p)


def feature_row(row):
    """Build the same Taiwan context for each tabular research candidate.

    All source records use explicit +08:00 timestamps and volume units. The
    model receives no foreign prices, realized exits or future extrema.
    Missing index/history/book evidence is an error, never a zero-filled value.
    """
    try:
        stock_identity(row)
        decision = timestamp(row["decision_at"])
        if not time(9, 30) <= decision.time() < time(12, 30):
            raise ContractError("outside_a_entry_window")
        if row["session_date"] != decision.date().isoformat() or row["trading_day_verified"] is not True:
            raise ContractError("official_session_required")
        known_at(row["features_as_of"], decision, max_age_seconds=30)
        known_at(row["quote_at"], decision, max_age_seconds=30)
        # Security type and day-trade eligibility must be known at the decision.
        known_at(row["eligibility_as_of"], decision)
        if row["daytrade_eligible"] is not True:
            raise ContractError("daytrade_eligibility_required")
        price = valid_price(row["price"])
        previous = row["previous_reference"]
        prev_at = known_at(previous["available_at"], decision, same_day=False)
        if timestamp(previous["session_at"]).date() >= decision.date() or prev_at > decision:
            raise ContractError("previous_session_reference_required")
        reference = valid_price(previous["price"])
        lower, upper = valid_price(row["limit_down"]), valid_price(row["limit_up"])
        if not lower < price < upper:
            raise ContractError("limit_locked_or_invalid_limits")
        radar = row["radar"]
        known_at(radar["as_of"], decision, max_age_seconds=30)
        if number(radar["history_seconds"]) < 300 or not .5 <= number(radar["classified_ratio_60s"]) <= 1:
            raise ContractError("insufficient_tick_history")
        buy = number(radar["buy_ratio_60s"])
        if not 0 <= buy <= 1 or radar["amount_unit"] != "TWD":
            raise ContractError("invalid_flow_units_or_ratio")
        surge, amount = number(radar["surge_60s"]), number(radar["amount_60s"])
        if surge < 0 or amount < 0:
            raise ContractError("negative_flow")
        volume = row["day_volume"]
        known_at(volume["as_of"], decision, max_age_seconds=30)
        lots = number(volume["value"])
        if not lots.is_integer():
            raise ContractError("fractional_volume_not_supported")
        if volume["unit"] == "SHARES":
            lots /= 1000
        elif volume["unit"] != "LOT":
            raise ContractError("explicit_volume_unit_required")
        if lots < 0:
            raise ContractError("negative_volume")
        book = row["book"]
        known_at(book["as_of"], decision, max_age_seconds=15)
        bid, ask = valid_price(book["bid"]), valid_price(book["ask"])
        if ask < bid or book["size_unit"] != "SHARES":
            raise ContractError("invalid_book")
        sizes = [number(book[k]) for k in ("bid_shares", "ask_shares")]
        if any(size <= 0 or not size.is_integer() for size in sizes):
            raise ContractError("missing_counterparty")
        market = row["market_context"]
        expected = "TAIEX" if row["venue"] == "TWSE" else "TPEX_INDEX"
        if market["index"] != expected or market["source_kind"] != "OFFICIAL_INDEX":
            raise ContractError("matching_taiwan_index_required")
        known_at(market["as_of"], decision, max_age_seconds=30)
        current, prev60, prev300, high = (number(market[k]) for k in ("price", "price_60s_ago", "price_5m_ago", "session_high_so_far"))
        if min(current, prev60, prev300) <= 0 or high < current:
            raise ContractError("invalid_index_prices")
        for key, seconds in (("price_60s_at", 60), ("price_5m_at", 300)):
            at = known_at(market[key], decision)
            age = (decision - at).total_seconds()
            if not seconds <= age <= seconds + 30:
                raise ContractError("invalid_index_history_window")
        ret5 = number(row["return_5m_pct"])
        market5 = (current / prev300 - 1) * 100
        values = (
            (price / reference - 1) * 100, ret5, surge, buy, amount,
            (current / prev60 - 1) * 100, market5, ret5 - market5,
            (current / high - 1) * 100,
            (decision - decision.replace(hour=9, minute=0, second=0, microsecond=0)).total_seconds() / 60,
            (ask / bid - 1) * 100, lots,
        )
        return dict(zip(FEATURES, map(number, values)))
    except KeyError as exc:
        raise ContractError("missing_field:" + str(exc.args[0])) from exc


def completed_candles(rows, *, decision_at, market, venue, symbol):
    """Validate one-minute Kronos input only; never synthesize missing candles.

    Session boundaries remain real timestamps. Available-at must be recorded,
    not inferred from an end-of-day download timestamp. This does not choose
    a lookback, download weights or perform a prediction.
    """
    stock_identity(dict(market=market, venue=venue, symbol=symbol, instrument_type="COMMON_STOCK"))
    decision = timestamp(decision_at)
    result, previous_end = [], None
    for row in rows:
        try:
            if (row["symbol"] != symbol or row["venue"] != venue or row["market"] != market
                    or row["instrument_type"] != "COMMON_STOCK"):
                raise ContractError("mixed_instruments")
            start, end = timestamp(row["start_at"]), timestamp(row["end_at"])
            available = known_at(row["available_at"], decision, same_day=False)
            if (end - start != timedelta(minutes=1) or start.second or start.microsecond
                    or start.date() != end.date() or not time(9) <= start.time() < time(13, 30)
                    or end.time() > time(13, 30) or end > available
                    or row["trading_day_verified"] is not True):
                raise ContractError("unfinished_or_invalid_candle")
            if previous_end is not None:
                if start < previous_end:
                    raise ContractError("unordered_or_overlapping_candles")
                if start.date() == previous_end.date() and start != previous_end:
                    raise ContractError("missing_intraday_candle")
                if start.date() > previous_end.date() and (previous_end.time() != time(13, 30) or start.time() != time(9)):
                    raise ContractError("incomplete_session_boundary")
            o, h, l, c = (valid_price(row[k]) for k in ("open", "high", "low", "close"))
            if not l <= min(o, c) <= max(o, c) <= h:
                raise ContractError("invalid_ohlc")
            volume = number(row["volume"])
            if volume < 0 or not volume.is_integer() or row["volume_unit"] != "SHARES":
                raise ContractError("explicit_share_volume_required")
            # Zero-volume intervals cannot be repaired with invented OHLC.
            if volume == 0:
                raise ContractError("zero_volume_candle_not_supported")
            if row["amount_unit"] != "TWD" or number(row["amount"]) < 0:
                raise ContractError("explicit_twd_amount_required")
            result.append({"start_at": start.isoformat(), **{k: row[k] for k in ("open", "high", "low", "close", "volume", "amount")}})
            previous_end = end
        except KeyError as exc:
            raise ContractError("missing_field:" + str(exc.args[0])) from exc
    if not result:
        raise ContractError("empty_candles")
    if (decision - previous_end).total_seconds() > 90:
        raise ContractError("stale_candle_context")
    return result
