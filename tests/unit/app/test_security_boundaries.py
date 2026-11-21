# -*- coding: utf-8 -*-
"""Safe reads, no-effect rule checks, and audited live configuration."""

import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app.routers import security_boundaries as boundaries
from qwenpaw.config import utils
from qwenpaw.extensions.api.delete_block_middleware import DeleteBlockMiddleware

BASE = "/api/security/boundaries"
CHECK = BASE + "/delete-protection/check"
ENABLE = BASE + "/delete-protection/enable"
CONFIGURE = BASE + "/delete-protection/configure"
ADMIN = {"X-Test-Role": "admin"}
CONFIRM = {"confirm": "启用全局删除保护"}
ENABLE_POLICY = {**CONFIRM, "blocked": True, "expected_blocked": False}
RELEASE_POLICY = {
    "confirm": "解除全局删除保护", "blocked": False, "expected_blocked": True,
}


@pytest.fixture
def sample(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "security": {"delete_ops_disabled": False},
        "unrelated_setting": {"saved": True},
    }), encoding="utf-8")
    monkeypatch.setattr(utils, "get_config_path", lambda: path)
    monkeypatch.setattr(utils, "_config_cache", None)
    monkeypatch.setattr(utils, "_config_mtime", None)
    monkeypatch.delenv("QWENPAW_DELETE_OPS_DISABLED", raising=False)
    monkeypatch.delenv("COPAW_DELETE_OPS_DISABLED", raising=False)
    from qwenpaw.config.online_boundary_settings import ENV
    from qwenpaw.security.tool_guard import engine

    monkeypatch.setattr(engine, "_engine_instance", None)
    policy_envs = {name for fields in ENV.values() for name, _ in fields}
    for name in policy_envs | {"QWENPAW_PRODUCTION_GUARDS", "QWENPAW_MCP_ALLOWED_HOSTS"}:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.replace("QWENPAW_", "COPAW_", 1), raising=False)
    app = FastAPI()
    app.add_middleware(DeleteBlockMiddleware)

    @app.middleware("http")
    async def identity(request: Request, call_next):
        role = request.headers.get("X-Test-Role")
        if role:
            request.state.access_identity = SimpleNamespace(
                user_id="test-user", is_admin=role == "admin",
            )
        return await call_next(request)

    @app.delete("/api/dummy")
    def remove_dummy():
        return {"allowed_by_global_policy": True}

    app.include_router(boundaries.router, prefix="/api")
    with TestClient(app) as client:
        yield client, path


def test_snapshot_admin_only_and_no_configuration_secrets(sample, monkeypatch):
    client, _ = sample
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "secret-host.invalid")
    for headers in ({}, {"X-Test-Role": "user"}):
        assert client.get(BASE, headers=headers).status_code == 403
        assert client.get(CHECK, headers=headers).status_code == 403
    response = client.get(BASE, headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "secret-host.invalid" not in response.text
    assert response.json()["delete_protection"] == {
        "blocked": False, "source": "config_or_default",
        "editable": True, "locked_reason": None,
    }


def test_enable_persists_without_changing_other_keys_and_takes_effect(
    sample, caplog, capture_qwenpaw_logs,
):
    client, path = sample
    assert client.delete("/api/dummy").status_code == 200
    assert client.get(CHECK, headers=ADMIN).json()["decision"] == "not_blocked"
    result = client.post(ENABLE, headers=ADMIN, json=CONFIRM)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "delete_protection": {"blocked": True, "source": "config_or_default"},
        "changed": True,
    }
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "security": {"delete_ops_disabled": True},
        "unrelated_setting": {"saved": True},
    }
    assert "actor='test-user' action=enable_delete_protection" in caplog.text
    assert client.delete("/api/dummy").status_code == 403
    assert client.get(CHECK, headers=ADMIN).json()["decision"] == "blocked"
    assert not client.post(ENABLE, headers=ADMIN, json=CONFIRM).json()["changed"]


def test_confirm_admin_and_origin_required(sample, monkeypatch):
    client, path = sample
    monkeypatch.setenv("QWENPAW_BROWSER_ORIGINS", "http://testserver")
    original = path.read_bytes()
    assert client.post(ENABLE, headers={"X-Test-Role": "user"}, json=CONFIRM).status_code == 403
    assert client.post(ENABLE, headers={**ADMIN, "Origin": "https://untrusted.invalid"}, json=CONFIRM).status_code == 403
    assert client.post(ENABLE, headers=ADMIN, json={"confirm": "false"}).status_code == 422
    assert client.post(ENABLE, headers=ADMIN, json={**CONFIRM, "enabled": False}).status_code == 422
    assert path.read_bytes() == original


def test_environment_override_cannot_be_changed_in_portal(sample, monkeypatch):
    client, path = sample
    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "false")
    original = path.read_bytes()
    snapshot = client.get(BASE, headers=ADMIN).json()["delete_protection"]
    assert snapshot["source"] == "environment"
    assert snapshot["blocked"] is False
    assert snapshot["editable"] is False
    assert "QWENPAW_DELETE_OPS_DISABLED" in snapshot["locked_reason"]
    response = client.post(ENABLE, headers=ADMIN, json=CONFIRM)
    assert response.status_code == 409
    assert path.read_bytes() == original
    assert client.get(CHECK, headers=ADMIN).json()["decision"] == "not_blocked"
    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "true")
    assert client.get(CHECK, headers=ADMIN).json()["decision"] == "blocked"


def test_unsupported_config_representation_is_not_rewritten(sample):
    client, path = sample
    original = b'{"security":{"delete_ops_disabled":"false"}}'
    path.write_bytes(original)
    assert client.post(ENABLE, headers=ADMIN, json=CONFIRM).status_code == 409
    assert path.read_bytes() == original



def test_configure_both_directions_updates_actual_guards_and_audits_actor(
    sample, caplog, capture_qwenpaw_logs,
):
    from qwenpaw.extensions.integrations.knowledge_source_control import (
        check_source_operation_policy,
    )

    client, path = sample
    headers = {**ADMIN, "Origin": "http://testserver"}
    guard = "/api/dummy"
    for payload, blocked in ((ENABLE_POLICY, True), (RELEASE_POLICY, False)):
        result = client.post(CONFIGURE, headers=headers, json=payload)
        assert result.status_code == 200, result.text
        assert result.json() == {
            "delete_protection": {
                "blocked": blocked, "source": "config_or_default",
                "editable": True, "locked_reason": None,
            },
            "changed": True,
        }
        assert client.delete(guard).status_code == (403 if blocked else 200)
        assert client.get(CHECK, headers=ADMIN).json()["decision"] == (
            "blocked" if blocked else "not_blocked"
        )
        check_source_operation_policy("archive")
        assert json.loads(path.read_bytes()) == {
            "security": {"delete_ops_disabled": blocked},
            "unrelated_setting": {"saved": True},
        }
    assert "actor='test-user' action=enable_delete_protection" in caplog.text
    assert "actor='test-user' action=disable_delete_protection" in caplog.text


def test_cannot_release_from_untrusted_session_or_with_stale_or_invalid_input(
    sample, monkeypatch,
):
    client, path = sample
    monkeypatch.setenv("QWENPAW_BROWSER_ORIGINS", "http://testserver")
    assert client.post(CONFIGURE, headers=ADMIN, json=ENABLE_POLICY).status_code == 200
    original = path.read_bytes()
    for headers in (
        {}, {"X-Test-Role": "user"}, {**ADMIN, "Origin": "https://untrusted.invalid"},
        {**ADMIN, "Cookie": "session=fixture"},
    ):
        assert client.post(CONFIGURE, headers=headers, json=RELEASE_POLICY).status_code == 403
    for payload in (
        {**RELEASE_POLICY, "confirm": CONFIRM["confirm"]},
        {**RELEASE_POLICY, "blocked": "false"},
        {**RELEASE_POLICY, "unexpected": True},
    ):
        assert client.post(CONFIGURE, headers=ADMIN, json=payload).status_code == 422
    assert client.post(CONFIGURE, headers=ADMIN, json=ENABLE_POLICY).status_code == 409
    assert path.read_bytes() == original


def test_deployment_lock_disallows_release_even_if_config_writable(sample, monkeypatch):
    client, path = sample
    monkeypatch.setenv("QWENPAW_DELETE_OPS_DISABLED", "true")
    original = path.read_bytes()
    response = client.post(CONFIGURE, headers=ADMIN, json=RELEASE_POLICY)
    assert response.status_code == 409
    assert "QWENPAW_DELETE_OPS_DISABLED" in response.json()["detail"]
    assert path.read_bytes() == original
    assert client.delete("/api/dummy").status_code == 403


@pytest.mark.parametrize("original", [None, b'{"security":{}}', b'{"extra":1}'])
def test_release_default_guard_without_losing_other_fields(sample, original):
    client, path = sample
    if original is None:
        path.unlink()
    else:
        path.write_bytes(original)
    snapshot = client.get(BASE, headers=ADMIN).json()["delete_protection"]
    assert snapshot["blocked"] is True and snapshot["editable"] is True
    assert client.post(CONFIGURE, headers=ADMIN, json=RELEASE_POLICY).status_code == 200
    saved = json.loads(path.read_bytes())
    assert saved == {
        **(json.loads(original) if original else {}),
        "security": {"delete_ops_disabled": False},
    }


@pytest.mark.parametrize("original", [b'{"security":', b'{"security":null}', b'[]'])
def test_recovered_config_is_not_eligible_for_online_release(sample, original):
    client, path = sample
    path.write_bytes(original)
    snapshot = client.get(BASE, headers=ADMIN).json()["delete_protection"]
    assert snapshot["blocked"] is True and snapshot["editable"] is False
    assert client.post(CONFIGURE, headers=ADMIN, json=RELEASE_POLICY).status_code == 409
    assert path.read_bytes() == original


def test_save_requires_effective_readback(sample, monkeypatch):
    client, _ = sample
    monkeypatch.setattr(boundaries, "configure_delete_protection", lambda **kw: True)
    result = client.post(CONFIGURE, headers=ADMIN, json=ENABLE_POLICY)
    assert result.status_code == 409
    assert "未能确认变更已生效" in result.json()["detail"]



def configure_boundary(client, key, current, target, headers=ADMIN, **extra):
    return client.post(
        f"{BASE}/settings/{key}/configure", headers=headers,
        json={"expected": current, "value": target, "confirm": "确认变更安全边界", **extra},
    )


def control(client, key):
    return client.get(BASE, headers=ADMIN).json()["controls"][key]


def test_existing_config_boundaries_update_runtime_without_replacing_other_settings(
    sample, caplog, capture_qwenpaw_logs,
):
    from qwenpaw.extensions.api.domain_guard import load_config as domain_settings
    from qwenpaw.extensions.security.output_guard import load_config as output_settings
    from qwenpaw.security.skill_scanner import _get_scan_mode
    from qwenpaw.security.tool_guard.engine import get_guard_engine

    client, path = sample
    config = json.loads(path.read_bytes())
    config["security"]["output_guard"] = {"mask_streaming": False}
    config["security"]["skill_scanner"] = {"timeout": 50}
    path.write_text(json.dumps(config), encoding="utf-8")
    engine = get_guard_engine()
    scenarios = [
        ("tool_guard", True, False, lambda: engine.enabled),
        ("skill_scan", "warn", "block", _get_scan_mode),
        ("domain_guard", "block", "warn", lambda: domain_settings().mode),
        ("output_masking", True, False, lambda: output_settings().active),
    ]
    for key, old, new, live in scenarios:
        assert control(client, key) == {"value": old, "locked_reason": None}
        response = configure_boundary(client, key, old, new)
        assert response.status_code == 200, response.text
        assert live() == new
        assert control(client, key)["value"] == new
        assert f"actor='test-user' action=configure_boundary key={key}" in caplog.text
    stored = json.loads(path.read_bytes())
    assert stored["unrelated_setting"] == {"saved": True}
    assert stored["security"]["output_guard"]["mask_streaming"] is False
    assert stored["security"]["skill_scanner"]["timeout"] == 50
    assert stored["security"]["delete_ops_disabled"] is False


def test_online_policy_requires_admin_origin_fresh_state_and_valid_payload(sample, monkeypatch):
    client, path = sample
    original = path.read_bytes()
    for headers in ({}, {"X-Test-Role": "user"}, {**ADMIN, "Origin": "https://untrusted.invalid"}):
        assert configure_boundary(client, "skill_scan", "warn", "off", headers).status_code == 403
    assert configure_boundary(client, "skill_scan", "warn", False).status_code == 409
    assert configure_boundary(client, "skill_scan", "off", "block").status_code == 409
    assert configure_boundary(client, "skill_scan", "warn", "off", confirm="skip").status_code == 422
    assert configure_boundary(client, "production_guards", True, False).status_code == 422
    monkeypatch.setenv("COPAW_SKILL_SCAN_MODE", "block")
    assert "QWENPAW_SKILL_SCAN_MODE" in control(client, "skill_scan")["locked_reason"]
    assert configure_boundary(client, "skill_scan", "block", "off").status_code == 409
    assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_online_chat_and_document_flags_drive_actual_gates(sample, monkeypatch):
    from qwenpaw.app.routers.controlled_documents import current_actor
    from qwenpaw.extensions.api import chat_isolation, trusted_chat_text
    from qwenpaw.config.runtime_boundary_policy import policy_path

    client, path = sample
    original = path.read_bytes()
    assert configure_boundary(client, "text_guard", False, True).status_code == 409
    assert chat_isolation.chat_scope() is None
    assert configure_boundary(client, "chat_isolation", False, True).status_code == 200
    with pytest.raises(HTTPException) as isolated:
        chat_isolation.chat_scope()
    assert isolated.value.status_code == 401
    assert "不允许在线关闭" in control(client, "chat_isolation")["locked_reason"]
    assert configure_boundary(client, "chat_isolation", True, False).status_code == 409
    assert configure_boundary(client, "text_guard", False, True).status_code == 200
    with pytest.raises(HTTPException) as text:
        await trusted_chat_text.check_portal_input([], isolated=False)
    assert text.value.status_code == 503
    assert configure_boundary(client, "text_guard", True, False).status_code == 200
    await trusted_chat_text.check_portal_input([], isolated=False)

    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    with pytest.raises(HTTPException) as entry:
        await anext(current_actor(request, Response()))
    assert entry.value.status_code == 404
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    assert configure_boundary(client, "controlled_documents", False, True).status_code == 409
    monkeypatch.delenv("QWENPAW_PRODUCTION_GUARDS")
    assert configure_boundary(client, "controlled_documents", False, True).status_code == 200
    with pytest.raises(HTTPException) as auth:
        await anext(current_actor(request, Response()))
    assert auth.value.status_code in {401, 403}
    assert json.loads(policy_path().read_bytes()) == {
        "chat_isolation": True, "text_guard": False, "controlled_documents": True,
    }
    assert path.read_bytes() == original


def test_online_mcp_list_intersects_deployment_trust_and_updates_request_gate(sample, monkeypatch):
    from qwenpaw.extensions.security.mcp_boundary import validate_endpoint, validate_remote_request

    client, _ = sample
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "mcp-fixture.invalid")
    endpoint = {"transport": "sse", "url": "https://mcp-fixture.invalid/sse"}
    validate_endpoint(endpoint)
    for url in ("https://unapproved.invalid/sse", "https://user:secret@mcp-fixture.invalid/sse", "https://mcp-fixture.invalid/sse?key=secret"):
        assert configure_boundary(client, "mcp_remote", None, [{**endpoint, "url": url}]).status_code == 409
    assert configure_boundary(client, "mcp_remote", None, [endpoint, endpoint]).status_code == 409
    denied = "https://mcp-fixture.invalid/other"
    assert configure_boundary(client, "mcp_remote", None, [endpoint]).status_code == 200
    validate_endpoint(endpoint)
    validate_remote_request("sse", endpoint["url"])
    with pytest.raises(PermissionError):
        validate_remote_request("sse", denied)
    with pytest.raises(PermissionError):
        validate_endpoint({**endpoint, "url": denied})
    monkeypatch.delenv("QWENPAW_MCP_ALLOWED_HOSTS")
    with pytest.raises(PermissionError):
        validate_endpoint(endpoint)
    assert configure_boundary(client, "mcp_remote", [endpoint], []).status_code == 200
    assert client.get(BASE, headers=ADMIN).json()["mcp"]["declared_endpoint_count"] == 0
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_ENDPOINTS", json.dumps([endpoint]))
    assert "QWENPAW_MCP_ALLOWED_ENDPOINTS" in control(client, "mcp_remote")["locked_reason"]
    assert "mcp-fixture.invalid" not in client.get(BASE, headers=ADMIN).text
    assert configure_boundary(client, "mcp_remote", None, []).status_code == 409
    validate_endpoint(endpoint)


def test_malformed_online_policy_fails_closed_and_is_not_overwritten(sample):
    from qwenpaw.config.runtime_boundary_policy import policy_path
    from qwenpaw.extensions.api.chat_isolation import chat_isolation_enabled
    from qwenpaw.extensions.security.mcp_boundary import validate_endpoint

    client, _ = sample
    original = b'{"mcp_remote":'
    policy_path().write_bytes(original)
    assert control(client, "mcp_remote")["locked_reason"]
    assert chat_isolation_enabled()
    with pytest.raises(PermissionError):
        validate_endpoint({"transport": "sse", "url": "http://localhost/sse"})
    assert configure_boundary(client, "mcp_remote", None, []).status_code == 409
    assert policy_path().read_bytes() == original
