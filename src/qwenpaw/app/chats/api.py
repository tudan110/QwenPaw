# -*- coding: utf-8 -*-
"""Chat management API."""
from __future__ import annotations
import logging
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agentscope.message import Msg
from agentscope.state import AgentState

from ...extensions.api.chat_isolation import (
    chat_scope,
    reject_reserved_legacy_namespace,
    require_owned_chat,
)
from .session import EMPTY_RECALLED_CHAT_NAME, SafeJSONSession, portal_turn_status
from .manager import ChatManager
from .models import (
    ChatSpec,
    ChatUpdate,
    ChatHistory,
)
from .stopped_turn import latest_stopped_turn
from .utils import agentscope_msg_to_message, parse_legacy_memory_state

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


async def get_workspace(request: Request):
    """Get the workspace for the active agent."""
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def get_chat_manager(
    request: Request,
) -> ChatManager:
    """Get the chat manager for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance for the specified agent

    Raises:
        HTTPException: If manager is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.chat_manager


async def get_session(
    request: Request,
) -> SafeJSONSession:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        SafeJSONSession instance for the specified agent

    Raises:
        HTTPException: If session is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.session


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    Args:
        user_id: Optional user ID to filter chats
        channel: Optional channel name to filter chats
        mgr: Chat manager dependency
    """
    scope = chat_scope()
    chats = await mgr.list_chats(
        user_id=scope.owner if scope is not None else user_id,
        channel=channel,
    )
    tracker = workspace.task_tracker
    result = []
    for spec in chats:
        if scope is not None and not scope.owns(spec):
            continue
        if scope is None:
            try:
                reject_reserved_legacy_namespace(spec.user_id, spec.session_id)
            except HTTPException:
                continue
        status = await tracker.get_status(spec.id)
        if (
            scope is not None and status != "running"
            and spec.name == EMPTY_RECALLED_CHAT_NAME
            and getattr(workspace, "session", None) is not None
            and await workspace.session.is_empty_recalled_chat(spec)
        ):
            continue
        result.append(spec.model_copy(update={"status": status}))
    return result


@router.post("", response_model=ChatSpec)
async def create_chat(
    request: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a new chat.

    Server generates chat_id (UUID) automatically.

    Args:
        request: Chat creation request
        mgr: Chat manager dependency

    Returns:
        Created chat spec with UUID
    """
    scope = chat_scope()
    if scope is None:
        reject_reserved_legacy_namespace(request.user_id, request.session_id)
    elif request.channel != "console":
        raise HTTPException(422, "该入口仅支持 Portal 会话")
    chat_id = str(uuid4())
    spec = ChatSpec(
        id=chat_id,
        name=request.name,
        session_id=scope.session_id(request.session_id) if scope else request.session_id,
        user_id=scope.owner if scope else request.user_id,
        channel=request.channel,
        meta=request.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    chat_ids: list[str],
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete chats by chat IDs.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    scope = chat_scope()
    for chat_id in set(chat_ids):
        if scope is not None:
            await require_owned_chat(mgr, chat_id, scope)
        else:
            existing = await mgr.get_chat(chat_id)
            if existing:
                reject_reserved_legacy_namespace(existing.user_id, existing.session_id)
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    return {"deleted": deleted}


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        request: FastAPI request (for agent context)
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: SafeJSONSession dependency

    Returns:
        ChatHistory with messages and status (idle/running)

    Raises:
        HTTPException: If chat not found (404)
    """
    scope = chat_scope()
    chat_spec = await require_owned_chat(mgr, chat_id, scope)

    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
        chat_spec.channel,
    )
    status = await workspace.task_tracker.get_status(chat_id)
    if not state:
        return ChatHistory(messages=[], status=status)

    agent_raw = state.get("agent", {})
    memories: list[Msg] = []

    state_raw = agent_raw.get("state")
    parsed_state = False
    if isinstance(state_raw, dict):
        try:
            agent_state = AgentState.model_validate(state_raw)
            memories = list(agent_state.context)
            parsed_state = True
        except Exception:
            logger.debug(
                "Failed to parse agent.state, falling back to legacy",
                exc_info=True,
            )

    # Legacy fallback: 1.x ``agent.memory`` format. An explicitly empty
    # current state must not resurrect a legacy copy of removed messages.
    if not parsed_state:
        memory_raw = agent_raw.get("memory", {})
        if memory_raw:
            memories, _summary = parse_legacy_memory_state(memory_raw)

    messages = agentscope_msg_to_message(memories)
    checkpoint = latest_stopped_turn(memories) if scope is not None else None
    return ChatHistory(
        messages=messages, status=status, stopped_turn=checkpoint,
        portal_turn=portal_turn_status(state) if scope is not None else None,
    )


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Partial chat update payload
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat not found (404)
    """
    await require_owned_chat(mgr, chat_id, chat_scope())
    updated = await mgr.patch_chat(chat_id, spec)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete a chat by UUID.

    Note: This only deletes the chat spec (UUID mapping).
    JSONSession state is NOT deleted.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    await require_owned_chat(mgr, chat_id, chat_scope())
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return {"deleted": True}
