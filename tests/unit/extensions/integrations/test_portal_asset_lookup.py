import asyncio
import json

import httpx
import pytest

from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.integrations.zgops_cmdb import portal_asset_lookup as lookup


@pytest.fixture(autouse=True)
def sample(monkeypatch):
    monkeypatch.setenv("QWENPAW_TRUSTED_CHAT_ISOLATION", "true")
    monkeypatch.setenv("INOE_API_BASE_URL", "https://inoe.example/api")
    monkeypatch.setenv("INOE_API_TOKEN", "shared-must-not-be-used")


def result(chunk):
    return json.loads(chunk.content[0].text)


@pytest.mark.asyncio
async def test_lookup_keeps_concurrent_callers_separate(monkeypatch):
    name = "TEST-Device-01.example"
    seen = []

    async def fake_upstream(request):
        seen.append(request.headers["authorization"])
        assert request.method == "GET"
        assert request.url.host == "inoe.example"
        assert request.url.path == "/api/cmdb/api/v0.1/ci/s"
        assert request.url.params["q"] == f"name:{name}"
        await asyncio.sleep(0)
        if request.headers["authorization"] == "Bearer admin-fixture":
            return httpx.Response(200, json={"result": [
                {"name": name, "_id": 10, "private_key": "do-not-return"},
                {"name": "another-device", "_id": 20},
            ]})
        return httpx.Response(200, json={"result": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(lookup.httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(fake_upstream),
    ))

    async def call(user, token):
        reset = CURRENT_IDENTITY.set(AccessIdentity({"userId": user}, token))
        try:
            return result(await lookup.lookup_portal_cmdb_asset(name))
        finally:
            CURRENT_IDENTITY.reset(reset)

    admin, ordinary = await asyncio.gather(call("A", "admin-fixture"), call("B", "ordinary-fixture"))
    assert admin["status"] == "ok" and admin["assets"] == [{"name": name, "_id": 10}]
    assert ordinary["status"] == "no_visible_match" and "assets" not in ordinary
    assert sorted(seen) == ["Bearer admin-fixture", "Bearer ordinary-fixture"]


@pytest.mark.asyncio
async def test_refuses_shared_credentials_and_query_operators(monkeypatch):
    def must_not_connect(**kw):
        raise AssertionError("invalid calls must not reach an upstream")

    monkeypatch.setattr(lookup.httpx, "AsyncClient", must_not_connect)
    reset = CURRENT_IDENTITY.set(AccessIdentity({"userId": 2}, ""))
    try:
        assert result(await lookup.lookup_portal_cmdb_asset("device"))["status"] == "authentication_required"
    finally:
        CURRENT_IDENTITY.reset(reset)
    reset = CURRENT_IDENTITY.set(AccessIdentity({"userId": 2}, "test-token"))
    try:
        assert result(await lookup.lookup_portal_cmdb_asset("device,_type:*"))["status"] == "invalid_name"
        assert lookup.portal_asset_lookup_available("gateway", ["zgops-cmdb"], {"channel": "console"})
        assert not lookup.portal_asset_lookup_available("resource", ["zgops-cmdb"], {"channel": "console"})
    finally:
        CURRENT_IDENTITY.reset(reset)


@pytest.mark.asyncio
@pytest.mark.parametrize("status, code, expected", [
    (401, None, "upstream_auth_rejected"), (403, None, "access_denied"),
    (200, 401, "upstream_auth_rejected"), (200, 403, "access_denied"),
    (200, 500, "query_failed"), (302, None, "query_failed"),
    (500, None, "query_failed"),
])
async def test_failure_is_not_reported_as_empty_result(monkeypatch, status, code, expected):
    hits = []

    def fake_upstream(request):
        hits.append(request.url.host)
        return httpx.Response(
            status, headers={"Location": "https://other.example/"},
            json={"code": code, "result": []},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(lookup.httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(fake_upstream),
    ))
    reset = CURRENT_IDENTITY.set(AccessIdentity({"userId": 2}, "test-token"))
    try:
        failure = result(await lookup.lookup_portal_cmdb_asset("device"))
        assert failure["status"] == expected
        assert "assets" not in failure
        if expected == "upstream_auth_rejected":
            assert "CMDB" in failure["message"]
            assert "请重新登录" not in failure["message"]
        assert hits == ["inoe.example"]
    finally:
        CURRENT_IDENTITY.reset(reset)
