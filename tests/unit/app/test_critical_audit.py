"""Critical audit API, retention evidence and fail-closed capture."""

import csv
import io
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from qwenpaw.app.routers import critical_audit, security_evidence
from qwenpaw.governance.activity_middleware import (
    CriticalActivityAuditMiddleware,
    classify_operation,
)
from qwenpaw.governance.audit import AuditEvent, AuditLog
from qwenpaw.governance.audit_archive import archive
from qwenpaw.governance.audit_integrity import EVENT_FIELDS, retention_policy, verify

BASE = "/api/security/evidence/critical-audit"
ADMIN = {"X-Test-User": "operator-1"}
CALL = "a" * 32
STOP = "/api/console/chat/control/incidents/stop"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(security_evidence, "WORKING_DIR", tmp_path)
    path = tmp_path / "governance" / "audit.db"
    log = AuditLog._create(path)
    monkeypatch.setattr(AuditLog, "get_instance", lambda *a, **kw: log)
    try:
        yield log, path
    finally:
        log.close()


@pytest.fixture
def app():
    server = FastAPI()
    server.include_router(critical_audit.router, prefix="/api")
    server.include_router(security_evidence.router, prefix="/api")
    server.add_middleware(CriticalActivityAuditMiddleware)
    server.state.stop_count = 0

    @server.middleware("http")
    async def identity(request: Request, call_next):
        subject = request.headers.get("X-Test-User")
        if subject:
            request.state.access_identity = SimpleNamespace(
                user_id=subject, is_admin=subject.startswith("operator")
            )
        return await call_next(request)

    @server.post(STOP)
    async def stop(request: Request):
        if not request.state.access_identity.is_admin:
            raise HTTPException(403)
        server.state.stop_count += 1
        return {"accepted": True}

    return server


def policy(
    log, target="https://user:secret@example.test/private?a=secret", decision="allow"
):
    log._append(
        AuditEvent(
            990, "workspace", "agent-7", "session-2", "ReadFile", target, decision
        )
    )


def test_admin_only_and_no_store(app, store):
    client = TestClient(app)
    for headers in ({}, {"X-Test-User": "non-admin"}):
        assert client.get(BASE, headers=headers).status_code == 403
        assert (
            client.post(BASE + "/verify", headers=headers, json={}).status_code == 403
        )
        assert (
            client.post(
                BASE + "/export", headers=headers, json={"through_id": 0}
            ).status_code
            == 403
        )
    assert client.get(BASE, headers=ADMIN).headers["cache-control"] == "no-store"


def test_reads_do_not_create_audit_database(app, tmp_path, monkeypatch):
    monkeypatch.setattr(security_evidence, "WORKING_DIR", tmp_path)
    client = TestClient(app)
    assert client.get(BASE, headers=ADMIN).json()["storage"]["state"] == "not_created"
    assert (
        client.post(BASE + "/verify", headers=ADMIN, json={}).json()["state"]
        == "not_created"
    )
    assert not (tmp_path / "governance").exists()


def test_fields_filters_and_paging_snapshot(app, store):
    log, _ = store
    policy(log)
    log.record_execution(
        "workspace",
        agent_id="agent-9",
        session_id="s",
        tool_name="read_file",
        event_id=CALL,
        result="success",
    )
    client = TestClient(app)
    assert client.post(STOP, headers=ADMIN).status_code == 200
    page = client.get(BASE, headers=ADMIN, params={"limit": 2}).json()
    finish, start = page["records"]
    assert finish["call_id"] == start["call_id"]
    assert finish["subject"] == "operator-1" and finish["subject_kind"] == "account"
    assert (
        finish["kind"] == "governance_activity"
        and finish["operation"] == "chat.incident.stop"
    )
    assert (
        finish["target"] == STOP
        and finish["http_status"] == 200
        and finish["result"] == "http_completed"
    )
    assert start["result"] == "started"
    policy(log, decision="deny")  # this new record must not move the paging window
    params = {
        "limit": 2,
        "before_id": page["next_before_id"],
        "through_id": page["through_id"],
    }
    second = client.get(BASE, headers=ADMIN, params=params).json()
    execution, decision = second["records"]
    assert (
        execution["call_id"] == CALL
        and execution["result"] == "success"
        and execution["target"] == "read_file"
    )
    assert (
        decision["ts"] == 990
        and decision["subject"] == "agent-7"
        and decision["subject_kind"] == "agent"
    )
    assert (
        decision["target"] == "https://example.test" and decision["decision"] == "allow"
    )
    assert decision["result"] == "not_recorded"
    assert second["next_before_id"] is None
    for params in (
        {"kind": "tool_execution"},
        {"result": "success"},
        {"subject": "agent-9"},
        {"operation": "read_file"},
    ):
        only = client.get(BASE, headers=ADMIN, params=params).json()["records"]
        assert [row["id"] for row in only] == [execution["id"]]
    assert client.get(
        BASE, headers=ADMIN, params={"since": 0, "until": 990, "result": "allow"}
    ).json()["records"] == [decision]
    old = client.get(
        "/api/security/evidence/audit?kind=tool_execution", headers=ADMIN
    ).json()
    assert old["total"] == 1 and old["records"][0]["execution_result"] == "success"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"before_id": 0},
        {"since": 100, "until": 99},
        {"result": "bogus"},
    ],
)
def test_rejects_invalid_filters(app, params):
    assert TestClient(app).get(BASE, headers=ADMIN, params=params).status_code == 422


def test_export_matches_frozen_page_redacts_and_prevents_formula_injection(app, store):
    log, _ = store
    log._append(
        AuditEvent(
            1000,
            "workspace",
            "=cmd()",
            "session",
            "ReadFile",
            "private/never-export.txt",
            "allow",
        )
    )
    client = TestClient(app)
    page = client.get(BASE, headers=ADMIN).json()
    response = client.post(
        BASE + "/export", json={"through_id": page["through_id"]}, headers=ADMIN
    )
    assert (
        response.status_code == 200
        and "attachment" in response.headers["content-disposition"]
    )
    assert "never-export" not in response.text
    csv_rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert len(csv_rows) == 1 and csv_rows[0]["subject"] == "'=cmd()"
    assert csv_rows[0]["time_utc"] == "1970-01-01T00:00:01.000+00:00"
    export_rows = client.get(
        BASE, headers=ADMIN, params={"operation": "audit.export"}
    ).json()["records"]
    assert [row["result"] for row in export_rows] == ["http_completed", "started"]


def test_failed_audit_write_prevents_critical_action(app, store, monkeypatch):
    log, _ = store

    def broken(**kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(log, "record_activity", broken)
    response = TestClient(app).post(STOP, headers=ADMIN, json={})
    assert response.status_code == 503
    assert app.state.stop_count == 0


def test_denied_governance_action_is_not_logged_as_success(app, store):
    client = TestClient(app)
    assert client.post(STOP, headers={"X-Test-User": "reader1"}).status_code == 403
    latest = client.get(BASE, headers=ADMIN).json()["records"][0]
    assert (latest["subject"], latest["result"], latest["http_status"]) == (
        "reader1",
        "denied",
        403,
    )
    assert classify_operation(
        "POST", "/api/portal/controlled-documents/operations/secret/download"
    ) == (
        "document.download",
        "[ID 未记录]",
    )
    assert classify_operation(
        "POST", f"/api/portal/controlled-documents/operations/{CALL}/download"
    ) == (
        "document.download",
        CALL,
    )


def test_local_rows_are_append_only(app, store):
    log, path = store
    policy(log)
    with sqlite3.connect(path) as conn:
        for sql in (
            "DELETE FROM audit_events",
            "UPDATE audit_events SET target = 'x'",
            f"INSERT OR REPLACE INTO audit_events (rowid, {EVENT_FIELDS}) SELECT rowid, * FROM audit_events",
            "DELETE FROM audit_chain_seals",
            "UPDATE audit_chain_origin SET ledger_id = 'x'",
            "INSERT OR REPLACE INTO audit_chain_seals SELECT * FROM audit_chain_seals",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(sql)
    assert (
        TestClient(app).post(BASE + "/verify", headers=ADMIN, json={}).json()["state"]
        == "verified"
    )
    assert log.purge(10**15) == 0 and log.count == 1


def test_privileged_middle_change_is_detected_even_if_trigger_is_restored(app, store):
    log, path = store
    policy(log)
    policy(log)
    with sqlite3.connect(path) as conn:
        trigger = "audit_events_protect_update"
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (trigger,)
        ).fetchone()[0]
        conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute("UPDATE audit_events SET target = 'changed' WHERE rowid = 1")
        conn.execute(sql)
    check = TestClient(app).post(BASE + "/verify", headers=ADMIN, json={}).json()
    assert check["state"] == "mismatch" and check["first_bad_id"] == 1


def test_missing_protection_will_not_be_silently_reinstalled(app, store):
    log, path = store
    policy(log)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER audit_chain_seals_protect_delete")
    check = TestClient(app).post(BASE + "/verify", headers=ADMIN, json={}).json()
    assert check["state"] == "protection_missing"
    with pytest.raises(sqlite3.IntegrityError):
        policy(log)
    with pytest.raises(sqlite3.IntegrityError):
        AuditLog._create(path)


def test_external_checkpoint_and_wal_consistent_backup(app, store, tmp_path):
    log, path = store
    policy(log)
    client = TestClient(app)
    check = lambda value=None: client.post(
        BASE + "/verify", headers=ADMIN, json={"checkpoint": value}
    ).json()
    old = check()["checkpoint"]
    snapshot = archive(path, tmp_path, old)
    policy(log)
    current = check(old)
    assert (
        current["state"] == "verified"
        and current["external_match"]
        and current["checked_events"] == 2
    )
    with sqlite3.connect(snapshot / "audit.db") as backup:
        assert verify(backup, old)["external_match"] is True
        assert verify(backup, current["checkpoint"])["state"] == "checkpoint_mismatch"
    assert (
        client.post(
            BASE + "/verify", headers=ADMIN, json={"checkpoint": "invalid"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "configured, months, valid",
    [("6", 36, False), ("garbage", 36, False), ("72", 72, True)],
)
def test_retention_configuration_cannot_relax_defaults(
    monkeypatch, configured, months, valid
):
    monkeypatch.setenv("QWENPAW_AUDIT_EXTENDED_RETENTION_MONTHS", configured)
    policy = retention_policy()
    assert policy == {
        "minimum_months": 6,
        "extended_months": months,
        "valid_configuration": valid,
        "local_auto_purge": False,
        "archive_status": "not_verified",
    }


def test_concurrent_connections_preserve_chain(store):
    log, path = store
    other = AuditLog._create(path)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: policy(log if i % 2 else other), range(32)))
        with sqlite3.connect(path) as conn:
            assert verify(conn)["checked_events"] == 32
            assert verify(conn)["state"] == "verified"
    finally:
        other.close()
