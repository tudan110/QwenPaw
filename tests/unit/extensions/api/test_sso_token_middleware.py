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
        "/api/portal/employee-status/private",
        "/api/portal/sso/sso-settings",
        "/api/portal/sso/status/extra",
        "/api/portal/ai/system-summary",
        "/portal-api/employee-status/export",
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
        ("GET", "/employee-status"),
        ("GET", "/sso/status"),
        ("POST", "/knowledge-base/query"),
        ("POST", "/sso/token-login"),
        ("POST", "/sso/exchange"),
        ("POST", "/sso/clear-login-cookie"),
    ],
)
def test_public_endpoints_are_method_scoped(client, prefix, method, suffix):
    path = prefix + suffix
    assert client.request(method, path).status_code == 200
    assert client.request(method, path + "/").status_code == 200
    assert client.put(path).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "/portal-api/employee-status",
        "/api/portal/employee-status",
        "/copaw-api/api/portal/employee-status",
    ],
)
def test_employee_status_whitelist_is_exact(client, path):
    assert client.get(path).status_code == 200
    assert (
        client.get(path, params={"include_alert_count": "false"}).status_code
        == 200
    )
    for method in ["POST", "PUT", "DELETE"]:
        assert client.request(method, path).status_code == 401
    assert client.get(path + "/private").status_code == 401


@pytest.mark.parametrize(
    "prefix", ["/api/portal", "/portal-api", "/copaw-api/api/portal"]
)
def test_knowledge_query_whitelist_is_exact(client, prefix):
    path = prefix + "/knowledge-base/query"
    for suffix in ["", "/"]:
        response = client.post(
            path + suffix,
            json={"query": "CPU usage threshold", "filters": {}},
        )
        assert response.status_code == 200
        for method in ["GET", "PUT", "DELETE"]:
            assert client.request(method, path + suffix).status_code == 401
    for suffix in [
        "/query/private",
        "/query-extra",
        "/health",
        "/rag-synthesize",
        "/sources",
        "/sources/1",
    ]:
        protected_path = prefix + "/knowledge-base" + suffix
        for method in ["GET", "POST"]:
            assert client.request(method, protected_path).status_code == 401


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
    from qwenpaw.extensions.api import portal_backend

    async def employee_statuses(request, include_alert_count):
        return []

    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setattr(
        portal_backend, "collect_portal_employee_statuses", employee_statuses
    )
    query_payload = {"query": "CPU usage threshold", "filters": {}}
    query_result = {
        "query_id": "public-query",
        "relevant_evidence": [],
        "flags": {"insufficient_evidence": True},
    }

    def query_knowledge(payload):
        assert payload == query_payload
        return query_result

    monkeypatch.setattr(
        portal_backend.knowledge_base, "query_knowledge", query_knowledge
    )
    assert any(
        middleware.cls is SsoTokenMiddleware
        for middleware in app.user_middleware
    )
    main_client = TestClient(app)
    assert main_client.get("/api/chats").status_code == 401
    response = main_client.get("/api/portal/employee-status")
    assert response.status_code == 200
    assert response.json()["employees"] == []
    assert main_client.get("/api/portal/health").status_code == 200
    response = main_client.post(
        "/api/portal/knowledge-base/query", json=query_payload
    )
    assert response.status_code == 200
    assert response.json() == query_result
    assert (
        main_client.get("/api/portal/knowledge-base/sources").status_code
        == 401
    )
