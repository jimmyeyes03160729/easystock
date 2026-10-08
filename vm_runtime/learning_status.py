#!/usr/bin/env python3
"""Read-only research/system inspection; publish only a small public summary with --publish."""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import multiprocessing
import sys
import time

TPE = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
DATA = Path(
    os.getenv(
        "LEARNING_DATA_DIR",
        "/home/ubuntu/easystock-learning-data",
    )
)

UNITS = (
    "easystock-intraday.service",
    "easystock-learning.service",
    "easystock-learning-train.service",
)

# The installed oneshot has TimeoutStartSec=50. Do not change its deadline.
TOTAL_DEADLINE = 40.0
OPERATION_DEADLINE = 8.0
CONNECT_TIMEOUT = 2.0
READ_TIMEOUT = 4.0
READ_ATTEMPTS = 2
RETRY_BACKOFF = 0.25


class StatusUnavailable(RuntimeError):
    """Incomplete inspection: preserve the previous public status."""


class StatusDeadline(StatusUnavailable):
    pass


def diagnostic(stage, status, started, *, error=None, attempt=None, count=None):
    """No exception text, URLs, paths, credentials or inspected data in logs."""
    row = {"component": "learning_status", "stage": stage, "status": status,
           "elapsed_s": round(max(0, time.monotonic() - started), 3)}
    if error is not None:
        row["error_type"] = type(error).__name__
    if attempt is not None:
        row["attempt"] = attempt
    if count is not None:
        row["count"] = count
    print(json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)


class Budget:
    def __init__(self, deadline, connection=None):
        self.deadline = deadline
        self.connection = connection

    def run(self, stage, operation, *, network=False, reserve=0):
        started = time.monotonic()
        stop = min(self.deadline - reserve,
                   started + OPERATION_DEADLINE if network else self.deadline)
        if stop <= started:
            raise StatusDeadline()
        if self.connection is not None:
            self.connection.send(("stage", stage, stop, started))
        diagnostic(stage, "STARTED", started)
        try:
            value = operation()
            if time.monotonic() >= stop:
                raise StatusDeadline()
        except Exception as error:
            diagnostic(stage, "UNAVAILABLE", started, error=error)
            raise
        diagnostic(stage, "OK", started)
        return value


def bounded_reference():
    """Learning-only SDK app/transport; no mutation of FirebaseStore or other jobs.

    Admin's public httpTimeout is a requests socket timeout, not a total deadline.
    Replace only this app's HTTP session to bound OAuth as well as RTDB, disable
    SDK transport retries, and use separate connect/read timeouts. The supervisor
    additionally reaps the worker on DNS, slow trickles or compute stalls.
    """
    import firebase_admin
    from firebase_admin import credentials, db
    from google.auth.transport.requests import AuthorizedSession, Request
    import requests
    import firebase_store as settings

    class TokenSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs["timeout"] = (CONNECT_TIMEOUT, READ_TIMEOUT)
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

    class DatabaseSession(AuthorizedSession):
        def request(self, method, url, **kwargs):
            kwargs["timeout"] = (CONNECT_TIMEOUT, READ_TIMEOUT)
            kwargs["allow_redirects"] = False
            return super().request(method, url, **kwargs)

    if settings.SERVICE_ACCOUNT_FILE:
        credential = credentials.Certificate(settings.SERVICE_ACCOUNT_FILE)
    elif settings.SERVICE_ACCOUNT_JSON:
        credential = credentials.Certificate(json.loads(settings.SERVICE_ACCOUNT_JSON))
    else:
        raise StatusUnavailable()
    app = firebase_admin.initialize_app(credential, {
        "databaseURL": settings.FIREBASE_DATABASE_URL,
        "httpTimeout": READ_TIMEOUT,
    }, name="learning-status-bounded")
    reference = db.reference("/" + settings.FIREBASE_ROOT_PATH, app=app)
    # SDK 7.5 (VM) and 7.7 (local) use this client/session integration point.
    # An incompatible SDK must fail before publication, never silently ignore it.
    client = reference._client
    if not isinstance(client._session, AuthorizedSession):
        raise StatusUnavailable()
    token_session = TokenSession()
    session = DatabaseSession(credential.get_credential(),
        auth_request=Request(session=token_session), max_refresh_attempts=0,
        refresh_timeout=READ_TIMEOUT)
    for transport in (token_session, session):
        for scheme in ("http://", "https://"):
            transport.mount(scheme, requests.adapters.HTTPAdapter(max_retries=0))
    client._session.close()
    client._session = session
    return reference


def firebase_read(reference, budget, stage):
    from firebase_admin import exceptions
    import requests

    def read_with_retry():
        stop = min(budget.deadline, time.monotonic() + OPERATION_DEADLINE)
        for attempt in range(1, READ_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                value = reference.get()
                if value is None:  # A successful JSON null is not a failed read.
                    return {}
                if not isinstance(value, dict):
                    raise StatusUnavailable()
                return value
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    exceptions.UnavailableError, exceptions.DeadlineExceededError) as error:
                diagnostic(stage, "RETRYABLE_FAILURE", started, error=error, attempt=attempt)
                delay = RETRY_BACKOFF * 2 ** (attempt - 1)
                if attempt == READ_ATTEMPTS or time.monotonic() + delay >= stop:
                    raise
                time.sleep(delay)
                if time.monotonic() >= stop:
                    raise StatusDeadline() from None
    return budget.run(stage, read_with_retry, network=True)


def read(path, default, errors):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (ValueError, OSError):
        errors.append(path.name)
        return default


def valid_day(value):
    if not isinstance(value, str):
        return False

    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def states():
    result = {}

    for unit in UNITS:
        try:
            out = subprocess.run(
                [
                    "systemctl",
                    "show",
                    unit,
                    "-p",
                    "ActiveState",
                    "-p",
                    "SubState",
                    "-p",
                    "ExecMainStatus",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout

            fields = dict(
                line.split("=", 1)
                for line in out.splitlines()
                if "=" in line
            )

            result[unit] = fields

        except Exception:
            result[unit] = {
                "ActiveState": "unknown"
            }

    return result


# EASYSTOCK_MODEL_STATUS_V2
def model_application(
    engine_hash,
    known_hashes,
):
    try:
        from daytrade_learning.model_status import (
            public_model_application,
        )

        return public_model_application()

    except Exception:
        return {
            "status": (
                "not_applied"
                if engine_hash in known_hashes
                else "unknown"
            ),
            "basis":
                "reviewed_engine_hash_fallback",
        }


def _rows(value):
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def trade_summary(live, session_date, research_rows=None):
    """Public aggregates only. Durable research evidence wins over mirrors."""
    all_rows = []
    source = research_rows if research_rows is not None else (
        _rows((live or {}).get('closed_trades')) + _rows((live or {}).get('open_positions')))
    seen = set()
    for row in source:
        stamp = str(row.get("exit_time") or row.get("entry_time") or "")
        identity = row.get('research_trade_id') or row.get('trade_id') or (row.get('symbol'), str(row.get('entry_time')))
        if stamp[:10] == session_date and identity not in seen:
            seen.add(identity)
            all_rows.append(row)
    rows = [row for row in all_rows if row.get('status', 'CLOSED') == 'CLOSED']
    gross_pnl = [float(row['pnl_pct']) for row in rows if isinstance(row.get('pnl_pct'), (int, float))]
    pnl = [float(row['research_net_pnl_pct'] if isinstance(row.get('research_net_pnl_pct'), (int, float))
                 else row['pnl_pct']) for row in rows
           if isinstance(row.get('pnl_pct'), (int, float))]
    net = [float(row['research_net_pnl_pct']) for row in rows
           if isinstance(row.get('research_net_pnl_pct'), (int, float))]
    mfe = [float(row["mfe_pct"]) for row in rows if isinstance(row.get("mfe_pct"), (int, float))]
    mae = [float(row["mae_pct"]) for row in rows if isinstance(row.get("mae_pct"), (int, float))]
    wins = sum(value > 0 for value in pnl)
    losses = sum(value < 0 for value in pnl)
    gross_profit = sum(value for value in pnl if value > 0)
    gross_loss = -sum(value for value in pnl if value < 0)
    curve = peak = drawdown = 0.0
    for value in pnl:
        curve += value
        peak = max(peak, curve)
        drawdown = min(drawdown, curve - peak)
    return {
        'source': 'research_store' if research_rows is not None else 'legacy_live_mirror',
        'accepted_episodes': len(all_rows), 'research_trades': len(all_rows),
        'research_closed': len(rows), 'research_open': len(all_rows)-len(rows),
        'paper_filled': sum(row.get('paper_execution') == 'FILLED' or
                            row.get('execution_kind') == 'paper_fill' for row in all_rows),
        'paper_skipped': sum(row.get('paper_execution') == 'SKIPPED' for row in all_rows),
        'paper_skipped_insufficient_cash': sum(row.get('paper_skip_reason') == 'insufficient_cash' for row in all_rows),
        'paper_skipped_daily_buy_limit': sum(row.get('paper_skip_reason') == 'daily_buy_limit_exceeded' for row in all_rows),
        "count": len(rows), "wins": wins, "losses": losses,
        'net_pnl_pct': sum(net) if net and len(net) == len(rows) else None,
        'gross_pnl_pct': sum(gross_pnl) if gross_pnl else None,
        'win_loss_basis': 'research_net_returns_when_available_else_legacy_gross',
        'net_pnl': None, 'return_pct': None,
        'pnl_basis': 'sum_of_independent_one_lot_research_returns_pct_not_wallet_return',
        "avg_pnl_pct": (sum(pnl) / len(pnl)) if pnl else None,
        "avg_mfe_pct": (sum(mfe) / len(mfe)) if mfe else None,
        "avg_mae_pct": (sum(mae) / len(mae)) if mae else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "max_drawdown_pct": drawdown if pnl else None,
        "exit_reasons": dict(Counter(str(row.get("exit_reason") or "UNKNOWN") for row in rows)),
    }


def compute(
    data,
    now,
    service_states,
    engine_hash,
    known_hashes,
    preferred_date=None,
    live=None,
    timing=None,
):
    errors = []
    today = now.date().isoformat()

    reports = []
    reports_by_date = {}

    collection_days = set()

    samples_by_date = Counter()
    observed_by_date = {}
    last_sample_by_date = {}

    labels_by_date = Counter()
    learned_by_date = {}

    # -----------------------------------------------------
    # Reports
    # -----------------------------------------------------
    scan_started = time.monotonic()
    file_count = 0
    for p in sorted(
        (data / "reports").glob("*.json")
    ):
        file_count += 1
        row = read(
            p,
            {},
            errors,
        )

        if (
            isinstance(row, dict)
            and valid_day(row.get("date"))
        ):
            reports.append(row)
            reports_by_date[row["date"]] = row

    if timing:
        timing("reports_scan", "OK", scan_started, count=file_count)

    # -----------------------------------------------------
    # Intraday learning journals
    # -----------------------------------------------------
    scan_started = time.monotonic()
    file_count = 0
    for p in sorted(
        data.glob("journal-*.jsonl")
    ):
        file_count += 1
        file_day = (
            p.stem.removeprefix(
                "journal-"
            )
        )

        has_samples = False

        try:
            with p.open() as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        errors.append(p.name)
                        continue

                    if row.get("kind") != "sample":
                        continue

                    d = row.get(
                        "data",
                        {},
                    )

                    at = str(
                        d.get(
                            "observed_at",
                            "",
                        )
                        or ""
                    )

                    date = at[:10]

                    if (
                        date != file_day
                        or not valid_day(date)
                    ):
                        continue

                    has_samples = True

                    samples_by_date[date] += 1

                    symbol = str(
                        d.get(
                            "symbol",
                            "",
                        )
                        or ""
                    ).strip()

                    if symbol:
                        observed_by_date.setdefault(
                            date,
                            set(),
                        ).add(symbol)

                    previous = (
                        last_sample_by_date.get(
                            date
                        )
                    )

                    if (
                        previous is None
                        or at > previous
                    ):
                        last_sample_by_date[
                            date
                        ] = at

            if has_samples:
                collection_days.add(
                    file_day
                )

        except OSError:
            errors.append(p.name)

    if timing:
        timing("journals_scan", "OK", scan_started, count=file_count)

    # -----------------------------------------------------
    # Labels
    # -----------------------------------------------------
    unique = {}
    scan_started = time.monotonic()
    file_count = 0

    for p in sorted(
        (data / "labels").glob("*.json")
    ):
        file_count += 1
        rows = read(
            p,
            [],
            errors,
        )

        if not isinstance(
            rows,
            list,
        ):
            errors.append(p.name)
            continue

        for row in rows:
            if not isinstance(
                row,
                dict,
            ):
                continue

            if (
                not row.get("symbol")
                or not row.get("at")
                or row.get("date")
                != p.stem
                or not row.get("profile")
            ):
                continue

            unique[
                (
                    row["symbol"],
                    row["at"],
                    row["profile"],
                )
            ] = row

    if timing:
        timing("labels_scan", "OK", scan_started, count=file_count)

    labels = list(
        unique.values()
    )

    for row in labels:
        date = row.get("date")

        if not valid_day(date):
            continue

        labels_by_date[date] += 1

        learned_by_date.setdefault(
            date,
            set(),
        ).add(
            str(row["symbol"])
        )

    # -----------------------------------------------------
    # Training profile
    # -----------------------------------------------------
    recent = (
        max(
            labels,
            key=lambda x: x["at"],
        )
        if labels
        else {}
    )

    profile = recent.get(
        "profile"
    )

    same = [
        x
        for x in labels
        if x.get("profile")
        == profile
    ]

    # -----------------------------------------------------
    # 最近交易日
    # -----------------------------------------------------
    activity_dates = set(
        samples_by_date.keys()
    )

    activity_dates.update(
        labels_by_date.keys()
    )

    activity_dates.update(
        reports_by_date.keys()
    )
    from daytrade_learning.episodes import research_days
    activity_dates.update(day for day in research_days(Path(data)/'research.sqlite') if valid_day(day))

    if valid_day(
        preferred_date
    ):
        activity_dates.add(
            preferred_date
        )

    session_date = (
        max(activity_dates)
        if activity_dates
        else today
    )

    def build_day(date):
        report = (
            reports_by_date.get(
                date,
                {},
            )
        )

        collection = (
            report.get(
                "collection",
                {},
            )
            if isinstance(
                report,
                dict,
            )
            else {}
        )

        ai = (
            report.get(
                "ai",
                {},
            )
            if isinstance(
                report,
                dict,
            )
            else {}
        )

        return {
            "date":
                date,

            "sample_count":
                samples_by_date.get(
                    date,
                    0,
                ),

            "observed_stocks":
                len(
                    observed_by_date.get(
                        date,
                        set(),
                    )
                ),

            "learned_stocks":
                len(
                    learned_by_date.get(
                        date,
                        set(),
                    )
                ),

            "labeled_count":
                labels_by_date.get(
                    date,
                    0,
                ),

            "requested":
                collection.get(
                    "requested"
                ),

            "downloaded":
                collection.get(
                    "downloaded"
                ),

            "report_status":
                report.get(
                    "status"
                )
                if isinstance(
                    report,
                    dict,
                )
                else None,

            "ai_status":
                ai.get(
                    "status"
                )
                if isinstance(
                    ai,
                    dict,
                )
                else None,
        }

    # -----------------------------------------------------
    # Service phase
    # -----------------------------------------------------
    phase = "idle"

    if any(
        x.get("SubState")
        == "auto-restart"
        or x.get("ActiveState")
        == "failed"
        for x in service_states.values()
    ):
        phase = "failed"

    elif any(
        x.get("ActiveState")
        == "unknown"
        for x in service_states.values()
    ):
        phase = "unknown"

    elif (
        service_states
        .get(
            UNITS[2],
            {},
        )
        .get("ActiveState")
        in (
            "active",
            "activating",
        )
    ):
        phase = "training"

    elif (
        service_states
        .get(
            UNITS[1],
            {},
        )
        .get("ActiveState")
        in (
            "active",
            "activating",
        )
    ):
        phase = "reviewing"

    elif (
        service_states
        .get(
            UNITS[0],
            {},
        )
        .get("ActiveState")
        in (
            "active",
            "activating",
        )
    ):
        try:
            last_sample = (
                last_sample_by_date.get(
                    today
                )
            )

            age = (
                now
                - datetime.fromisoformat(
                    last_sample
                )
            ).total_seconds()

        except (
            TypeError,
            ValueError,
        ):
            age = 999999

        phase = (
            "collecting"
            if 0 <= age <= 420
            else "unknown"
        )

    training = read(
        data / "training-status.json",
        {},
        errors,
    )

    last_report = (
        max(
            reports,
            key=lambda x: x["date"],
        )
        if reports
        else {}
    )

    return {
        "schema_version":
            1,

        "updated_at":
            now.isoformat(),

        "phase":
            phase,

        "data_errors":
            sorted(
                set(errors)
            ),

        # 保留舊欄位，避免其他前端壞掉。
        "today":
            build_day(today),

        # 新欄位：畫面主要改讀最近交易日。
        "session":
            build_day(
                session_date
            ),

        "totals": {
            "collection_days":
                len(
                    collection_days
                ),

            "learning_days":
                len(
                    {
                        x["date"]
                        for x in labels
                        if valid_day(
                            x.get("date")
                        )
                    }
                ),

            "training_days":
                len(
                    {
                        x["date"]
                        for x in same
                        if valid_day(
                            x.get("date")
                        )
                    }
                ),

            "training_samples":
                len(same),
        },

        "training": {
            k:
                training.get(k)
            for k in (
                "status",
                "reason",
                "dates",
                "samples",
                "deployment_allowed",
                "trained_through", "validation", "profit_factor", "max_drawdown_pct",
            )
        },

        "model_application":
            model_application(
                engine_hash,
                known_hashes,
            ),

        "last_report": {
            "date":
                last_report.get(
                    "date"
                ),

            "status":
                last_report.get(
                    "status"
                ),
        },
        "research_summary": {
            "date": session_date,
            "new_samples": samples_by_date.get(session_date, 0),
            "labels": labels_by_date.get(session_date, 0),
            "requested": build_day(session_date).get("requested"),
            "downloaded": build_day(session_date).get("downloaded"),
            "trades": trade_summary(live or {}, session_date,
                research_rows=_research_rows(data, session_date)),
        },
    }


def _research_rows(data, day):
    from daytrade_learning.episodes import read_trades
    path = Path(data) / 'research.sqlite'
    return read_trades(path, day) if path.exists() else None


def iter_live_rows(
    value,
):
    if isinstance(
        value,
        dict,
    ):
        for key, row in (
            value.items()
        ):
            if isinstance(
                row,
                dict,
            ):
                yield str(key), row

    elif isinstance(
        value,
        list,
    ):
        for index, row in enumerate(
            value
        ):
            if isinstance(
                row,
                dict,
            ):
                yield str(index), row


def recommendation_summary(
    live,
    session_date,
):
    empty = {
        "recommended_stocks":
            None,

        "open_recommendations":
            None,

        "closed_recommendations":
            None,
    }

    if not isinstance(
        live,
        dict,
    ):
        return empty

    if (
        live.get("scan_date")
        != session_date
    ):
        return empty

    open_symbols = set()
    closed_symbols = set()

    def collect(
        node,
        target,
    ):
        for key, row in iter_live_rows(
            node
        ):
            entry_time = str(
                row.get(
                    "entry_time",
                    "",
                )
                or ""
            )

            # 有 entry_time 時必須屬於該交易日。
            if (
                entry_time
                and entry_time[:10]
                != session_date
            ):
                continue

            symbol = str(
                row.get(
                    "symbol"
                )
                or key
                or ""
            ).strip()

            if symbol:
                target.add(
                    symbol
                )

    collect(
        live.get(
            "open_positions"
        ),
        open_symbols,
    )

    collect(
        live.get(
            "closed_trades"
        ),
        closed_symbols,
    )

    all_symbols = (
        open_symbols
        | closed_symbols
    )

    return {
        "recommended_stocks":
            len(all_symbols),

        "open_recommendations":
            len(open_symbols),

        "closed_recommendations":
            len(closed_symbols),
    }


def inspect_status(publish, budget, reference_factory=bounded_reference):
    known = budget.run("local_metadata", lambda: read(
        ROOT
        / "learning_status_engine_hashes.json",
        [],
        [],
    ))

    engine_hash = hashlib.sha256(
        (
            ROOT
            / "intraday_live.py"
        ).read_bytes()
    ).hexdigest()

    reference = budget.run("firebase_init", reference_factory, network=True)
    live = firebase_read(reference.child("intraday_live"), budget, "firebase_live_read")
    overnight = firebase_read(reference.child("intraday_picks"), budget, "firebase_overnight_read")

    def complete_compute():
        result = compute(DATA, datetime.now(TPE), states(), engine_hash, known,
                         preferred_date=live.get("scan_date"), live=live, timing=diagnostic)
        if result.get("data_errors"):
            # Missing optional files keep their old semantics, but failed/corrupt
            # reads must not become a fresh, apparently complete snapshot.
            raise StatusUnavailable()
        return result
    result = budget.run("compute", complete_compute,
                        reserve=OPERATION_DEADLINE if publish else 0)

    result["session"].update(
        recommendation_summary(
            live,
            result["session"]["date"],
        )
    )

    # ---------------------------------------------------------
    # Runtime model application status
    # ---------------------------------------------------------
    def runtime_status():
        try:
            from daytrade_learning.model_runtime import DaytradeModel
            runtime_model = DaytradeModel()
            runtime_decision = runtime_model.evaluate({})
            version = (runtime_decision.get("model_version")
                       or getattr(runtime_model, "model_version", None))
            mode = os.environ.get("LIVE_ENTRY_MODE", "model")
            ready = bool(runtime_decision.get("active") and runtime_decision.get("approved"))
            result["model_application"] = {
                "status": "not_applied" if mode != "model" or not ready else "unknown",
                "basis": "explicit_rules_mode" if mode == "rules" else
                         "approved_model_configured_runtime_not_verified" if ready else runtime_decision.get("reason"),
                "model_version": version, "entry_mode": mode, "configured": ready,
            }
        except Exception as error:
            result.setdefault("model_application", {
                "status": "unknown", "basis": "runtime_check_failed"})
            result["model_application"]["runtime_error"] = type(error).__name__

    budget.run("model_status", runtime_status)

    config = live.get("config") if isinstance(live, dict) else {}
    closed = _rows(live.get("closed_trades")) if isinstance(live, dict) else []
    result["model_application"].update({
        "runtime_loaded": config.get("model_ready") if isinstance(config, dict) else None,
        "runtime_used": any(row.get("model_version") for row in closed),
    })

    # -----------------------------------------------------
    # Overnight
    # -----------------------------------------------------
    result["overnight"] = {
        k:
            overnight.get(k)
        for k in (
            "scan_date",
            "generated_at",
            "session",
            "scanned_symbols",
            "candidate_symbols",
            "market_level",
            "daily_source_date",
        )
    }

    candidates = (
        overnight.get(
            "overnight_candidates",
            overnight.get(
                "overnight",
                [],
            ),
        )
    )

    result[
        "overnight"
    ].update(
        candidate_count=(
            len(candidates)
            if isinstance(
                candidates,
                list,
            )
            else None
        ),
        enabled=overnight.get(
            "legacy_overnight_enabled"
        ),
    )

    if publish:
        # One complete PUT only. Never retry an ambiguous write, clear the node,
        # or publish a placeholder/renewed timestamp on any inspection failure.
        budget.run("firebase_publish", lambda: reference.child(
            "daytrade_learning_status").set(result), network=True)
    return result


def _worker(connection, publish, deadline):
    started = time.monotonic()
    try:
        result = inspect_status(publish, Budget(deadline, connection))
        if not publish:
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        connection.send(("done", 0))
    except Exception as error:
        diagnostic("inspection", "UNAVAILABLE", started, error=error)
        connection.send(("done", 1))
    finally:
        connection.close()


def supervise(publish, *, worker=_worker, timeout=TOTAL_DEADLINE):
    """A process deadline, not a Future/thread timeout leaving I/O running.

    Reap only our own inspection worker. Never stop a systemd service or signal
    another job. A timed-out PUT has unknown server outcome and is not retried.
    """
    started = time.monotonic()
    deadline = started + timeout
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(child, publish, deadline))
    stage, stage_started, stop = "startup", started, deadline
    process.start()
    child.close()
    code = 1
    try:
        while True:
            remaining = min(deadline, stop) - time.monotonic()
            if remaining <= 0:
                diagnostic(stage, "UNAVAILABLE", stage_started, error=StatusDeadline())
                break
            if not parent.poll(remaining):
                continue
            try:
                event = parent.recv()
            except EOFError:
                break
            if event[0] == "stage":
                _, stage, stop, stage_started = event
            elif event[0] == "done":
                code = event[1]
                break
    finally:
        # No live worker, open socket or delayed publisher after returning.
        if code != 0 and process.is_alive():
            process.terminate()
        process.join(0.5)
        if process.is_alive():
            process.kill()
            process.join(0.5)
            code = 1
        if process.is_alive() or process.exitcode not in (0, None):
            code = 1
        parent.close()
    diagnostic("total", "UNAVAILABLE" if code else "OK", started)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    return supervise(args.publish)


if __name__ == "__main__":
    raise SystemExit(main())
