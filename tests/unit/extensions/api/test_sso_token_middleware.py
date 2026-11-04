"""Contract for the temporary, deliberately presence-only SSO gate."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    app = FastAPI()
    app.add_middleware(SsoTokenMiddleware)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    )
    async def endpoint(request: Request, path: str):
        if path == "api/console/chat":
            return StreamingResponse(
                iter(["data: ready\n\n"]),
                media_type="text/event-stream",
            )
        return {"method": request.method, "path": path}

    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/chats",
        "/api/agents/gateway/chats",
        "/api/portal/employee-status",
        "/api/portal/sso/sso-settings",
        "/api/portal/sso/status/extra",
        "/api/portal/ai/system-summary",
        "/portal-api/employee-status",
        "/copaw-api/api/chats",
    ],
)
def test_missing_token_is_rejected(client, path):
    response = client.get(path, headers={"X-Agent-Id": "gateway"})
    assert response.status_code == 401
    assert response.json()["code"] == "SSO_TOKEN_REQUIRED"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("token", ["", " ", "Bearer", "Bearer "])
def test_empty_header_token_is_rejected(client, token):
    assert (
        client.get("/api/chats", headers={"X-Inoe-Token": token}).status_code
        == 401
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Inoe-Token": "temporary-test-token"},
        {"X-Inoe-Token": "Bearer temporary-test-token"},
        {"Cookie": "qwenpaw_sso_token=temporary%2Ftest%3Dtoken"},
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_nonempty_token_is_accepted_without_validation(
    client, headers, method
):
    assert (
        client.request(method, "/api/chats", headers=headers).status_code
        == 200
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"Cookie": "qwenpaw_sso_token=%20%20"},
        {"X-Forwarded-For": "127.0.0.1"},
        {"Authorization": "Bearer unrelated-token"},
    ],
)
def test_no_alternate_bypass(client, headers):
    assert client.get("/api/chats", headers=headers).status_code == 401
    assert client.get("/api/chats?token=test").status_code == 401


@pytest.mark.parametrize("prefix", ["/api/portal", "/portal-api"])
@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/health"),
        ("GET", "/sso/status"),
        ("POST", "/sso/token-login"),
        ("POST", "/sso/exchange"),
        ("POST", "/sso/clear-login-cookie"),
    ],
)
def test_only_bootstrap_and_health_are_public(client, prefix, method, suffix):
    path = prefix + suffix
    assert client.request(method, path).status_code == 200
    assert client.request(method, path + "/").status_code == 200
    assert client.put(path).status_code == 401


def test_preflight_and_static_pages_still_work(client):
    assert client.options("/api/chats").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/sso/callback").status_code == 200


def test_streaming_is_not_consumed(client):
    response = client.post(
        "/api/console/chat", headers={"X-Inoe-Token": "test-token"}
    )
    assert response.status_code == 200
    assert response.text == "data: ready\n\n"
    assert response.headers["content-type"].startswith("text/event-stream")
    assert client.post("/api/console/chat").status_code == 401


@pytest.mark.parametrize(
    "env_key",
    ["QWENPAW_SSO_TOKEN_REQUIRED", "COPAW_SSO_TOKEN_REQUIRED"],
)
def test_explicit_rollback_switch(client, monkeypatch, env_key):
    monkeypatch.delenv("QWENPAW_SSO_TOKEN_REQUIRED", raising=False)
    monkeypatch.delenv("COPAW_SSO_TOKEN_REQUIRED", raising=False)
    assert client.get("/api/chats").status_code == 401
    monkeypatch.setenv(env_key, "false")
    assert client.get("/api/chats").status_code == 200


def test_invalid_switch_does_not_disable_gate(client, monkeypatch):
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "typo")
    assert client.get("/api/chats").status_code == 401


def test_main_app_registers_sso_token_gate(monkeypatch):
    from qwenpaw.app._app import app

    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    assert any(
        middleware.cls is SsoTokenMiddleware
        for middleware in app.user_middleware
    )
    main_client = TestClient(app)
    assert main_client.get("/api/chats").status_code == 401
    assert main_client.get("/api/portal/employee-status").status_code == 401
    assert main_client.get("/api/portal/health").status_code == 200
