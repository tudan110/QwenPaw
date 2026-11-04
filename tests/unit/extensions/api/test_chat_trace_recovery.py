# -*- coding: utf-8 -*-
"""Recover a failed turn without replaying an older successful answer."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.extensions.api import portal_backend


@pytest.fixture
def recovery_context(tmp_path, monkeypatch):
    spec = ChatSpec(
        id="chat", session_id="session", user_id="alice", channel="console"
    )
    workspace = SimpleNamespace(
        agent_id="gateway",
        chat_manager=SimpleNamespace(get_chat=AsyncMock(return_value=spec)),
    )
    monkeypatch.setattr(
        portal_backend,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    monkeypatch.setattr(portal_backend.constant, "WORKING_DIR", tmp_path)
    root = tmp_path / "chat_traces"
    root.mkdir()

    def write(events):
        payload = [
            {
                "agent_id": "gateway",
                "session_id": "session",
                "user_id": "alice",
                "channel": "console",
                **event,
            }
            for event in events
        ]
        (root / "session.jsonl").write_text(
            "\n".join(
                json.dumps(event, ensure_ascii=False) for event in payload
            ),
            encoding="utf-8",
        )

    return write


@pytest.mark.parametrize(
    "error",
    [
        {
            "message": "sk-private-key /tmp/private.json",
            "public_error_code": "MODEL_API_KEY_MISSING",
        },
        {
            "message": (
                "Error code: 401 - {'message':'INCORRECT_API_KEY_PROVIDED',"
                "'detail':'未携带Authorization请求头'} sk-private-key"
            ),
        },
    ],
)
async def test_failed_trace_restores_user_and_safe_error(
    recovery_context, error
):
    recovery_context(
        [
            {"type": "user_message", "text": "上一个问题", "ts": 1},
            {"type": "agent_reply", "text": "上一次的回答", "ts": 2},
            {"type": "user_message", "text": "你好", "ts": 3},
            {"type": "error", "ts": 4, **error},
            # A different agent/user/channel must not affect this conversation.
            {
                "type": "agent_reply",
                "agent_id": "other",
                "text": "wrong",
                "ts": 5,
            },
            {"type": "error", "user_id": "bob", "ts": 6},
            {"type": "user_message", "channel": "other", "ts": 7},
        ]
    )
    result = await portal_backend.recover_chat_trace_reply(None, "chat")
    assert result["available"] is True
    assert result["is_error"] is True
    assert result["user_message"]["content"][0]["text"] == "你好"
    assert result["message"]["metadata"]["portal_chat_error"] == (
        "MODEL_API_KEY_MISSING"
    )
    assert result["trace_ts"] == 4
    assert "private" not in str(result)
    assert "上一次的回答" not in str(result)


async def test_new_unfinished_turn_does_not_replay_previous_reply(
    recovery_context,
):
    recovery_context(
        [
            {"type": "agent_reply", "text": "之前的回答", "ts": 1},
            {"type": "user_message", "text": "新问题", "ts": 2},
        ]
    )
    result = await portal_backend.recover_chat_trace_reply(None, "chat")
    assert result == {"available": False, "reason": "reply_not_found"}


async def test_successful_trace_recovery_keeps_existing_shape(
    recovery_context,
):
    recovery_context(
        [
            {"type": "user_message", "text": "问题", "ts": 1},
            {"type": "agent_reply", "text": "正常回答", "ts": 2},
        ]
    )
    result = await portal_backend.recover_chat_trace_reply(None, "chat")
    assert result["available"] is True
    assert result["message"]["content"][0]["text"] == "正常回答"
    assert "is_error" not in result
