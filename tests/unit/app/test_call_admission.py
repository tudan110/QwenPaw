"""Call admission administration and final dispatch share persistent restrictions."""
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agentscope.permission import PermissionBehavior
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app.routers import call_admission as api
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.extensions.integrations.zgops_cmdb import portal_asset_lookup
from qwenpaw.extensions.security import call_admission as policy
from qwenpaw.extensions.security import execution_policy
from qwenpaw.governance import tool_adapter
from qwenpaw.governance.tool_adapter import PolicyGuardedTool
from qwenpaw.runtime.tool_guard import GuardedFunctionTool

BASE = "/api/security/call-admission"
ADMIN = {"x-test-role": "admin", "origin": "http://testserver"}


def target(kind, name, service=""):
    return {"kind": kind, "name": name, "service": service}


def change(kind, name, service="", *, decision="deny", revision=0):
    return {
        **target(kind, name, service), "decision": decision, "revision": revision,
        "risk": "high", "reason": "本地治理验收",
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WORKING_DIR", tmp_path)
    app = FastAPI()

    @app.middleware("http")
    async def inject_verified_identity(request: Request, call_next):
        role = request.headers.get("x-test-role")
        if role:
            request.state.access_identity = SimpleNamespace(
                user_id="test-operator", is_admin=role == "admin",
            )
        return await call_next(request)

    app.include_router(api.router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


def test_access_catalog_and_no_side_effect(client):
    body = change("tool", "get_current_time")
    for headers in ({}, {"x-test-role": "user"}):
        assert client.get(BASE, headers=headers).status_code == 403
        assert client.put(BASE, headers=headers, json=body).status_code == 403
    for headers in ({**ADMIN, "origin": "https://other.invalid"},
                    {"x-test-role": "admin", "cookie": "session=fixture"}):
        assert client.put(BASE, headers=headers, json=body).status_code == 403
    response = client.get(BASE, headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    rows = response.json()["items"]
    assert {row["kind"] for row in rows} == {"tool", "script", "api", "mcp_service", "mcp_tool"}
    assert {row["risk"] for row in rows} == {"low", "medium", "high", "critical"}
    assert all(row["boundary"] and row["risk_source"] == "baseline" for row in rows)
    check = client.post(BASE + "/check", headers=ADMIN, json=target("tool", "get_current_time"))
    assert check.json()["decision"] == "inherit"
    assert not policy._path().exists()


def test_write_read_check_and_optimistic_concurrency(client):
    body = change("tool", "get_current_time")
    response = client.put(BASE, headers=ADMIN, json=body)
    assert response.status_code == 200
    row = response.json()
    assert (row["default_risk"], row["risk"], row["risk_source"], row["revision"]) == ("low", "high", "manual", 1)
    assert row in client.get(BASE, headers=ADMIN).json()["items"]
    check = client.post(BASE + "/check", headers=ADMIN, json=target("tool", "get_current_time"))
    assert check.json()["decision"] == "deny"
    assert client.put(BASE, headers=ADMIN, json=body).status_code == 409
    assert client.put(BASE, headers=ADMIN, json={**body, "revision": 1, "decision": "inherit"}).status_code == 200
    assert policy.blocked_by(policy.Target("tool", "get_current_time")) is None
    from contextlib import closing

    with closing(sqlite3.connect(policy._path())) as conn:
        assert conn.execute("SELECT updated_by, decision FROM revisions ORDER BY revision").fetchall() == [
            ("test-operator", "deny"), ("test-operator", "inherit"),
        ]


def test_quick_toggle_persists_and_preserves_risk_assessment(client):
    body = change("tool", "get_current_time")
    toggle = {**body, "risk": None}
    assert client.put(BASE, headers={"x-test-role": "user"}, json=toggle).status_code == 403
    disabled = client.put(BASE, headers=ADMIN, json=toggle).json()
    assert (disabled["decision"], disabled["risk"], disabled["risk_source"]) == ("deny", "low", "baseline")
    assert disabled in client.get(BASE, headers=ADMIN).json()["items"]
    assert policy.blocked_by(policy.Target("tool", "get_current_time"))
    assert client.put(BASE, headers=ADMIN, json=toggle).status_code == 409

    enabled = client.put(BASE, headers=ADMIN, json={**toggle, "decision": "inherit", "revision": 1}).json()
    assert (enabled["decision"], enabled["risk_source"], enabled["revision"]) == ("inherit", "baseline", 2)
    assert enabled in client.get(BASE, headers=ADMIN).json()["items"]
    assert policy.blocked_by(policy.Target("tool", "get_current_time")) is None

    assessed = client.put(BASE, headers=ADMIN, json={**body, "risk": "medium", "revision": 2}).json()
    assert assessed["risk_source"] == "manual"
    restored = client.put(BASE, headers=ADMIN, json={**toggle, "decision": "inherit", "revision": 3}).json()
    assert (restored["risk"], restored["risk_source"]) == ("medium", "manual")
    assert restored in client.get(BASE, headers=ADMIN).json()["items"]


def test_quick_toggle_works_with_legacy_manual_record(client):
    body = change("tool", "get_current_time")
    assert client.put(BASE, headers=ADMIN, json=body).status_code == 200
    restored = client.put(BASE, headers=ADMIN, json={
        **body, "decision": "inherit", "revision": 1, "risk": None,
    }).json()
    assert (restored["risk"], restored["risk_source"]) == ("high", "manual")
    assert restored in client.get(BASE, headers=ADMIN).json()["items"]


@pytest.mark.parametrize("name, params", [
    ("write_file", {"file_path": "tmp.txt", "content": "业务明细"}),
    ("execute_shell_command", {"command": "touch tmp.txt"}),
])
@pytest.mark.asyncio
async def test_quick_toggle_does_not_override_production_guards(client, monkeypatch, name, params):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    body = {**change("tool", name, decision="inherit"), "risk": None}
    assert client.put(BASE, headers=ADMIN, json=body).status_code == 200
    assert client.post(BASE + "/check", headers=ADMIN, json=target("tool", name)).json()["decision"] == "inherit"
    with pytest.raises(PermissionError):
        await execution_policy.check_tool(name, params)


@pytest.mark.parametrize("patch", [
    {"decision": "allow"}, {"risk": "unknown"}, {"reason": "  "},
    {"kind": "api", "name": "unknown"}, {"kind": "mcp_tool"},
    {"name": "https://other.invalid"}, {"name": "*"}, {"bypass": True},
    {"service": "unrelated"}, {"name": policy.CMDB_LOOKUP},
])
def test_reject_invalid_or_unsupported_rules(client, patch):
    response = client.put(BASE, headers=ADMIN, json={**change("tool", "get_current_time"), **patch})
    assert response.status_code == 422
    assert not policy._path().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapper", [PolicyGuardedTool, GuardedFunctionTool])
async def test_agent_dispatch_rechecks_after_permission(client, monkeypatch, wrapper):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    monkeypatch.setattr(tool_adapter, "_is_execution_level_off", lambda: True)
    ran = []

    async def synthetic_clock():
        ran.append(True)

    instance = wrapper(synthetic_clock)
    admitted = await instance.check_permissions({})
    assert admitted.behavior == PermissionBehavior.ALLOW
    assert client.put(BASE, headers=ADMIN, json=change("tool", "synthetic_clock")).status_code == 200
    denied = await instance.check_permissions({})
    assert denied.behavior == PermissionBehavior.DENY
    with pytest.raises(PermissionError, match="调用准入"):
        await instance()
    assert not ran


@pytest.mark.asyncio
async def test_inherit_cannot_grant_unknown_production_tool(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    assert client.put(BASE, headers=ADMIN, json=change("tool", "unknown_operation", decision="inherit")).status_code == 200

    async def unknown_operation():
        pytest.fail("Unclassified tool must not run")

    decision = await PolicyGuardedTool(unknown_operation).check_permissions({})
    assert decision.behavior == PermissionBehavior.DENY
    assert "可信 AI 管理员" in decision.message


@pytest.mark.asyncio
async def test_cmdb_block_before_network(client, monkeypatch):
    no_request = AsyncMock(side_effect=AssertionError("should not access upstream"))
    monkeypatch.setattr(portal_asset_lookup.httpx.AsyncClient, "get", no_request)
    assert client.put(BASE, headers=ADMIN, json=change("api", policy.CMDB_LOOKUP)).status_code == 200
    with pytest.raises(PermissionError, match="调用准入"):
        await portal_asset_lookup.lookup_portal_cmdb_asset("synthetic-asset")
    no_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_dispatch_is_exact_and_service_denial_overrides_tool(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    outgoing = AsyncMock(return_value="synthetic result")

    def mcp(service):
        driver = object.__new__(MCPDriverHandler)
        driver._card = SimpleNamespace(name=service)
        driver._client = SimpleNamespace(call_tool=outgoing)
        return driver

    left, right = mcp("left"), mcp("right")
    body = change("mcp_tool", "lookup", "left")
    assert client.put(BASE, headers=ADMIN, json=body).status_code == 200
    with pytest.raises(PermissionError, match="调用准入"):
        await left._execute(None, None, tool_name="lookup")
    outgoing.assert_not_awaited()
    assert await right._execute(None, None, tool_name="lookup") == "synthetic result"
    outgoing.assert_awaited_once_with("lookup", {})
    assert client.put(BASE, headers=ADMIN, json={**body, "decision": "inherit", "revision": 1}).status_code == 200
    assert client.put(BASE, headers=ADMIN, json=change("mcp_service", "left")).status_code == 200
    with pytest.raises(PermissionError, match="调用准入"):
        await left._execute(None, None, tool_name="lookup")
    assert await left.list_capabilities() == []
    check = client.post(BASE + "/check", headers=ADMIN, json=target("mcp_tool", "lookup", "left"))
    assert check.json()["blocked_by"] == "left"


def test_managed_script_and_parent_restrictions(client, tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    script = tmp_path / "get_alarms.py"
    script.write_text("print('synthetic data')", encoding="utf-8")
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", json.dumps({
        str(script): hashlib.sha256(script.read_bytes()).hexdigest(),
    }))
    command = "python get_alarms.py"
    assert execution_policy.check_shell(command, tmp_path) is False
    assert client.put(BASE, headers=ADMIN, json=change("script", script.name)).status_code == 200
    with pytest.raises(PermissionError, match="调用准入"):
        execution_policy.check_shell(command, tmp_path)
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    response = client.post(BASE + "/check", headers=ADMIN, json=target("script", script.name))
    assert response.json()["decision"] == "inactive"
    assert client.put(BASE, headers=ADMIN, json=change("tool", "execute_shell_command")).status_code == 200
    response = client.post(BASE + "/check", headers=ADMIN, json=target("script", script.name))
    assert response.json()["blocked_by"] == "execute_shell_command"


def test_unreadable_rules_fail_closed(client):
    path = policy._path()
    path.parent.mkdir()
    path.write_text("not a database", encoding="utf-8")
    assert client.get(BASE, headers=ADMIN).status_code == 503
    with pytest.raises(PermissionError, match="不可读取"):
        policy.require_agent_tool("get_current_time")


@pytest.mark.asyncio
async def test_script_deny_saved_during_dispatch_authorization(client, tmp_path, monkeypatch):
    from qwenpaw.extensions.security import portal_capabilities

    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    script = tmp_path / "get_alarms.py"
    script.write_text("# synthetic", encoding="utf-8")
    monkeypatch.setenv("QWENPAW_ALLOWED_SCRIPT_HASHES", json.dumps({
        str(script): hashlib.sha256(script.read_bytes()).hexdigest(),
    }))

    async def check_skills(*args, dispatch=False, **kwargs):
        assert dispatch
        assert client.put(BASE, headers=ADMIN, json=change("script", script.name)).status_code == 200

    async def execute_shell_command(command: str, cwd: str):
        pytest.fail("The script deny must be checked immediately before dispatch")

    monkeypatch.setattr(portal_capabilities, "check_tool_skills", check_skills)
    with pytest.raises(PermissionError, match="调用准入"):
        await PolicyGuardedTool(execute_shell_command)(command="python get_alarms.py", cwd=str(tmp_path))
