"""Protected HTTP APIs require a genuinely validated INOE login."""

import pytest
import asyncio
import httpx
from unittest.mock import AsyncMock
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware
from qwenpaw.extensions.api import inoe_settings_store
from qwenpaw.extensions.api.sso_auth import InoeTokenValidator


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    app = FastAPI()

    async def validate(token, url, *, use_cache):
        if token.startswith("invalid"):
            raise HTTPException(401, "INOE 登录态无效或已过期")
        return {"userId": 7, "username": "test-user"}

    validator = AsyncMock()
    validator.validate.side_effect = validate
    app.state.validator = validator
    app.add_middleware(SsoTokenMiddleware, validator=validator)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    )
    async def endpoint(request: Request, path: str):
        if path == "api/console/chat":

            async def events():
                assert request.state.inoe_token == "test-token"
                assert request.state.sso_user["userId"] == 7
                assert (
                    inoe_settings_store.CURRENT_REQUEST_TOKEN.get()
                    == "test-token"
                )
                yield "data: ready\n\n"

            return StreamingResponse(
                events(),
                media_type="text/event-stream",
            )
        if path == "api/identity":
            return {
                "user": request.state.sso_user,
                "token": inoe_settings_store.CURRENT_REQUEST_TOKEN.get(),
            }
        return {"method": request.method, "path": path}

    return TestClient(app, headers={"Origin": "http://testserver"})


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
    assert response.json()["stage"] == "request_authentication"
    assert response.json()["occurred_at"]
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
def test_validated_token_is_accepted(client, headers, method):
    assert (
        client.request(method, "/api/chats", headers=headers).status_code
        == 200
    )
    client.app.state.validator.validate.assert_awaited_once()


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Inoe-Token": "invalid-token"},
        {"Cookie": "qwenpaw_sso_token=invalid-token"},
        {
            "X-Inoe-Token": "invalid-token",
            "Cookie": "qwenpaw_sso_token=valid-cookie",
        },
    ],
)
def test_invalid_token_cannot_pass_gate(client, headers):
    response = client.get("/api/chats", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "SSO_TOKEN_INVALID"
    assert response.headers["cache-control"] == "no-store"


def test_empty_explicit_header_does_not_fall_back_to_cookie(client):
    response = client.get(
        "/api/chats",
        headers={
            "X-Inoe-Token": "",
            "Cookie": "qwenpaw_sso_token=valid-cookie",
        },
    )
    assert response.status_code == 401
    client.app.state.validator.validate.assert_not_awaited()


@pytest.mark.parametrize("status", [502, 503, 504])
def test_validation_failure_never_reaches_endpoint(client, status):
    client.app.state.validator.validate.side_effect = HTTPException(
        status, "SSO validation unavailable"
    )
    response = client.get(
        "/api/chats", headers={"X-Inoe-Token": "valid-token"}
    )
    assert response.status_code == status
    assert response.json()["code"] == "SSO_VALIDATION_UNAVAILABLE"


@pytest.mark.parametrize(
    ("method", "path", "cached"),
    [
        ("GET", "/api/chats", True),
        ("POST", "/api/console/chat/task", True),
        ("POST", "/api/agents/gateway/console/chat/task", True),
        ("POST", "/copaw-api/api/console/chat/task", True),
        ("POST", "/api/approval/approve", False),
        ("POST", "/api/agents/gateway/approval/approve", False),
        ("POST", "/api/chats/batch-delete", False),
        ("PUT", "/portal-api/inoe-settings", False),
        ("DELETE", "/api/chats/1", False),
    ],
)
def test_only_queries_and_chat_entries_use_cache(client, method, path, cached):
    response = client.request(
        method, path, headers={"X-Inoe-Token": "valid-token"}
    )
    assert response.status_code == 200
    assert (
        client.app.state.validator.validate.await_args.kwargs["use_cache"]
        is cached
    )


def test_cookie_identity_and_token_reach_downstream(client):
    response = client.get(
        "/api/identity",
        headers={"Cookie": "qwenpaw_sso_token=valid%2Fcookie%3Dtoken"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "user": {"userId": 7, "username": "test-user"},
        "token": "valid/cookie=token",
    }
    assert inoe_settings_store.CURRENT_REQUEST_TOKEN.get() is None


def test_validator_is_closed_at_app_shutdown(client):
    with client:
        response = client.get(
            "/api/chats", headers={"X-Inoe-Token": "valid-token"}
        )
        assert response.status_code == 200
    client.app.state.validator.aclose.assert_awaited_once()


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


async def test_real_cache_and_legacy_passthrough_preserve_cookie_identity(
    monkeypatch,
):
    from qwenpaw.extensions.api import portal_backend, sso_settings_store

    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setattr(
        sso_settings_store,
        "get_userinfo_url",
        lambda: "http://gateway:8080/admin/user/getInfo",
    )
    calls = []

    def handler(request):
        calls.append(request.headers["Authorization"])
        if calls[-1] == "Bearer invalid-token":
            return httpx.Response(401)
        return httpx.Response(200, json={"code": 200, "user": {"userId": 7}})

    validator = InoeTokenValidator(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    app = FastAPI()
    app.add_middleware(SsoTokenMiddleware, validator=validator)
    portal_backend.register_app_routes(app)

    @app.get("/api/test/identity")
    async def identity(request: Request):
        threaded_token = await asyncio.to_thread(
            inoe_settings_store.CURRENT_REQUEST_TOKEN.get
        )
        return {
            "token": request.state.inoe_token,
            "threaded_token": threaded_token,
            "user": request.state.sso_user,
        }

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"Cookie": "qwenpaw_sso_token=valid%2Fcookie%3D"}
            for _ in range(2):
                response = await client.get(
                    "/api/test/identity", headers=headers
                )
                assert response.status_code == 200
                assert response.json() == {
                    "token": "valid/cookie=",
                    "threaded_token": "valid/cookie=",
                    "user": {"userId": 7},
                }
            assert calls == ["Bearer valid/cookie="]
            response = await client.get(
                "/api/test/identity",
                headers={**headers, "X-Inoe-Token": "invalid-token"},
            )
            assert response.status_code == 401
            assert calls[-1] == "Bearer invalid-token"
        assert inoe_settings_store.CURRENT_REQUEST_TOKEN.get() is None
    finally:
        await validator.aclose()


async def test_concurrent_streams_keep_separate_verified_credentials(
    monkeypatch,
):
    from qwenpaw.extensions.api import sso_settings_store

    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setattr(
        sso_settings_store,
        "get_userinfo_url",
        lambda: "http://gateway:8080/admin/user/getInfo",
    )

    def handler(request):
        token = request.headers["Authorization"].removeprefix("Bearer ")
        return httpx.Response(
            200, json={"code": 200, "user": {"userName": token}}
        )

    validator = InoeTokenValidator(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    app = FastAPI()
    app.add_middleware(SsoTokenMiddleware, validator=validator)

    @app.post("/api/console/chat")
    async def stream(request: Request):
        async def events():
            for _ in range(2):
                await asyncio.sleep(0)
                token = inoe_settings_store.CURRENT_REQUEST_TOKEN.get()
                assert token == request.state.sso_user["username"]
                yield f"data: {token}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                client.post(
                    "/api/console/chat",
                    headers={"X-Inoe-Token": "user-one"},
                ),
                client.post(
                    "/api/console/chat",
                    headers={"X-Inoe-Token": "Bearer user-two"},
                ),
            )
        assert responses[0].text == "data: user-one\n\n" * 2
        assert responses[1].text == "data: user-two\n\n" * 2
        assert inoe_settings_store.CURRENT_REQUEST_TOKEN.get() is None
    finally:
        await validator.aclose()
