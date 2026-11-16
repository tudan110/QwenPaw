"""Public login endpoints cannot grant cross-site cookie changes."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app import auth
from qwenpaw.extensions.api import access_session, sso_backend
from qwenpaw.extensions.api.sso_token_middleware import SsoTokenMiddleware


@pytest.fixture
def login(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(
        access_session,
        "_STORE",
        access_session.AccessSessionStore(tmp_path / "sessions.db"),
    )
    monkeypatch.setattr(
        sso_backend.sso_settings_store,
        "get_userinfo_url",
        lambda **kwargs: "http://fixture.invalid/userinfo",
    )
    validate = AsyncMock(return_value={"user": {"userId": 7}})
    monkeypatch.setattr(sso_backend, "_validate_inoe_token", validate)
    monkeypatch.setenv("QWENPAW_SSO_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "1")
    monkeypatch.delenv("QWENPAW_BROWSER_ORIGINS", raising=False)
    app = FastAPI()
    validator = AsyncMock()
    validator.validate.return_value = {"userId": 7}
    app.add_middleware(SsoTokenMiddleware, validator=validator)
    app.include_router(sso_backend.router, prefix="/api/portal")

    @app.api_route("/api/portal/{resource:path}", methods=["GET", "POST"])
    async def query(request: Request, resource: str):
        return {"user_id": request.state.access_identity.user_id}

    return TestClient(app), validate


@pytest.mark.parametrize(
    "headers",
    [
        {"Cookie": "Cnos-Inoe-Admin-Token=fixture"},
        {"Cookie": "Cnos-Inoe-Admin-Token=fixture", "Origin": "null"},
        {
            "Cookie": "Cnos-Inoe-Admin-Token=fixture",
            "Origin": "https://evil.invalid",
        },
        {"Origin": "https://evil.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_public_login_rejects_untrusted_browser_before_validation(
    login, headers
):
    client, validate = login
    response = client.post(
        "/api/portal/sso/token-login",
        headers=headers,
        json={"token": "fixture"},
    )
    assert response.status_code == 403
    validate.assert_not_awaited()
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://testserver"},
        {
            "Origin": "http://testserver",
            "Cookie": "Cnos-Inoe-Admin-Token=fixture",
        },
    ],
)
def test_public_login_allows_nonbrowser_explicit_and_same_origin(
    login, headers
):
    client, validate = login
    response = client.post(
        "/api/portal/sso/token-login",
        headers=headers,
        json={"token": "fixture"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"].startswith("qp1.")
    validate.assert_awaited_once()


def test_explicit_deployed_origin_is_supported(login, monkeypatch):
    client, _ = login
    monkeypatch.setenv("QWENPAW_BROWSER_ORIGINS", "https://portal.example")
    response = client.post(
        "/api/portal/sso/token-login",
        headers={"Origin": "https://portal.example"},
        json={"token": "fixture"},
    )
    assert response.status_code == 200


def test_cookie_cleanup_checks_origin_before_revoking_and_allows_expired_cookie(
    login,
):
    client, _ = login
    result = client.post(
        "/api/portal/sso/token-login",
        headers={"Origin": "http://testserver"},
        json={"token": "fixture"},
    ).json()
    token = result["access_token"]
    response = client.post(
        "/api/portal/sso/clear-login-cookie",
        headers={"Origin": "https://evil.invalid"},
    )
    assert response.status_code == 403
    access_session.get_access_store().resolve(token)
    response = client.post(
        "/api/portal/sso/clear-login-cookie",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        access_session.get_access_store().resolve(token)
    client.cookies.set(access_session.ACCESS_COOKIE, "expired-fixture")
    assert client.post(
        "/api/portal/sso/clear-login-cookie",
        headers={"Origin": "http://testserver"},
    ).json() == {"cleared": True}


def test_authorization_code_is_disabled_even_with_client_config(
    login, monkeypatch
):
    client, _ = login
    monkeypatch.setattr(
        sso_backend.sso_settings_store, "is_configured", lambda: True
    )
    exchange = AsyncMock()
    monkeypatch.setattr(sso_backend, "_exchange_code_for_token", exchange)
    response = client.post(
        "/api/portal/sso/exchange",
        json={"code": "fixture", "state": "unbound"},
    )
    assert response.status_code == 404
    exchange.assert_not_awaited()
    assert (
        client.get("/api/portal/sso/status").json()["authorization_code_ready"]
        is False
    )


@pytest.mark.parametrize(
    "method,path",
    [("GET", "employee-status"), ("POST", "knowledge-base/query")],
)
def test_closed_data_endpoints_allow_regular_authenticated_users(
    login, method, path
):
    client, _ = login
    url = "/api/portal/" + path
    assert client.request(method, url).status_code == 401
    response = client.request(method, url, headers={"X-Inoe-Token": "fixture"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "7"
    issued = client.post(
        "/api/portal/sso/token-login", json={"token": "fixture"}
    ).json()["access_token"]
    response = client.request(
        method,
        url,
        headers={
            "X-QwenPaw-Access-Token": issued,
            "Origin": "http://testserver",
        },
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == "7"
