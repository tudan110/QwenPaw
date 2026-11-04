# -*- coding: utf-8 -*-
"""Failed turns survive history reloads without exposing provider details."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState
from openai import APIStatusError

from qwenpaw.app.chats.api import get_chat
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.extensions.runtime.chat_history import persist_failed_chat_turn
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw.runtime.hooks import HookContext


def _message(role, text):
    return Msg(name=role, role=role, content=[TextBlock(text=text)])


def _context(session, *, snapshot=None, error=None):
    return HookContext(
        request=SimpleNamespace(user_id="alice", channel="console"),
        session_id="failed-session",
        agent_id="gateway",
        root_session_id="failed-session",
        root_agent_id="gateway",
        workspace_dir=None,
        workspace=SimpleNamespace(session=session),
        app_services=None,
        agent=(
            SimpleNamespace(state_dict=lambda: snapshot)
            if snapshot is not None
            else None
        ),
        error=error or RuntimeError("sk-private-key /tmp/private.json"),
        input_msgs=[_message("user", "你好")],
        extras={"_error_text": "failed (MODEL_API_KEY_MISSING)"},
    )


async def _saved_messages(session):
    spec = ChatSpec(
        id="chat",
        session_id="failed-session",
        user_id="alice",
        channel="console",
    )
    history = await get_chat(
        "chat",
        mgr=SimpleNamespace(get_chat=AsyncMock(return_value=spec)),
        session=session,
        workspace=SimpleNamespace(
            task_tracker=SimpleNamespace(
                get_status=AsyncMock(return_value="idle")
            )
        ),
    )
    return [message.model_dump(mode="json") for message in history.messages]


async def test_failed_first_turn_reloads_user_and_safe_error(tmp_path):
    session = SafeJSONSession(str(tmp_path))
    ctx = _context(session)

    await persist_failed_chat_turn(ctx)

    # Reopen the store rather than relying on any in-memory cache.
    history = await _saved_messages(SafeJSONSession(str(tmp_path)))
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[0]["content"][0]["text"] == "你好"
    assert history[1]["metadata"]["metadata"]["portal_chat_error"] == (
        "MODEL_API_KEY_MISSING"
    )
    assert history[1]["content"][0]["text"] == "本轮对话失败。"
    assert "private" not in str(history)


async def test_keeps_previous_turns_scroll_and_deduplicates_user(tmp_path):
    session = SafeJSONSession(str(tmp_path))
    ctx = _context(session)
    state = AgentState(
        context=[
            _message("user", "之前的问题"),
            _message("assistant", "之前的回答"),
            ctx.input_msgs[0],
        ]
    )
    snapshot = {
        "state": state.model_dump(mode="json"),
        "scroll": {"checkpoint": "keep"},
    }
    ctx.agent = SimpleNamespace(state_dict=lambda: snapshot)
    await SessionSaveHook().run(ctx)

    await persist_failed_chat_turn(ctx)

    saved = await session.get_session_state_dict(
        ctx.session_id, "alice", "console"
    )
    assert saved["agent"]["scroll"] == {"checkpoint": "keep"}
    assert len(snapshot["state"]["context"]) == 3
    persisted = AgentState.model_validate(saved["agent"]["state"])
    assert len(persisted.context) == 4
    assert [msg.id for msg in persisted.context].count(
        ctx.input_msgs[0].id
    ) == 1

    # A subsequent successful response retains the earlier failed turn.
    persisted.context.extend(
        [
            _message("user", "重试"),
            _message("assistant", "成功回答"),
        ]
    )
    ctx.agent = SimpleNamespace(
        state_dict=lambda: {
            **saved["agent"],
            "state": persisted.model_dump(mode="json"),
        }
    )
    await SessionSaveHook().run(ctx)
    history = await _saved_messages(SafeJSONSession(str(tmp_path)))
    assert len(history) == 6
    assert history[-1]["content"][0]["text"] == "成功回答"
    assert history[3]["metadata"]["metadata"]["portal_chat_error"] == (
        "MODEL_API_KEY_MISSING"
    )


async def test_build_failure_preserves_existing_session(tmp_path):
    session = SafeJSONSession(str(tmp_path))
    ctx = _context(
        session,
        snapshot={
            "state": AgentState(
                context=[
                    _message("user", "之前的问题"),
                    _message("assistant", "之前的回答"),
                ]
            ).model_dump(mode="json"),
        },
    )
    await SessionSaveHook().run(ctx)
    ctx.agent = None

    await persist_failed_chat_turn(ctx)

    history = await _saved_messages(session)
    assert len(history) == 4
    assert history[1]["content"][0]["text"] == "之前的回答"
    assert history[2]["content"][0]["text"] == "你好"


async def test_does_not_save_partial_agent_execution(tmp_path):
    session = SafeJSONSession(str(tmp_path))
    state = AgentState(
        context=[_message("assistant", "incomplete private output")],
        permission_context={"mode": "bypass"},
    )
    ctx = _context(
        session,
        snapshot={
            "state": state.model_dump(mode="json"),
        },
    )
    await persist_failed_chat_turn(ctx)
    history = await _saved_messages(session)
    assert len(history) == 2
    assert history[0]["content"][0]["text"] == "你好"
    assert "private" not in str(history)
    saved = await session.get_session_state_dict(
        ctx.session_id, "alice", "console"
    )
    assert saved["agent"]["state"]["permission_context"]["mode"] == "bypass"


async def test_repeated_failed_turns_with_same_text_remain_distinct(tmp_path):
    session = SafeJSONSession(str(tmp_path))
    await persist_failed_chat_turn(_context(session))
    await persist_failed_chat_turn(_context(session))
    history = await _saved_messages(SafeJSONSession(str(tmp_path)))
    assert [message["role"] for message in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@pytest.mark.parametrize(
    "error,channel,has_input",
    [
        (asyncio.CancelledError(), "console", True),
        (RuntimeError("fail"), "dingtalk", True),
        (RuntimeError("fail"), "console", False),
    ],
)
async def test_ignores_cancellation_other_channels_and_empty_turns(
    tmp_path, error, channel, has_input
):
    session = SafeJSONSession(str(tmp_path))
    ctx = _context(session, error=error)
    ctx.request.channel = channel
    if not has_input:
        ctx.input_msgs = []
    await persist_failed_chat_turn(ctx)
    assert list(tmp_path.rglob("*.json")) == []


async def test_storage_failure_is_logged_without_replacing_model_error(
    monkeypatch,
):
    from qwenpaw.extensions.runtime import chat_history

    log_error = Mock()
    monkeypatch.setattr(chat_history.logger, "exception", log_error)
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(side_effect=OSError("disk full"))
    )
    ctx = _context(session)
    await persist_failed_chat_turn(ctx)
    log_error.assert_called_once()
    assert "Failed to persist failed chat turn" in log_error.call_args.args[0]
    assert isinstance(ctx.error, RuntimeError)


async def test_error_lifecycle_persists_after_safe_classification(
    tmp_path, monkeypatch
):
    from qwenpaw.extensions.traceability import install
    from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook
    from qwenpaw.runtime.hooks import HookRegistry
    from qwenpaw.runtime.phases import Phase

    monkeypatch.setattr(HookRegistry, "run", HookRegistry.run)
    monkeypatch.setattr(
        HookRegistry, install._PATCH_MARK, False, raising=False
    )
    monkeypatch.setattr(install, "_emit_error", AsyncMock())
    monkeypatch.setattr(
        "qwenpaw.app.chats.query_error_dump.write_query_error_dump",
        lambda *args, **kwargs: None,
    )
    install._install_lifecycle_trace()
    session = SafeJSONSession(str(tmp_path))
    ctx = _context(
        session,
        error=APIStatusError(
            "secret-provider-detail",
            response=httpx.Response(
                401,
                request=httpx.Request(
                    "POST",
                    "https://model.example/v1/chat/completions",
                ),
            ),
            body={"error": {"code": "no_authentication_credential"}},
        ),
    )
    registry = HookRegistry()
    registry.register(ErrorNormalizeHook())
    await registry.run(Phase.ON_ERROR, ctx)

    history = await _saved_messages(session)
    assert history[-1]["metadata"]["metadata"]["portal_chat_error"] == (
        "MODEL_API_KEY_MISSING"
    )
