# -*- coding: utf-8 -*-
"""Evidence endpoints must remain authenticated, truthful and read-only."""

import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app.routers import security_evidence as evidence
from qwenpaw.extensions.security import output_guard
from qwenpaw.extensions.security.output_guard.redactor import (
    OutputGuardSettings,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "WORKING_DIR", tmp_path)
    app = FastAPI()

    @app.middleware("http")
    async def test_identity(request: Request, call_next):
        role = request.headers.get("X-Test-Role")
        if role:
            request.state.access_identity = SimpleNamespace(
                is_admin=role == "admin",
            )
        return await call_next(request)

    app.include_router(evidence.router, prefix="/api")
    return TestClient(app)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "governance" / "audit.db"
    path.parent.mkdir()
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE audit_events (ts INTEGER, workspace_dir TEXT, "
        "agent_id TEXT, session_id TEXT, tool_name TEXT, target TEXT, "
        "decision TEXT, reason TEXT, extra TEXT)",
    )
    conn.executemany(
        "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                1000,
                "private/workspace",
                "agent-a",
                "session-a",
                "read_file",
                "https://user:secret@demo.invalid/p?key=hidden",
                "allow",
                "Authorization: Bearer do-not-expose",
                '{"token": "extra-secret"}',
            ),
            (
                2000,
                "private/workspace",
                "agent-b",
                "session-b",
                "execute_shell_command",
                "curl --token positional-secret",
                "deny",
                "password=reason-secret",
                "{}",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return path


BASE = "/api/security/evidence"
ADMIN = {"X-Test-Role": "admin"}


@pytest.mark.parametrize("role", [None, "user"])
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/audit"),
        ("GET", "/protection"),
        ("POST", "/redaction-check"),
    ],
)
def test_unverified_and_non_admin_cannot_read(client, role, method, path):
    headers = {"X-Test-Role": role} if role else {}
    assert (
        client.request(method, BASE + path, headers=headers).status_code == 403
    )


def test_absent_database_is_not_created(client, tmp_path):
    response = client.get(BASE + "/audit", headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["storage_status"] == "not_created"
    assert response.json()["records"] == []
    assert not (tmp_path / "governance").exists()


def test_query_is_readonly_redacted_and_not_execution_success(
    client, database
):
    before = database.read_bytes()
    response = client.get(BASE + "/audit", headers=ADMIN)
    data = response.json()
    assert response.status_code == 200
    assert database.read_bytes() == before
    assert data["total"] == 2
    assert data["record_kind"] == "policy_decision"
    assert data["execution_result"] == "not_recorded"
    assert [row["decision"] for row in data["records"]] == ["deny", "allow"]
    text = response.text
    for secret in (
        "extra-secret",
        "reason-secret",
        "positional-secret",
        "do-not-expose",
        "private/workspace",
        "?key=hidden",
    ):
        assert secret not in text
    assert data["records"][1]["target"] == "https://demo.invalid"


def test_filters_pagination_and_parameter_binding(client, database):
    for query in (
        "agent_id=agent-a",
        "tool_name=read_file",
        "decision=allow",
        "since=0&until=1500",
    ):
        data = client.get(BASE + "/audit?" + query, headers=ADMIN).json()
        assert data["total"] == 1
        assert data["records"][0]["agent_id"] == "agent-a"
    data = client.get(BASE + "/audit?limit=1&offset=1", headers=ADMIN).json()
    assert data["total"] == 2 and len(data["records"]) == 1
    result = client.get(
        BASE + "/audit",
        params={"tool_name": "' OR 1=1 --"},
        headers=ADMIN,
    )
    assert result.json()["total"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "limit=201",
        "limit=0",
        "offset=-1",
        "offset=100001",
        "since=-1",
        "since=2000&until=1000",
        "decision=success",
    ],
)
def test_invalid_or_unbounded_query_is_rejected(client, query):
    assert (
        client.get(BASE + "/audit?" + query, headers=ADMIN).status_code == 422
    )


def test_legacy_database_is_preserved(client, database):
    conn = sqlite3.connect(database)
    conn.execute("ALTER TABLE audit_events RENAME TO original_events")
    conn.execute("CREATE TABLE audit_events (ts TEXT)")
    conn.execute("INSERT INTO audit_events VALUES ('keep-me')")
    conn.commit()
    conn.close()
    before = database.read_bytes()
    data = client.get(BASE + "/audit", headers=ADMIN).json()
    assert data["storage_status"] == "unsupported_schema"
    assert database.read_bytes() == before


def test_broken_storage_is_error_not_empty_success(client, tmp_path):
    directory = tmp_path / "governance"
    directory.mkdir()
    (directory / "audit.db").write_bytes(b"not a database")
    assert client.get(BASE + "/audit", headers=ADMIN).status_code == 503


def test_fixed_sample_check_respects_disabled_guard(client, monkeypatch):
    monkeypatch.setattr(
        output_guard,
        "load_config",
        lambda: OutputGuardSettings(
            enabled=False,
        ),
    )
    data = client.post(BASE + "/redaction-check", headers=ADMIN).json()
    assert data["scope"] == "synthetic_redactor_only"
    assert data["active"] is False
    assert all(
        not row["changed"] and not row["hit_ids"] for row in data["results"]
    )


def test_samples_return_actual_results_without_altering_configuration(
    client,
    monkeypatch,
):
    settings = OutputGuardSettings()
    monkeypatch.setattr(output_guard, "load_config", lambda: settings)
    data = client.post(BASE + "/redaction-check", headers=ADMIN).json()
    assert data["active"] is True
    assert data["results"][0]["changed"] is True
    assert "openai_dashscope_key" in data["results"][0]["hit_ids"]
    assert data["results"][-1]["changed"] is False
    assert output_guard.load_config() is settings


def test_config_snapshot_has_no_lexicon_path_or_values(client, monkeypatch):
    monkeypatch.setattr(
        output_guard,
        "load_config",
        lambda: OutputGuardSettings(
            lexicon_path="private/secret.yaml",
            disabled_patterns=("openai_dashscope_key",),
        ),
    )
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "one.invalid,two.invalid,")
    response = client.get(BASE + "/protection", headers=ADMIN)
    data = response.json()
    assert data["scope"] == "resolved_configuration_only"
    assert data["output_guard"]["lexicon"] == "custom"
    assert "private/secret.yaml" not in response.text
    assert "one.invalid" not in response.text
    assert data["mcp_boundary"] == {
        "production_guards": False,
        "declared_host_count": 2,
    }
    assert (
        next(
            row
            for row in data["output_guard"]["patterns"]
            if row["id"] == "openai_dashscope_key"
        )["enabled"]
        is False
    )


@pytest.mark.parametrize(
    "value,secret",
    [
        ("Authorization: Bearer ordinary-secret", "ordinary-secret"),
        ("Authorization: Basic encoded-secret", "encoded-secret"),
        ("password='secret with spaces'", "secret with spaces"),
        ("curl --access-token cli-secret", "cli-secret"),
        (
            "https://name:url-secret@demo.invalid/path-secret"
            "?token=query-secret",
            "path-secret",
        ),
    ],
)
def test_free_text_redaction(value, secret):
    assert secret not in evidence.safe_text(value)


def test_execution_view_contains_only_observed_status(client, database):
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (3000, "private/workspace", "agent-a", "session-a", "read_file",
             "read_file", "", "",
             '{"auth_user_id":"u1","kind":"tool_execution","result":"error",'
             '"call_id":"0123456789abcdef0123456789abcdef","token":"secret-value"}'),
        )
    result = client.get(BASE + "/audit", params={"kind": "tool_execution"}, headers=ADMIN)
    assert result.status_code == 200
    assert "secret-value" not in result.text
    data = result.json()
    assert data["total"] == 1 and data["record_kind"] == "tool_execution"
    assert data["records"][0]["execution_result"] == "error"
    assert data["records"][0]["subject"] == "u1"
    assert data["records"][0]["call_id"] == "0123456789abcdef0123456789abcdef"
    assert client.get(BASE + "/audit", headers=ADMIN).json()["total"] == 2
