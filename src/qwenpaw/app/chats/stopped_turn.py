"""Recover the visible part of an interrupted, isolated Portal turn."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable

from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from ...extensions.api.trusted_chat_text import MAX_INPUT, get_text_block
from ...extensions.security.output_guard import load_config, redact
from .models import ChatSpec, StoppedTurn
from .utils import parse_legacy_memory_state

_STOPPED = "portal_stopped_turn"
# Accept a single explicit asset lookup, including the Portal's usual prompts.
# The continuation will run only the bounded CMDB GET, never the original agent.
_CMDB_QUESTION = re.compile(
    r"(?:请\s*)?(?:查询\s*CMDB|(?:智观\s*)?CMDB)\s*(?:查询\s*)?"
    r"(?:资产|设备)\s+(?P<name>[\w][\w.-]{0,159})",
    re.IGNORECASE,
)


def cmdb_asset_name(question: str) -> str | None:
    match = _CMDB_QUESTION.fullmatch(question.strip())
    return match["name"] if match else None


def visible_question(parts: list) -> str:
    return "\n".join(text for part in parts if (text := get_text_block(part)))


def redact_reply(text: str) -> str:
    guard = load_config()
    return redact(text, cfg=guard)[0] if guard.active else text


def stream_events(buffer: Iterable[str]):
    for sse in buffer:
        if sse.startswith("data: "):
            try:
                event = json.loads(sse[6:])
            except ValueError:
                continue
            if isinstance(event, dict):
                yield event


def _visible_stream(buffer: list[str]) -> tuple[str, bool, bool]:
    # Accept the same public text events as Portal, ignoring thinking, tools,
    # metadata and attachments. Completed content replaces prior deltas.
    messages: dict[str, dict[int, str]] = {}
    used_tools = finished = False
    for event in stream_events(buffer):
        kind = event.get("type")
        if event.get("object") == "response" and event.get("status") == "completed":
            finished = True
        elif event.get("object") == "message":
            if kind in {"plugin_call", "plugin_call_output", "function_call", "mcp_tool_call"}:
                used_tools = True
            if kind != "message" or event.get("role") != "assistant" or not event.get("id"):
                continue
            blocks = messages.setdefault(event["id"], {})
            if event.get("status") == "completed":
                text = [
                    part["text"] for part in (event.get("content") or [])
                    if isinstance(part, dict) and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ]
                if text:
                    blocks.clear()
                    blocks.update(enumerate(part[:MAX_INPUT] for part in text))
        elif event.get("object") == "content" and kind == "text":
            blocks = messages.get(event.get("msg_id"))
            text = event.get("text")
            if blocks is None or not isinstance(text, str):
                continue
            index = event.get("index") or 0
            prefix = blocks.get(index, "") if event.get("delta") else ""
            blocks[index] = (prefix + text)[:MAX_INPUT]
    reply = "\n\n".join(
        text for blocks in messages.values()
        if (text := "".join(blocks[index] for index in sorted(blocks)).strip())
    )
    return reply[:MAX_INPUT], used_tools, finished


async def _load(session, chat: ChatSpec) -> tuple[dict, AgentState]:
    saved = await session.get_session_state_dict(chat.session_id, chat.user_id, chat.channel)
    snapshot = saved.get("agent", {})
    state = AgentState.model_validate(snapshot.get("state", {}))
    if "state" not in snapshot and snapshot.get("memory"):
        state.context, state.summary = parse_legacy_memory_state(snapshot["memory"])
    return snapshot, state


async def _save(session, chat: ChatSpec, snapshot: dict, state: AgentState) -> None:
    await session.update_session_state(
        chat.session_id, "agent", {**snapshot, "state": state.model_dump(mode="json")},
        user_id=chat.user_id, channel=chat.channel,
    )


def latest_stopped_turn(memories: list[Msg]) -> StoppedTurn | None:
    if len(memories) < 2:
        return None
    question, reply = memories[-2:]
    marker = reply.metadata.get(_STOPPED)
    if question.role != "user" or reply.role != "assistant" or not isinstance(marker, dict):
        return None
    if marker.get("id") != question.id:
        return None
    return StoppedTurn.model_validate(marker)


async def save_stopped_turn(
    session, chat: ChatSpec, turn_id: str, question: str, buffer: list[str],
    *, cmdb_available: bool,
) -> dict | None:
    draft, used_tools, finished = _visible_stream(buffer)
    if finished or not question.strip():
        return None
    snapshot, state = await _load(session, chat)
    if any(message.id == turn_id for message in state.context):
        return None  # The normal response was already saved before cancellation.
    mode = "none"
    if cmdb_available and cmdb_asset_name(question):
        mode = "cmdb"
    elif draft and not used_tools and not cmdb_asset_name(question) and len(question) <= MAX_INPUT:
        mode = "text"
    checkpoint = StoppedTurn(id=turn_id, at=int(time.time() * 1_000), mode=mode)
    state.context.extend((
        Msg(id=turn_id, name="user", role="user", content=[TextBlock(text=question[:MAX_INPUT])]),
        Msg(name="assistant", role="assistant", metadata={_STOPPED: checkpoint.model_dump()},
            content=[TextBlock(text=redact_reply(draft) if draft else "本轮已停止，未生成回复。")]),
    ))
    await _save(session, chat, snapshot, state)
    return checkpoint.model_dump()


async def get_checkpoint(session, chat: ChatSpec, turn_id: str, mode: str):
    snapshot, state = await _load(session, chat)
    checkpoint = latest_stopped_turn(state.context)
    if checkpoint is None or checkpoint.id != turn_id or checkpoint.mode != mode:
        return None
    question, reply = state.context[-2:]
    return snapshot, state, question.get_text_content(), reply.get_text_content(), checkpoint


async def update_checkpoint_reply(session, chat: ChatSpec, stored, text: str, *, completed: bool):
    snapshot, state, _, _, checkpoint = stored
    reply = state.context[-1]
    reply.content = [TextBlock(text=text)]
    if completed:
        reply.metadata.pop(_STOPPED)
        reply.metadata["portal_resumed"] = True
    await _save(session, chat, snapshot, state)
    return None if completed else checkpoint.model_dump()
