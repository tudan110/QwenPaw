# -*- coding: utf-8 -*-
"""Keep Kunlun failure categories without exposing provider details."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from qwenpaw.extensions.runtime.chat_errors import refine_kunlun_chat_error
from qwenpaw.runtime.hooks import HookContext

_URL = "http://127.0.0.1:8088/api/portal/kunlun-adapter/v1/chat/completions"
_ORIGINAL_TEXT = "Model 'unknown' execution failed (MODEL_EXECUTION_ERROR)"


def _error(status, body, *, url=_URL):
    response = httpx.Response(
        status,
        request=httpx.Request("POST", url),
    )
    return APIStatusError(
        "upstream failure: secret-provider-detail",
        response=response,
        body=body,
    )


def _context(exc, *, channel="console"):
    return HookContext(
        request=SimpleNamespace(channel=channel),
        session_id="test-session",
        agent_id="test-agent",
        root_session_id="test-session",
        root_agent_id="test-agent",
        workspace_dir=None,
        workspace=None,
        app_services=None,
        error=exc,
        extras={"_error_text": _ORIGINAL_TEXT},
    )


@pytest.mark.parametrize(
    "status,body,code",
    [
        (
            500,
            {"code": 500, "msg": "model not authorized: private-model-id"},
            "KUNLUN_MODEL_UNAUTHORIZED",
        ),
        (
            404,
            {
                "message": (
                    "JTEOP_GRAY: POST /serviceAgent/rest/cpn/aiapp/v1/"
                    "chat/completions 未匹配到有效的API"
                )
            },
            "KUNLUN_ROUTE_NOT_FOUND",
        ),
        (
            404,
            {"error": {"message": "model does not exist"}},
            "KUNLUN_NOT_FOUND",
        ),
        (
            503,
            "<html>503 Service Temporarily Unavailable APISIX</html>",
            "KUNLUN_SERVICE_UNAVAILABLE",
        ),
        (401, {"error": "unauthorized"}, "KUNLUN_AUTH_FAILED"),
        (403, {"error": "forbidden"}, "KUNLUN_AUTH_FAILED"),
        (
            502,
            {"detail": "Kunlun token endpoint returned 401: private detail"},
            "KUNLUN_AUTH_FAILED",
        ),
        (
            503,
            {"detail": "Kunlun adapter is not configured. Set secret env"},
            "KUNLUN_NOT_CONFIGURED",
        ),
        (
            502,
            {"detail": "Failed to connect to Kunlun upstream: private URL"},
            "KUNLUN_CONNECTION_FAILED",
        ),
        (
            502,
            {"detail": "Failed to reach Kunlun token endpoint: ConnectError"},
            "KUNLUN_CONNECTION_FAILED",
        ),
        (
            504,
            {"detail": "Kunlun upstream request timed out."},
            "KUNLUN_TIMEOUT",
        ),
        (429, {"message": "rate limit"}, "KUNLUN_RATE_LIMITED"),
    ],
)
def test_exposes_only_allowlisted_category(status, body, code):
    ctx = _context(_error(status, body))

    refine_kunlun_chat_error(ctx)

    assert ctx.extras["_error_text"] == (
        f"Kunlun model request failed ({code})"
    )
    assert ctx.error.body == body
    assert ctx.error.status_code == status


def test_never_echoes_upstream_secrets_or_request_url():
    ctx = _context(
        _error(
            500,
            {
                "msg": (
                    "model not authorized: private-model-id "
                    "Authorization: Bearer private-token "
                    "sk-private-key /tmp/private-dump.json"
                )
            },
            url=_URL + "?key=private-query-secret",
        )
    )

    refine_kunlun_chat_error(ctx)

    text = ctx.extras["_error_text"]
    assert "KUNLUN_MODEL_UNAUTHORIZED" in text
    assert "private" not in text
    assert "/tmp" not in text
    assert "127.0.0.1" not in text


@pytest.mark.parametrize(
    "exc,channel",
    [
        (_error(500, {"msg": "unrecognized provider error"}), "console"),
        (
            _error(
                500,
                {"msg": "model not authorized"},
                url="https://other.example/v1/chat/completions",
            ),
            "console",
        ),
        (_error(500, {"msg": "model not authorized"}), "dingtalk"),
        (RuntimeError("model not authorized"), "console"),
        (asyncio.CancelledError(), "console"),
        (None, "console"),
    ],
)
def test_leaves_unknown_other_provider_and_channel_errors_unchanged(
    exc, channel
):
    ctx = _context(exc, channel=channel)

    refine_kunlun_chat_error(ctx)

    assert ctx.extras["_error_text"] == _ORIGINAL_TEXT


def test_follows_exception_cause_without_looping():
    underlying = _error(500, {"msg": "model not authorized"})
    outer = RuntimeError("model wrapper failed")
    outer.__cause__ = underlying
    ctx = _context(outer)
    refine_kunlun_chat_error(ctx)
    assert "KUNLUN_MODEL_UNAUTHORIZED" in ctx.extras["_error_text"]

    outer.__cause__ = outer
    ctx = _context(outer)
    refine_kunlun_chat_error(ctx)
    assert ctx.extras["_error_text"] == _ORIGINAL_TEXT


async def test_installed_lifecycle_refines_after_core_normalization(
    monkeypatch,
):
    from qwenpaw.extensions.traceability import install as instrumentation
    from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook
    from qwenpaw.runtime.hooks import HookRegistry
    from qwenpaw.runtime.phases import Phase

    monkeypatch.setattr(
        "qwenpaw.app.chats.query_error_dump.write_query_error_dump",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(HookRegistry, "run", HookRegistry.run)
    monkeypatch.setattr(
        HookRegistry, instrumentation._PATCH_MARK, False, raising=False
    )
    emitted = []

    async def record_error(ctx):
        emitted.append(ctx.extras["_error_text"])

    monkeypatch.setattr(instrumentation, "_emit_error", record_error)
    instrumentation._install_lifecycle_trace()
    wrapped = HookRegistry.run
    instrumentation._install_lifecycle_trace()
    assert HookRegistry.run is wrapped
    registry = HookRegistry()
    registry.register(ErrorNormalizeHook())
    contexts = [
        _context(_error(500, {"msg": "model not authorized"})),
        _context(_error(503, "<html>APISIX unavailable</html>")),
        _context(
            _error(
                500,
                {"msg": "model not authorized"},
                url="https://other.example/v1/chat/completions",
            )
        ),
    ]

    await asyncio.gather(
        *(registry.run(Phase.ON_ERROR, ctx) for ctx in contexts)
    )

    assert "KUNLUN_MODEL_UNAUTHORIZED" in contexts[0].extras["_error_text"]
    assert "KUNLUN_SERVICE_UNAVAILABLE" in contexts[1].extras["_error_text"]
    assert "KUNLUN_" not in contexts[2].extras["_error_text"]
    assert len(emitted) == 3

    from qwenpaw.runtime.envelope import Envelope

    for ctx in contexts[:2]:
        events = [
            event.model_dump(mode="json")
            async for event in Envelope(ctx.session_id).error_envelope(
                ctx.extras["_error_text"]
            )
        ]
        assert events[-1]["object"] == "response"
        assert events[-1]["status"] == "failed"
        assert events[-1]["error"] == ctx.extras["_error_text"]

    def broken_classifier(ctx):
        raise RuntimeError("classification failed")

    monkeypatch.setattr(
        instrumentation, "refine_kunlun_chat_error", broken_classifier
    )
    ctx = _context(_error(503, "upstream unavailable"))
    await registry.run(Phase.ON_ERROR, ctx)
    assert "MODEL_EXECUTION_ERROR" in ctx.extras["_error_text"]
    assert len(emitted) == 4
