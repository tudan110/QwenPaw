# -*- coding: utf-8 -*-
"""Native federation, northbound compatibility and default-deny P0 policy."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from qwenpaw.app import auth
from qwenpaw.extensions.api import access_session, model_access
from qwenpaw.extensions.api.access_session import AccessSessionStore
from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware
from qwenpaw.security import secret_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(
        secret_store, "_cached_master_key", Fernet.generate_key()
    )
    value = AccessSessionStore(tmp_path / "access.db")
    monkeypatch.setattr(access_session, "_STORE", value)
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    return value


@pytest.fixture
def client(store):
    app = FastAPI()
    validator = AsyncMock()

    async def validate(token, url, *, use_cache):
        if token.startswith("invalid") or not token:
            raise HTTPException(401, "invalid")
        return {
            "userId": 8 if token == "user-eight" else 7,
            "username": "user",
        }

    validator.validate.side_effect = validate
    app.state.validator = validator
    app.add_middleware(SsoTokenMiddleware, validator=validator)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def endpoint(request: Request, path: str):
        identity = getattr(request.state, "access_identity", None)
        if identity is None:
            return {"source": "explicitly-disabled"}
        return {
            "userId": identity.user_id,
            "source": identity.source,
            "inoe": identity.inoe_token,
        }

    return TestClient(app)


def test_issue_without_password_registration_and_no_plaintext_credentials(
    store,
):
    issued = store.issue("user-seven", {"userId": 7})
    assert auth.has_registered_users() is False
    identity = store.resolve(issued["access_token"])
    assert identity.user_id == "7"
    assert identity.inoe_token == "user-seven"
    assert issued["expires_in_seconds"] == 600
    assert b"user-seven" not in store.path.read_bytes()
    assert issued["access_token"].encode() not in store.path.read_bytes()
    assert (
        issued["access_token"]
        != store.issue("user-eight", {"userId": 8})["access_token"]
    )


def test_explicit_nonproduction_profile_preserves_native_management(
    client, monkeypatch
):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "false")
    assert client.post("/api/agents").status_code == 200
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    assert client.post("/api/agents").status_code == 401
    assert (
        client.post(
            "/api/agents", headers={"X-Inoe-Token": "user-eight"}
        ).status_code
        == 200
    )


def test_configured_admin_one_does_not_grant_other_users(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "1")
    validator = client.app.state.validator.validate
    validator.side_effect = None
    validator.return_value = {"userId": 1}
    assert (
        client.post(
            "/api/agents", headers={"X-Inoe-Token": "fixture-one"}
        ).status_code
        == 200
    )
    validator.return_value = {"userId": 2}
    assert (
        client.post(
            "/api/agents", headers={"X-Inoe-Token": "fixture-two"}
        ).status_code
        == 403
    )
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "")
    validator.return_value = {"userId": 1}
    assert (
        client.post(
            "/api/agents", headers={"X-Inoe-Token": "fixture-one"}
        ).status_code
        == 403
    )


def test_tampered_expired_revoked_and_unregistered_tokens_fail(store):
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    with pytest.raises(HTTPException):
        store.resolve(issued + "tampered")
    signed_without_session = "qp1." + auth.create_token("inoe:7", 600)
    with pytest.raises(HTTPException):
        store.resolve(signed_without_session)
    with store._connect() as conn:
        conn.execute("UPDATE access_sessions SET expires_at=0")
    with pytest.raises(HTTPException):
        store.resolve(issued)
    current = store.issue("user-seven", {"userId": 7})["access_token"]
    store.revoke(current)
    with pytest.raises(HTTPException):
        store.resolve(current)


def test_corrupted_auth_key_does_not_regenerate_or_bypass(store):
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    auth.AUTH_FILE.write_text("not-json")
    with pytest.raises(HTTPException) as error:
        store.resolve(issued)
    assert error.value.status_code == 503
    assert auth.AUTH_FILE.read_text() == "not-json"


def test_logout_revokes_all_renewals_but_not_another_browser(store):
    original = store.issue("user-seven", {"userId": 7})["access_token"]
    identity = store.resolve(original)
    renewed = store.issue(
        identity.inoe_token,
        identity.user,
        family_id=identity.family_id,
    )["access_token"]
    other = store.issue("user-seven", {"userId": 7})["access_token"]
    store.revoke(renewed)
    for token in (original, renewed):
        with pytest.raises(HTTPException):
            store.resolve(token)
    assert store.resolve(other).user_id == "7"


def test_inflight_renewal_cannot_resurrect_logged_out_family(store):
    original = store.issue("user-seven", {"userId": 7})["access_token"]
    identity = store.resolve(original)
    store.revoke(original)
    with pytest.raises(HTTPException) as error:
        store.issue(
            identity.inoe_token, identity.user, family_id=identity.family_id
        )
    assert error.value.status_code == 401


def test_authentication_realm_change_invalidates_local_sessions(
    store, monkeypatch
):
    from qwenpaw.extensions.api import sso_settings_store

    original = store.issue("user-seven", {"userId": 7})["access_token"]
    monkeypatch.setattr(
        sso_settings_store,
        "get_userinfo_url",
        lambda: "https://new-authority.example/userinfo",
    )
    with pytest.raises(HTTPException):
        store.resolve(original)


def test_northbound_and_local_access_share_business_identity(client, store):
    north = client.get("/api/chats", headers={"X-Inoe-Token": "user-seven"})
    assert north.status_code == 200
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    for headers in (
        {"Authorization": "Bearer " + issued},
        {"X-QwenPaw-Access-Token": issued},
        {"X-Inoe-Token": issued},
        {"Cookie": "qwenpaw_access_token=" + issued},
    ):
        response = client.get("/api/chats", headers=headers)
        assert response.status_code == 200
        assert response.json()["inoe"] == "user-seven"
        assert response.json()["userId"] == "7"
    assert client.app.state.validator.validate.await_count == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/envs",
        "/api/mcp",
        "/api/agents/fault/mcp",
        "/api/portal/inoe-settings",
        "/api/portal/sso/sso-settings",
        "/api/security",
        "/api/approval/list",
    ],
)
def test_admin_allowlist_defaults_deny(client, monkeypatch, path):
    monkeypatch.delenv("QWENPAW_ADMIN_INOE_USER_IDS")
    response = client.get(path, headers={"X-Inoe-Token": "user-seven"})
    assert response.status_code == 403
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    assert (
        client.get(path, headers={"X-Inoe-Token": "user-seven"}).status_code
        == 200
    )
    assert (
        client.get(path, headers={"X-Inoe-Token": "user-eight"}).status_code
        == 403
    )


def test_conflicting_and_empty_explicit_credentials_do_not_fall_back(
    client, store
):
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    response = client.get(
        "/api/chats",
        headers={
            "Authorization": "Bearer " + issued,
            "X-Inoe-Token": "user-eight",
        },
    )
    assert response.status_code == 401
    response = client.get(
        "/api/chats",
        headers={
            "X-QwenPaw-Access-Token": "",
            "Cookie": "qwenpaw_access_token=" + issued,
        },
    )
    assert response.status_code == 401
    response = client.get(
        "/api/chats",
        headers={
            "Authorization": "Bearer " + issued,
            "X-Inoe-Token": "invalid-token",
        },
    )
    assert response.status_code == 401


def test_write_online_revalidation_and_disabled_gate_still_deny_admin(
    client, store, monkeypatch
):
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    assert (
        client.put(
            "/api/portal/inoe-settings",
            headers={
                "Authorization": "Bearer " + issued,
            },
        ).status_code
        == 200
    )
    assert (
        client.app.state.validator.validate.await_args.kwargs["use_cache"]
        is False
    )
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "false")
    assert client.get("/api/chats").status_code == 200
    assert client.put("/api/envs", json={}).status_code == 403


def test_cookie_write_requires_the_legitimate_browser_origin(client, store):
    issued = store.issue("user-seven", {"userId": 7})["access_token"]
    for origin in ("", "https://untrusted.example", "http://testserver:9999"):
        assert (
            client.put(
                "/api/envs",
                headers={
                    "Cookie": "qwenpaw_access_token=" + issued,
                    "Origin": origin,
                },
                json={},
            ).status_code
            == 403
        )
    assert (
        client.put(
            "/api/envs",
            headers={
                "Cookie": "qwenpaw_access_token=" + issued,
                "Origin": "http://testserver",
            },
            json={},
        ).status_code
        == 200
    )


def test_model_capability_key_is_not_general_api_authentication(client, store):
    key = model_access.model_service_key(create=True)
    response = client.post(
        "/api/portal/kunlun-adapter/v1/chat/completions",
        headers={"X-QwenPaw-Model-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "model_service"
    assert response.json()["inoe"] == ""
    assert (
        client.get(
            "/api/envs",
            headers={
                "X-QwenPaw-Model-Key": key,
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/portal/kunlun-adapter/v1/chat/completions",
            headers={
                "X-QwenPaw-Model-Key": "invalid-key",
            },
        ).status_code
        == 401
    )


def test_disabled_chat_gate_does_not_open_model_proxy(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "false")
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    path = "/api/portal/kunlun-adapter/v1/chat/completions"
    assert client.post(path).status_code == 401
    assert (
        client.post(
            path, headers={"X-QwenPaw-Model-Key": "invalid"}
        ).status_code
        == 401
    )
    key = model_access.model_service_key(create=True)
    response = client.post(path, headers={"X-QwenPaw-Model-Key": key})
    assert response.status_code == 200
    assert response.json()["source"] == "model_service"


def test_local_model_credentials_are_not_sent_to_external_models(
    store, monkeypatch
):
    from qwenpaw.agents.tools import agent_management

    monkeypatch.setattr(agent_management, "read_last_api", lambda: None)
    assert (
        model_access.local_model_headers("https://external.example/v1") == {}
    )
    local = model_access.local_model_headers(
        "http://127.0.0.1:8088/api/portal/kunlun-adapter/v1"
    )
    assert local["X-QwenPaw-Model-Key"]
    with pytest.raises(ValueError):
        model_access.local_model_headers(
            "https://external.example/api/portal/kunlun-adapter/v1"
        )


def test_upstream_adapter_never_forwards_qwenpaw_bearer(monkeypatch):
    from qwenpaw.extensions.api import qiming_openai_adapter

    monkeypatch.setattr(
        qiming_openai_adapter,
        "_read_env",
        lambda *args, **kwargs: "vendor-token",
    )
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer qp1.local-token"),
            ],
        }
    )
    assert (
        qiming_openai_adapter._resolve_authorization(request)
        == "Bearer vendor-token"
    )


def test_untrusted_proxy_headers_cannot_claim_loopback(monkeypatch):
    request = Request(
        {
            "type": "http",
            "client": ("203.0.113.2", 12345),
            "headers": [
                (b"x-forwarded-for", b"127.0.0.1"),
                (b"x-real-ip", b"127.0.0.1"),
            ],
        }
    )
    monkeypatch.delenv("QWENPAW_TRUSTED_PROXY_CIDRS", raising=False)
    monkeypatch.delenv("COPAW_TRUSTED_PROXY_CIDRS", raising=False)
    assert auth.resolve_client_ip(request) == "203.0.113.2"
    monkeypatch.setenv("QWENPAW_TRUSTED_PROXY_CIDRS", "203.0.113.0/24")
    request.scope["headers"] = [
        (b"x-forwarded-for", b"127.0.0.1, 198.51.100.3"),
    ]
    assert auth.resolve_client_ip(request) == "198.51.100.3"
