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
    for p in sorted(
        (data / "reports").glob("*.json")
    ):
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

    # -----------------------------------------------------
    # Intraday learning journals
    # -----------------------------------------------------
    for p in sorted(
        data.glob("journal-*.jsonl")
    ):
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

    # -----------------------------------------------------
    # Labels
    # -----------------------------------------------------
    unique = {}

    for p in sorted(
        (data / "labels").glob("*.json")
    ):
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


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--publish",
        action="store_true",
    )

    args = parser.parse_args()

    known = read(
        ROOT
        / "learning_status_engine_hashes.json",
        [],
        [],
    )

    engine_hash = hashlib.sha256(
        (
            ROOT
            / "intraday_live.py"
        ).read_bytes()
    ).hexdigest()

    from firebase_store import FirebaseStore

    store = FirebaseStore()

    live = (
        store.root
        .child(
            "intraday_live"
        )
        .get()
        or {}
    )

    result = compute(
        DATA,
        datetime.now(TPE),
        states(),
        engine_hash,
        known,
        preferred_date=(
            live.get(
                "scan_date"
            )
            if isinstance(
                live,
                dict,
            )
            else None
        ),
        live=live,
    )

    result["session"].update(
        recommendation_summary(
            live,
            result["session"]["date"],
        )
    )

    # ---------------------------------------------------------
    # Runtime model application status
    # ---------------------------------------------------------
    try:
        from daytrade_learning.model_runtime import (
            DaytradeModel,
        )

        runtime_model = (
            DaytradeModel()
        )

        runtime_decision = (
            runtime_model.evaluate(
                {}
            )
        )

        runtime_version = (
            runtime_decision.get(
                "model_version"
            )
            or getattr(
                runtime_model,
                "model_version",
                None,
            )
        )

        runtime_reason = (
            runtime_decision.get(
                "reason"
            )
        )

        mode = os.environ.get('LIVE_ENTRY_MODE', 'model')
        ready = bool(runtime_decision.get('active') and runtime_decision.get('approved'))
        result['model_application'] = {
            'status': 'not_applied' if mode != 'model' or not ready else 'unknown',
            'basis': 'explicit_rules_mode' if mode == 'rules' else
                     'approved_model_configured_runtime_not_verified' if ready else runtime_reason,
            'model_version': runtime_version,
            'entry_mode': mode,
            'configured': ready,
        }

    except Exception as exc:
        result.setdefault(
            "model_application",
            {
                "status":
                    "unknown",

                "basis":
                    "runtime_check_failed",
            },
        )

        result[
            "model_application"
        ][
            "runtime_error"
        ] = (
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    config = live.get("config") if isinstance(live, dict) else {}
    closed = _rows(live.get("closed_trades")) if isinstance(live, dict) else []
    result["model_application"].update({
        "runtime_loaded": config.get("model_ready") if isinstance(config, dict) else None,
        "runtime_used": any(row.get("model_version") for row in closed),
    })

    # -----------------------------------------------------
    # Overnight
    # -----------------------------------------------------
    overnight = (
        store.root
        .child(
            "intraday_picks"
        )
        .get()
        or {}
    )

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

    if args.publish:
        (
            store.root
            .child(
                "daytrade_learning_status"
            )
            .set(result)
        )

    else:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
