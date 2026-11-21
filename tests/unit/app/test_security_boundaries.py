# -*- coding: utf-8 -*-
"""Safe reads, no-effect rule checks, and one-way live hardening."""

import json
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app.routers import security_boundaries as boundaries
from qwenpaw.config import utils
from qwenpaw.extensions.api.delete_block_middleware import DeleteBlockMiddleware

BASE = "/api/security/boundaries"
CHECK = BASE + "/delete-protection/check"
ENABLE = BASE + "/delete-protection/enable"
ADMIN = {"X-Test-Role": "admin"}
CONFIRM = {"confirm": "启用全局删除保护"}


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
    assert client.get(BASE, headers=ADMIN).json()["delete_protection"] == {
        "blocked": False, "source": "environment",
    }
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
