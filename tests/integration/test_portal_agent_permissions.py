"""Exercise the human consent boundary on the real MCP Driver invocation."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app.routers import agent_permissions
from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import PolicyRule
from qwenpaw.extensions.api import traces_backend
from qwenpaw.extensions.api.access_session import AccessIdentity, AccessSessionStore, CURRENT_IDENTITY
from qwenpaw.extensions.api.chat_isolation import chat_scope
from qwenpaw.extensions.security import portal_capabilities as permissions
from qwenpaw.extensions.traceability import trace_store
from tests.integration.driver_mcp_fakes import FakeStdIOClient, patch_mcp_runtime_clients
from tests.integration.test_driver_mcp_policy_flow import _registry_with_policy


@pytest.fixture
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    db = AccessSessionStore(tmp_path / "private.db")
    monkeypatch.setattr(permissions, "get_access_store", lambda: db)
    trace_dir = tmp_path / "trace"
    monkeypatch.setattr(trace_store, "_TRACE_DIR", trace_dir)
    monkeypatch.setattr(trace_store, "_INDEX_PATH", trace_dir / "_index.json")


def user_scope(user: str, agent: str, session: str):
    token = CURRENT_IDENTITY.set(AccessIdentity({"userId": user}, "test-user-token"))
    try:
        scope = chat_scope()
        return permissions.PortalInvocation(scope.owner, agent, scope.session_id(session))
    finally:
        CURRENT_IDENTITY.reset(token)


@pytest.mark.parametrize("answer", ["allow", "deny", "revoke"])
async def test_mcp_consent_controls_real_client_and_stays_owner_scoped(tmp_path, monkeypatch, isolate, answer):
    patch_mcp_runtime_clients(monkeypatch)
    manager = await _registry_with_policy(tmp_path, [PolicyRule(subject="*", effect="allow")])
    capability = next(item for item in await manager.list_capabilities(kind="tool") if item.name == "echo")
    workspace = SimpleNamespace(agent_id="gateway", workspace_dir=tmp_path, driver_manager=manager)
    monkeypatch.setattr(agent_permissions, "get_agent_for_request", AsyncMock(return_value=workspace))
    monkeypatch.setattr(agent_permissions, "resolve_effective_skills", lambda *_: ["zgops-cmdb"])
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        caller = request.headers["X-Test-User"]
        token = CURRENT_IDENTITY.set(AccessIdentity({"userId": caller}, "test-user-token"))
        try:
            return await call_next(request)
        finally:
            CURRENT_IDENTITY.reset(token)

    app.include_router(agent_permissions.router, prefix="/api")
    app.include_router(traces_backend.router)
    alice = user_scope("A", "gateway", "chat-1")
    task = asyncio.create_task(manager.invoke_capability(DriverInvocation(
        capability.capability_id, {"text": "private-input"}, {permissions.CONTEXT_KEY: alice},
    )))
    prefix = "/api/portal/agent-permissions"
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(50):
                response = await client.get(f"{prefix}/requests", params={"session_id": "chat-1"}, headers={"X-Test-User": "A"})
                queue = response.json()["items"]
                if queue:
                    break
                if task.done():
                    pytest.fail(f"MCP returned before consent: {task.result()}")
                await asyncio.sleep(0.04)
            assert queue and FakeStdIOClient.instances[0].calls == []
            request_id = queue[0]["id"]
            assert "private-input" not in json.dumps(queue)
            payload = {"session_id": "chat-1", "decision": "allow"}
            assert (await client.post(f"{prefix}/requests/{request_id}", json=payload,
                                      headers={"X-Test-User": "B"})).status_code == 409
            if answer == "revoke":
                result = await client.post(prefix, json={"kind": "mcp", "name": "policy_echo", "mode": "revoked"}, headers={"X-Test-User": "A"})
                assert result.status_code == 200
                options = (await client.get(prefix, headers={"X-Test-User": "B"})).json()["items"]
                assert next(item for item in options if item["kind"] == "mcp")["mode"] == "ask"
            else:
                payload["decision"] = answer
                assert (await client.post(f"{prefix}/requests/{request_id}", json=payload,
                                          headers={"X-Test-User": "A"})).status_code == 200
            result = await asyncio.wait_for(task, 3)
            assert result.ok is (answer == "allow")
            calls = FakeStdIOClient.instances[0].calls
            assert calls == ([("echo", {"text": "private-input"})] if answer == "allow" else [])
            trace = f"/api/portal/traces/sessions/{alice.session}"
            events = (await client.get(trace, headers={"X-Test-User": "A"})).json()["events"]
            assert [event["decision"] for event in events] == ["pending", "allow" if answer == "allow" else "deny"]
            assert events[0]["authorization_id"] == events[1]["authorization_id"]
            assert (await client.get(trace, headers={"X-Test-User": "B"})).status_code == 404
            index = await client.get("/api/portal/traces/sessions", headers={"X-Test-User": "B"})
            assert index.json()["total"] == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await manager.shutdown_all()


async def test_expired_skill_grant_rejects_a_queued_cmdb_or_script(isolate, tmp_path, monkeypatch):
    alice = user_scope("A", "gateway", "chat-1")
    bob = user_scope("B", "gateway", "chat-1")
    context = {permissions.CONTEXT_KEY: alice, "_portal_workspace_dir": str(tmp_path)}
    now = [100.0]
    monkeypatch.setattr(permissions, "time", SimpleNamespace(time=lambda: now[0]))
    permissions.change(alice.owner, alice.agent, "skill", "zgops-cmdb", "temporary")
    await permissions.check_tool_skills(context, "lookup_portal_cmdb_asset", {})
    now[0] += permissions.TEMP_SECONDS + 1
    with pytest.raises(PermissionError, match="zgops-cmdb"):
        await permissions.check_tool_skills(context, "lookup_portal_cmdb_asset", {}, dispatch=True)
    with pytest.raises(PermissionError, match="zgops-cmdb"):
        await permissions.check_tool_skills(context, "execute_shell_command", {"command": "python skills/zgops-cmdb/scripts/cmdb_read.py query"}, dispatch=True)
    assert permissions.decision(bob, "skill", "zgops-cmdb")[0] == "inherited"


async def test_revoked_skill_cannot_be_injected_by_slash_command(isolate, tmp_path, monkeypatch):
    from qwenpaw.agents.skill_system import registry
    from qwenpaw.runtime.builtin_commands import _skill_fallback_handler

    alice = user_scope("A", "gateway", "chat-1")
    skill_dir = tmp_path / "skills" / "zgops-cmdb"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# only enabled users see this", encoding="utf-8")
    monkeypatch.setattr(registry, "resolve_effective_skills", lambda *_: ["zgops-cmdb"])
    request = SimpleNamespace(user_id=alice.owner, channel="console", channel_meta={"portal_human_session": True})
    ctx = SimpleNamespace(request=request, agent_id=alice.agent, session_id=alice.session,
                          workspace=SimpleNamespace(workspace_dir=tmp_path))
    permissions.change(alice.owner, alice.agent, "skill", "zgops-cmdb", "revoked")
    response = await _skill_fallback_handler("/zgops-cmdb 查询测试资产", ctx)
    assert "本次未使用该 Skill" in response.get_text_content()
