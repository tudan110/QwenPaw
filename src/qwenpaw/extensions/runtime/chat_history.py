# -*- coding: utf-8 -*-
"""Persist failed Portal turns using the existing session state schema."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.extensions.runtime.chat_errors import public_chat_error_code
from qwenpaw.runtime._state_utils import StateProxy

if TYPE_CHECKING:
    from qwenpaw.runtime.hooks import HookContext

logger = logging.getLogger(__name__)


async def persist_failed_chat_turn(ctx: HookContext) -> None:
    """Keep the user input and an explicitly marked, sanitized error reply."""
    if (
        getattr(ctx.request, "channel", None) != "console"
        or not isinstance(ctx.error, Exception)
        or not ctx.input_msgs
    ):
        return
    session = getattr(ctx.workspace, "session", None)
    if session is None:
        return
    user_id = getattr(ctx.request, "user_id", "") or ctx.session_id
    channel = getattr(ctx.request, "channel", "") or ""
    try:
        # Failed execution may leave unmatched tool calls in the live agent.
        # Keep the last durable state instead of persisting that partial state.
        saved = await session.get_session_state_dict(
            ctx.session_id, user_id, channel
        )
        snapshot = saved.get("agent", ctx.session_state or {})
        if not snapshot and ctx.agent is not None:
            initial = ctx.agent.state_dict()
            snapshot = {
                "state": {**initial.get("state", {}), "context": []},
            }
        state = AgentState.model_validate(snapshot.get("state", {}))
        if "state" not in snapshot and snapshot.get("memory"):
            from qwenpaw.app.chats.utils import parse_legacy_memory_state

            state.context, state.summary = parse_legacy_memory_state(
                snapshot["memory"]
            )
        existing_ids = {message.id for message in state.context}
        state.context.extend(
            message
            for message in ctx.input_msgs
            if message.id not in existing_ids
        )
        state.context.append(
            Msg(
                name="assistant",
                role="assistant",
                content=[TextBlock(text="本轮对话失败。")],
                metadata={
                    "portal_chat_error": public_chat_error_code(
                        ctx.extras.get("_error_text", "")
                    ),
                },
            )
        )
        proxy = StateProxy()
        proxy.data = {
            **snapshot,
            "state": state.model_dump(mode="json"),
        }
        await session.save_session_state(
            session_id=ctx.session_id,
            user_id=user_id,
            channel=channel,
            agent=proxy,
        )
    except Exception:
        logger.exception(
            "Failed to persist failed chat turn (session=%s)", ctx.session_id
        )
