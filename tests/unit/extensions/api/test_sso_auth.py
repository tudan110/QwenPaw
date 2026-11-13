# -*- coding: utf-8 -*-
"""Online validation, bounded caching, expiry and concurrent callers."""

import asyncio
import base64
import json
import time

import httpx
import pytest
from fastapi import HTTPException

from qwenpaw.extensions.api.sso_auth import InoeTokenValidator

URL = "http://gateway:8080/admin/user/getInfo"
USERINFO = {
    "code": 200,
    "user": {
        "userId": 7,
        "userName": "test-user",
        "password": "must-not-be-cached",
    },
}


def validator_for(handler, **kwargs):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return InoeTokenValidator(client=client, **kwargs)


async def test_success_is_cached_without_credentials():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler)
    try:
        first = await validator.validate("valid-token", URL)
        first["username"] = "changed-by-caller"
        second = await validator.validate("valid-token", URL)
        assert second == {"userId": 7, "username": "test-user"}
        assert len(requests) == 1
        assert requests[0].headers["Authorization"] == "Bearer valid-token"
        assert "valid-token" not in repr(validator._cache)
        assert "must-not-be-cached" not in repr(validator._cache)
    finally:
        await validator.aclose()


async def test_expiry_does_not_slide_on_cache_hits():
    clock = [0.0]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, clock=lambda: clock[0])
    try:
        await validator.validate("token", URL)
        clock[0] = 14.0
        await validator.validate("token", URL)
        assert len(calls) == 1
        clock[0] = 15.0
        await validator.validate("token", URL)
        assert len(calls) == 2
    finally:
        await validator.aclose()


@pytest.mark.parametrize("status", [401, 403])
async def test_invalid_tokens_are_never_cached(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "invalid"})

    validator = validator_for(handler)
    try:
        for _ in range(2):
            with pytest.raises(HTTPException) as error:
                await validator.validate("invalid-token", URL)
            assert error.value.status_code == 401
        assert len(calls) == 2
        assert not validator._cache
        assert not validator._inflight
    finally:
        await validator.aclose()


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (httpx.Response(200, json={"code": 401}), 401),
        (httpx.Response(200, json={"code": 403}), 401),
        (httpx.Response(200, json={"code": 500}), 502),
        (httpx.Response(200, json={"error": "invalid_token"}), 401),
        (
            httpx.Response(200, json={"code": 500, "error": "invalid_token"}),
            401,
        ),
        (
            httpx.Response(200, json={"code": 500, "error": "invalid_grant"}),
            401,
        ),
        (
            httpx.Response(200, json={"code": 500, "msg": "内部服务器错误"}),
            502,
        ),
        (httpx.Response(200, json={"error": "server_error"}), 502),
        (httpx.Response(200, json={}), 502),
        (httpx.Response(200, json={"code": 200, "user": {}}), 502),
        (httpx.Response(200, json={"userId": {"fake": 7}}), 502),
        (httpx.Response(200, json=[]), 502),
        (httpx.Response(200, text="not-json"), 502),
        (httpx.Response(302, headers={"Location": "/login"}), 502),
        (httpx.Response(500, text="upstream-secret"), 502),
        (httpx.Response(503, json={"error": "invalid_token"}), 502),
    ],
)
async def test_abnormal_responses_fail_closed(response, status):
    validator = validator_for(lambda request: response)
    try:
        with pytest.raises(HTTPException) as error:
            await validator.validate("token", URL)
        assert error.value.status_code == status
        assert "upstream-secret" not in str(error.value.detail)
        assert not validator._cache
    finally:
        await validator.aclose()


async def test_flat_oauth_userinfo_is_supported():
    validator = validator_for(
        lambda request: httpx.Response(
            200, json={"userId": "7", "username": "test-user"}
        )
    )
    try:
        assert await validator.validate("token", URL) == {
            "userId": "7",
            "username": "test-user",
        }
    finally:
        await validator.aclose()


@pytest.mark.usefixtures("capture_qwenpaw_logs")
@pytest.mark.parametrize(
    "code,expected", [(500, "500"), ("private-credential-value", "unexpected")]
)
async def test_protocol_diagnostics_do_not_log_upstream_secrets(
    caplog, code, expected
):
    validator = validator_for(
        lambda request: httpx.Response(
            200,
            json={
                "code": code,
                "msg": "private-upstream-message",
                "user": {"userId": "private-user"},
            },
        )
    )
    try:
        with caplog.at_level("WARNING"):
            with pytest.raises(HTTPException) as error:
                await validator.validate("private-request-token", URL)
        assert error.value.status_code == 502
        assert f"business_code={expected}" in caplog.text
        assert "classification=upstream_protocol" in caplog.text
        assert "private-" not in caplog.text
        assert "private-" not in str(error.value.detail)
    finally:
        await validator.aclose()


@pytest.mark.parametrize(
    ("exception", "status"),
    [
        (httpx.ConnectError("do-not-expose-token"), 502),
        (httpx.ReadTimeout("do-not-expose-token"), 504),
    ],
)
async def test_network_failures_do_not_reuse_expired_cache(exception, status):
    clock = [0.0]
    failing = [False]

    def handler(request):
        if failing[0]:
            raise exception
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, clock=lambda: clock[0])
    try:
        await validator.validate("token", URL)
        clock[0] = 15.0
        failing[0] = True
        with pytest.raises(HTTPException) as error:
            await validator.validate("token", URL)
        assert error.value.status_code == status
        assert "do-not-expose-token" not in str(error.value.detail)
        assert not validator._cache
    finally:
        await validator.aclose()


async def test_write_revalidation_evicts_a_revoked_cached_token():
    calls = []
    revoked = [False]

    def handler(request):
        calls.append(request)
        if revoked[0]:
            return httpx.Response(401)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler)
    try:
        await validator.validate("token", URL)
        revoked[0] = True
        with pytest.raises(HTTPException):
            await validator.validate("token", URL, use_cache=False)
        with pytest.raises(HTTPException):
            await validator.validate("token", URL)
        assert len(calls) == 3
        assert not validator._cache
    finally:
        await validator.aclose()


async def test_cache_is_bounded_and_keyed_by_token_and_endpoint():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, max_entries=2)
    try:
        await validator.validate("one", URL)
        await validator.validate("two", URL)
        await validator.validate("one", URL)
        await validator.validate("three", URL)
        assert len(validator._cache) == 2
        await validator.validate("two", URL)
        assert len(calls) == 4
        await validator.validate("two", URL + "/changed")
        assert len(calls) == 5
        await validator.validate("Bearer two", URL + "/changed")
        assert len(calls) == 5
    finally:
        await validator.aclose()


async def test_concurrent_requests_share_one_online_check():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler)
    tasks = [
        asyncio.create_task(validator.validate("token", URL))
        for _ in range(10)
    ]
    try:
        await entered.wait()
        release.set()
        users = await asyncio.gather(*tasks)
        assert len(calls) == 1
        assert all(user["userId"] == 7 for user in users)
        assert not validator._inflight
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await validator.aclose()


async def test_disconnected_caller_does_not_cancel_other_waiters():
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(request)
        entered.set()
        await release.wait()
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler)
    first = asyncio.create_task(validator.validate("token", URL))
    second = asyncio.create_task(validator.validate("token", URL))
    try:
        await entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await second)["userId"] == 7
        assert len(calls) == 1
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await validator.aclose()


async def test_pending_checks_are_bounded():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, max_entries=1)
    first = asyncio.create_task(validator.validate("one", URL))
    try:
        await entered.wait()
        with pytest.raises(HTTPException) as error:
            await validator.validate("two", URL)
        assert error.value.status_code == 503
        release.set()
        await first
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        await validator.aclose()


def jwt_with_exp(expires):
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expires}).encode())
        .decode()
        .rstrip("=")
    )
    return f"header.{payload}.signature"


@pytest.mark.parametrize("expires", [1005, 999, "bad", None])
async def test_jwt_exp_only_shortens_cache_after_online_validation(
    monkeypatch, expires
):
    monkeypatch.setattr(time, "time", lambda: 1000)
    clock = [0.0]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, clock=lambda: clock[0])
    token = jwt_with_exp(expires)
    try:
        await validator.validate(token, URL)
        assert len(calls) == 1
        clock[0] = 5.0
        await validator.validate(token, URL)
        assert len(calls) == (1 if expires is None else 2)
    finally:
        await validator.aclose()


async def test_shutdown_clears_cache_and_closes_connections():
    validator = validator_for(
        lambda request: httpx.Response(200, json=USERINFO)
    )
    client = validator._client
    await validator.validate("token", URL)
    await validator.aclose()
    assert client.is_closed
    assert not validator._cache
    assert not validator._inflight


@pytest.mark.parametrize(
    "token", ["", "Bearer", "contains space", "中文", "x" * 16385]
)
async def test_malformed_tokens_are_rejected_before_online_check(token):
    def handler(request):
        pytest.fail("Malformed token must not be sent upstream")

    validator = validator_for(handler)
    try:
        with pytest.raises(HTTPException) as error:
            await validator.validate(token, URL)
        assert error.value.status_code == 401
    finally:
        await validator.aclose()


async def test_missing_authentication_endpoint_does_not_allow_request():
    def handler(request):
        pytest.fail("No endpoint is configured")

    validator = validator_for(handler)
    try:
        with pytest.raises(HTTPException) as error:
            await validator.validate("token", "")
        assert error.value.status_code == 503
    finally:
        await validator.aclose()


async def test_online_validation_has_an_overall_deadline(monkeypatch):
    from qwenpaw.extensions.api import sso_auth

    monkeypatch.setattr(sso_auth, "_HTTP_TIMEOUT_SECONDS", 0.01)

    async def handler(request):
        await asyncio.Event().wait()

    validator = validator_for(handler)
    try:
        with pytest.raises(HTTPException) as error:
            await validator.validate("token", URL)
        assert error.value.status_code == 504
        assert not validator._cache
        assert not validator._inflight
    finally:
        await validator.aclose()


async def test_successful_write_check_ignores_existing_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler)
    try:
        await validator.validate("token", URL)
        await validator.validate("token", URL, use_cache=False)
        await validator.validate("token", URL)
        assert len(calls) == 2
    finally:
        await validator.aclose()


async def test_userinfo_pool_never_reuses_another_users_auth_cookie():
    seen_cookies = []

    def handler(request):
        seen_cookies.append(request.headers.get("Cookie"))
        authorization = request.headers["Authorization"]
        if authorization == "Bearer user-one":
            return httpx.Response(
                200,
                json={"code": 200, "user": {"userId": 1}},
                headers={"Set-Cookie": "idp_session=user-one; Path=/"},
            )
        if authorization == "Bearer user-two":
            return httpx.Response(
                200, json={"code": 200, "user": {"userId": 2}}
            )
        return httpx.Response(401)

    validator = validator_for(handler)
    try:
        assert (await validator.validate("user-one", URL))["userId"] == 1
        with pytest.raises(HTTPException) as error:
            await validator.validate("invalid-user", URL)
        assert error.value.status_code == 401
        assert (await validator.validate("user-two", URL))["userId"] == 2
        assert seen_cookies == [None, None, None]
        assert not validator._client.cookies
    finally:
        await validator.aclose()


async def test_slow_online_validation_does_not_extend_the_cache_window():
    clock = [0.0]
    calls = []

    def handler(request):
        calls.append(request)
        clock[0] += 5.0
        return httpx.Response(200, json=USERINFO)

    validator = validator_for(handler, clock=lambda: clock[0])
    try:
        await validator.validate("token", URL)
        clock[0] = 14.0
        await validator.validate("token", URL)
        assert len(calls) == 1
        clock[0] = 15.0
        await validator.validate("token", URL)
        assert len(calls) == 2
    finally:
        await validator.aclose()
