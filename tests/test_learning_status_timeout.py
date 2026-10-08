"""Synthetic fixtures only; no VM data, Firebase credentials or real network."""
import copy
from datetime import datetime
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from firebase_admin import exceptions

import learning_status as status


class Reference:
    def __init__(self):
        self.nodes = {name: SimpleNamespace(get=Mock(return_value={}), set=Mock())
                      for name in ("intraday_live", "intraday_picks", "daytrade_learning_status")}
        self.previous = {"updated_at": "2026-10-01T09:00:00+08:00", "phase": "idle"}

    def child(self, name):
        return self.nodes[name]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "DATA", tmp_path)
    monkeypatch.setattr(status, "states", lambda: {})
    monkeypatch.setenv("LEARNING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_PAPER_MODEL_PATH", str(tmp_path / "missing-model.json"))
    monkeypatch.setenv("MODEL_RUNTIME_STATUS_PATH", str(tmp_path / "missing-status.json"))
    monkeypatch.setattr(status, "model_application", lambda *a: {"status": "unknown"})
    from daytrade_learning import model_runtime
    monkeypatch.setattr(model_runtime, "DaytradeModel", lambda: SimpleNamespace(
        evaluate=lambda _: {"active": False, "approved": False, "reason": "fixture"}))
    # Ordinary pre-holdout synthetic files, not a fixture copied from production.
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "one.json").write_text(json.dumps({"date": "2026-10-01"}))
    (tmp_path / "journal-2026-10-01.jsonl").write_text(json.dumps({
        "kind": "sample", "data": {"observed_at": "2026-10-01T09:00:00+08:00", "symbol": "TEST"}}) + "\n")
    monkeypatch.setattr(status, "RETRY_BACKOFF", 0.001)
    return Reference()


def inspect(reference, publish=True):
    return status.inspect_status(publish, status.Budget(time.monotonic() + 40), lambda: reference)


def test_t1_success_preserves_existing_compute_schema(fixture, monkeypatch):
    fixed = datetime(2026, 10, 1, 10, tzinfo=status.TPE)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed
    monkeypatch.setattr(status, "datetime", Clock)
    expected = status.compute(status.DATA, fixed, {}, "fixture", [], live={})
    result = inspect(fixture)
    for field in ("schema_version", "updated_at", "phase", "today", "totals", "training",
                  "last_report", "research_summary", "data_errors"):
        assert result[field] == expected[field]
    assert result["session"]["sample_count"] == 1
    fixture.child("daytrade_learning_status").set.assert_called_once_with(result)


@pytest.mark.parametrize("error", [requests.ConnectTimeout, requests.ReadTimeout,
                                  exceptions.UnavailableError, exceptions.DeadlineExceededError])
def test_t2_t3_t5_failed_read_preserves_previous_no_publish(fixture, error, capsys):
    previous = copy.deepcopy(fixture.previous)
    fixture.child("intraday_live").get.side_effect = error("private-url-secret-payload")
    with pytest.raises(error):
        inspect(fixture)
    assert fixture.previous == previous
    assert fixture.child("intraday_live").get.call_count == 2
    fixture.child("daytrade_learning_status").set.assert_not_called()
    assert "private-url-secret-payload" not in capsys.readouterr().err


def test_t4_write_timeout_is_failure_and_never_retried(fixture):
    target = fixture.child("daytrade_learning_status")
    target.set.side_effect = requests.ReadTimeout("private")
    with pytest.raises(requests.ReadTimeout):
        inspect(fixture)
    target.set.assert_called_once()
    payload = target.set.call_args.args[0]
    assert payload["session"]["sample_count"] == 1
    assert payload and payload["schema_version"] == 1
    assert fixture.previous["updated_at"].startswith("2026-10-01")


def test_t5_overnight_failure_aborts_whole_snapshot(fixture):
    fixture.child("intraday_picks").get.side_effect = requests.ConnectTimeout("private")
    with pytest.raises(requests.ConnectTimeout):
        inspect(fixture)
    fixture.child("daytrade_learning_status").set.assert_not_called()


def test_t6_transient_read_recovers_with_bounded_retry(fixture):
    live = {"scan_date": "2026-10-01"}
    fixture.child("intraday_live").get.side_effect = [requests.ConnectTimeout("private"), live]
    result = inspect(fixture)
    assert result["session"]["date"] == "2026-10-01"
    assert fixture.child("intraday_live").get.call_count == 2


def test_t6_no_retry_after_operation_deadline(fixture, monkeypatch):
    monkeypatch.setattr(status, "OPERATION_DEADLINE", 0.001)
    monkeypatch.setattr(status, "RETRY_BACKOFF", 0.01)
    fixture.child("intraday_live").get.side_effect = requests.ConnectTimeout("private")
    with pytest.raises(requests.ConnectTimeout):
        inspect(fixture)
    assert fixture.child("intraday_live").get.call_count == 1


def test_invalid_success_payload_is_not_empty_data(fixture):
    fixture.child("intraday_live").get.return_value = ["invalid"]
    with pytest.raises(status.StatusUnavailable):
        inspect(fixture)
    fixture.child("daytrade_learning_status").set.assert_not_called()


def test_successful_null_retains_original_empty_node_semantics(fixture):
    fixture.child("intraday_live").get.return_value = None
    inspect(fixture)
    fixture.child("daytrade_learning_status").set.assert_called_once()


def test_local_scan_failure_never_publishes_partial_counts(fixture):
    (status.DATA / "journal-2026-10-01.jsonl").write_text("broken-json\n")
    with pytest.raises(status.StatusUnavailable):
        inspect(fixture)
    fixture.child("daytrade_learning_status").set.assert_not_called()


def test_t7_stage_timing_contains_no_research_payload(fixture, capsys):
    inspect(fixture)
    rows = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert {row["stage"] for row in rows} >= {
        "firebase_live_read", "firebase_overnight_read", "compute", "reports_scan",
        "journals_scan", "labels_scan", "firebase_publish"}
    assert all(set(row) <= {"component", "stage", "status", "elapsed_s", "count", "attempt", "error_type"} for row in rows)
    assert all(row["elapsed_s"] >= 0 for row in rows)
    assert "TEST" not in json.dumps(rows)


def _blocked_network_worker(connection, publish, deadline):
    # Mock a DNS/socket that never respects its own timeout; no network opened.
    connection.send(("stage", "firebase_live_read", time.monotonic() + 0.1, time.monotonic()))
    time.sleep(5)
    Path(os.environ["LEARNING_TEST_MARKER"]).write_text("late-write")
    connection.send(("done", 0))


def _slow_compute_worker(connection, publish, deadline):
    connection.send(("stage", "compute", deadline, time.monotonic()))
    time.sleep(5)
    Path(os.environ["LEARNING_TEST_MARKER"]).write_text("late-publish")
    connection.send(("done", 0))


@pytest.mark.parametrize("worker,timeout", [(_blocked_network_worker, 3), (_slow_compute_worker, 0.8)])
def test_t2_t7_hard_deadline_reaps_worker_no_late_publish(tmp_path, monkeypatch, worker, timeout):
    marker = tmp_path / "marker"
    monkeypatch.setenv("LEARNING_TEST_MARKER", str(marker))
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    assert status.supervise(True, worker=worker, timeout=timeout) == 1
    assert time.monotonic() - started < timeout + 1.5
    assert not marker.exists()
    assert {p.pid for p in multiprocessing.active_children()} <= before


def test_t7_expired_compute_cannot_renew_timestamp_or_publish(fixture, monkeypatch):
    original = status.compute
    def slow(*args, **kwargs):
        time.sleep(0.03)
        return original(*args, **kwargs)
    monkeypatch.setattr(status, "compute", slow)
    with pytest.raises(status.StatusDeadline):
        status.inspect_status(True, status.Budget(time.monotonic() + status.OPERATION_DEADLINE + 0.01), lambda: fixture)
    fixture.child("daytrade_learning_status").set.assert_not_called()


def test_t8_root_runtime_parity():
    root = Path(status.__file__).parent
    assert (root / "learning_status.py").read_bytes() == (root / "vm_runtime/learning_status.py").read_bytes()


def test_t9_inspection_reads_only_synthetic_directory(fixture, monkeypatch):
    original_open = Path.open
    root = status.DATA.resolve()
    code = Path(status.__file__).parent.resolve()
    def safe_open(path, *args, **kwargs):
        resolved = path.resolve()
        assert resolved.is_relative_to(root) or resolved in (
            code / "learning_status_engine_hashes.json", code / "intraday_live.py")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", safe_open)
    inspect(fixture)


def test_sdk_transport_actually_consumes_timeouts_and_disables_hidden_retries(monkeypatch):
    import firebase_admin
    from firebase_admin import credentials, db
    from google.auth.credentials import AnonymousCredentials
    import firebase_store
    class Credential(credentials.Base):
        def get_credential(self):
            return AnonymousCredentials()
    monkeypatch.setattr(credentials, "Certificate", lambda _: Credential())
    monkeypatch.setattr(firebase_store, "SERVICE_ACCOUNT_FILE", "synthetic-never-opened")
    monkeypatch.setattr(firebase_store, "FIREBASE_DATABASE_URL", "https://synthetic.invalid")
    calls = []
    def send(adapter, request, **kwargs):
        calls.append((request.method, kwargs["timeout"], adapter.max_retries.total))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{}'
        response.request = request
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    # No Firebase default app is touched, even if another caller already has one.
    before = dict(firebase_admin._apps)
    reference = status.bounded_reference()
    try:
        assert reference.child("intraday_live").get() == {}
        reference.child("daytrade_learning_status").set({"complete": True})
        assert calls == [("GET", (2.0, 4.0), 0), ("PUT", (2.0, 4.0), 0)]
        auth_request = reference._client._session._auth_request
        auth_request.session.request("POST", "https://synthetic.invalid/token", timeout=120)
        assert calls[-1] == ("POST", (2.0, 4.0), 0)
    finally:
        firebase_admin.delete_app(firebase_admin.get_app("learning-status-bounded"))
    assert firebase_admin._apps == before


def test_worker_and_cli_propagate_failure_without_payload(fixture, monkeypatch, capsys):
    conn = Mock()
    monkeypatch.setattr(status, "inspect_status", Mock(side_effect=requests.ReadTimeout("SECRET")))
    status._worker(conn, True, time.monotonic() + 1)
    conn.send.assert_called_once_with(("done", 1))
    assert "SECRET" not in capsys.readouterr().err
    monkeypatch.setattr(status, "supervise", Mock(return_value=1))
    assert status.main(["--publish"]) == 1
