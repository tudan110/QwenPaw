# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Literal, Optional, Union

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from qwenpaw.constant import EnvVarLoader, SECRET_DIR
from qwenpaw.schemas import (
    AgentRequest,
    _coerce_content_item,
)
from ...extensions.api.access_policy import require_browser_origin
from ...extensions.api.access_session import CURRENT_IDENTITY
from ...extensions.api.chat_isolation import (
    authorize_chat_payload,
    chat_isolation_enabled,
    chat_scope,
    PortalChatScope,
    reject_reserved_legacy_namespace,
    require_owned_chat,
)
from ...extensions.api import trusted_chat_text
from ...utils.logging import LOG_FILE_PATH
from ..agent_context import get_agent_for_request
from ..approvals.display import approval_display_fields
from ..chats.portal_control import (
    PortalChatControl,
    PortalChatStopPending,
    PortalChatsPaused,
    PortalIncidentChanged,
    PortalIncidentReviewRequired,
    PortalRollbackUnavailable,
)
from ..chats.session import portal_turn_status
from ..chats.cmdb_retry import cmdb_enabled, retry_cmdb_lookup
from ..chats.model_only import stream_model_only
from ..chats.stopped_turn import (
    cmdb_asset_name,
    get_checkpoint,
    redact_reply,
    save_stopped_turn,
    stream_events,
    update_checkpoint_reply,
    visible_question,
)
from ..chats.text_continuation import _sse, stream_text_continuation
from ..chats.title_generator import generate_and_update_title
from ..utils import check_upload_size


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


def _chat_control(request: Request) -> PortalChatControl:
    control = getattr(request.app.state, "portal_chat_control", None)
    if control is None:
        control = PortalChatControl(
            SECRET_DIR / "portal-chat-control" / "state.json",
            EnvVarLoader.get_int("QWENPAW_PORTAL_CHAT_TIMEOUT_SECONDS", 900, min_value=1),
        )
        request.app.state.portal_chat_control = control
    return control


async def _start_chat_stream(request, scope, tracker, chat_id, payload, stream_fn, **kwargs):
    if scope is None:
        return await tracker.attach_or_start(chat_id, payload, stream_fn, **kwargs)
    try:
        return await _chat_control(request).start(tracker, chat_id, payload, stream_fn, **kwargs)
    except PortalChatsPaused as exc:
        raise HTTPException(503, "Portal 对话已被管理员关停，请等待管理员解除关停。") from exc


def _require_control_admin(request: Request):
    identity = CURRENT_IDENTITY.get()
    if identity is None or identity.source not in {"inoe", "qwenpaw", "mixed"}:
        raise HTTPException(401, "请先通过智观认证")
    if not identity.is_admin:
        raise HTTPException(403, "需要智观 AI 管理员权限")
    if request.method != "GET":
        require_browser_origin(request)
    return identity


class ChatControlRequest(BaseModel):
    paused: bool


@router.get("/chat/control")
async def get_portal_chat_control(request: Request, response: Response) -> dict:
    _require_control_admin(request)
    response.headers["Cache-Control"] = "no-store"
    if not chat_isolation_enabled():
        return {"enabled": False}
    return {"enabled": True, **await _chat_control(request).status()}


@router.post("/chat/control")
async def set_portal_chat_control(payload: ChatControlRequest, request: Request) -> dict:
    identity = _require_control_admin(request)
    if not chat_isolation_enabled():
        raise HTTPException(404, "当前未启用 Portal 会话隔离")
    control = _chat_control(request)
    try:
        if payload.paused:
            # A dropped admin connection must not interrupt a received stop command.
            state = await asyncio.shield(control.stop(identity.user_id))
        else:
            state = await control.reopen(identity.user_id)
    except PortalIncidentReviewRequired as exc:
        raise HTTPException(409, "请到安全与审计的「异常中止」页面复核并恢复。") from exc
    except PortalChatStopPending as exc:
        raise HTTPException(409, "仍有本地任务待确认停止，请刷新状态后再解除关停。") from exc
    return {"enabled": True, **state}


class ChatRollbackRequest(BaseModel):
    batch_id: str = Field(min_length=32, max_length=32)


@router.post("/chat/control/rollback")
async def rollback_portal_chat_batch(payload: ChatRollbackRequest, request: Request) -> dict:
    identity = _require_control_admin(request)
    if not chat_isolation_enabled():
        raise HTTPException(404, "当前未启用 Portal 会话隔离")

    async def resolve_target(agent_id: str, chat_id: str):
        workspace = await get_agent_for_request(request, agent_id=agent_id)
        chat = await workspace.chat_manager.get_chat(chat_id)
        if (
            chat is not None and chat.user_id.startswith("qpowner1")
            and PortalChatScope(chat.user_id.removeprefix("qpowner1")).owns(chat)
        ):
            return workspace, chat
        return None

    try:
        state = await asyncio.shield(_chat_control(request).rollback(identity.user_id, payload.batch_id, resolve_target))
    except PortalChatStopPending as exc:
        raise HTTPException(409, "仍有对话待确认停止，请刷新状态后再回滚。") from exc
    except PortalIncidentReviewRequired as exc:
        raise HTTPException(409, "异常中止批次需保全现场，不可使用批量回滚。") from exc
    except PortalRollbackUnavailable as exc:
        raise HTTPException(409, "当前关停批次不可回滚，请刷新状态。") from exc
    return {"enabled": True, **state}


class IncidentStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["unauthorized_execution", "unauthorized_network", "data_exposure", "other_risk"]


class IncidentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    confirm: Literal["确认复核并恢复"]


@router.get("/chat/control/incidents")
async def list_portal_incidents(request: Request, response: Response, page: int = Query(1, ge=1, le=100)) -> dict:
    _require_control_admin(request)
    response.headers["Cache-Control"] = "no-store"
    if not chat_isolation_enabled():
        return {"enabled": False}
    return {"enabled": True, **await _chat_control(request).incidents(page)}


@router.get("/chat/control/incidents/{batch_id}")
async def get_portal_incident(batch_id: str, request: Request, response: Response, page: int = Query(1, ge=1)) -> dict:
    _require_control_admin(request)
    response.headers["Cache-Control"] = "no-store"
    if not chat_isolation_enabled() or not re.fullmatch(r"[0-9a-f]{32}", batch_id):
        raise HTTPException(404, "未找到处置批次。")
    result = await _chat_control(request).incident(batch_id, page)
    if result is None:
        raise HTTPException(404, "未找到处置批次。")
    return result


@router.post("/chat/control/incidents/stop")
async def stop_portal_incident(payload: IncidentStopRequest, request: Request, response: Response) -> dict:
    identity = _require_control_admin(request)
    response.headers["Cache-Control"] = "no-store"
    if not chat_isolation_enabled():
        raise HTTPException(404, "当前未启用 Portal 会话隔离。")
    control = _chat_control(request)
    try:
        await asyncio.shield(control.stop(identity.user_id, payload.reason))
    except PortalIncidentChanged as exc:
        raise HTTPException(409, "已有中止批次，请刷新状态并核对当前记录。") from exc
    return {"enabled": True, **await control.incidents(1)}


@router.post("/chat/control/incidents/resume")
async def resume_portal_incident(payload: IncidentResumeRequest, request: Request, response: Response) -> dict:
    identity = _require_control_admin(request)
    response.headers["Cache-Control"] = "no-store"
    if not chat_isolation_enabled():
        raise HTTPException(404, "当前未启用 Portal 会话隔离。")
    control = _chat_control(request)
    try:
        await asyncio.shield(control.reopen(identity.user_id, reviewed_batch=payload.batch_id))
    except PortalIncidentChanged as exc:
        raise HTTPException(409, "待复核批次已变更，请刷新状态。") from exc
    except PortalChatStopPending as exc:
        raise HTTPException(409, "仍有本地任务未结束，请刷新核对后再恢复。") from exc
    return {"enabled": True, **await control.incidents(1)}


# ── Background task store ──


@dataclass
class _BackgroundTask:
    """In-memory state for a background chat task."""

    owner: str | None = None
    status: str = "submitted"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    asyncio_task: Optional[asyncio.Task] = None


_bg_tasks: Dict[str, _BackgroundTask] = {}
_bg_lock = asyncio.Lock()


class MarkInboxReadRequest(BaseModel):
    event_ids: list[str] = []
    all: bool = False


MAX_DEBUG_LOG_LINES = 1000


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


def _extract_placeholder_name(content_parts: list) -> tuple[str, str]:
    """Return ``(placeholder_name, first_user_text)`` for a new chat.

    The placeholder name shows up in the session drawer immediately while a
    background task asks the model for a real title. Content shapes match
    ``channels/base.py::_extract_chat_name``: dict blocks like
    ``{"type": "text", "text": "..."}``, raw strings, and objects with a
    ``.text`` attribute. Anything else (audio/image/file blocks) is treated
    as media and gets the generic "Media Message" placeholder.
    """
    if not content_parts:
        return "New Chat", ""
    content = content_parts[0]
    if not content:
        return "Media Message", ""
    if isinstance(content, str):
        first_text = content
    elif isinstance(content, dict):
        text = content.get("text", "")
        first_text = text if isinstance(text, str) else ""
    elif hasattr(content, "text"):
        first_text = content.text or ""
    else:
        first_text = ""
    if not first_text:
        return "Media Message", ""
    return first_text[:10], first_text


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract run_key (ChatSpec.id), session_id, and native payload.

    run_key must be ChatSpec.id (chat_id) so it matches list_chats/get_chat.
    """
    if isinstance(request_data, AgentRequest):
        channel_id = getattr(request_data, "channel", None) or "console"
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = (
            list(request_data.input[0].content) if request_data.input else []
        )
    else:
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = request_data.get("session_id", "default")
        input_data = request_data.get("input", [])
        content_parts = []
        for content_part in input_data:
            if hasattr(content_part, "content"):
                content_parts.extend(list(content_part.content or []))
            elif isinstance(content_part, dict) and "content" in content_part:
                # Coerce raw dicts to typed Content models so downstream
                # getattr checks (e.g. _content_has_text) see real attrs.
                content_parts.extend(
                    _coerce_content_item(c)
                    for c in (content_part["content"] or [])
                )

    meta: dict = {
        "session_id": session_id,
        "user_id": sender_id,
    }

    # Preserve request_context (e.g. session-level approval_level)
    if isinstance(request_data, AgentRequest):
        rc = getattr(request_data, "request_context", None)
    else:
        rc = request_data.get("request_context")
    if isinstance(rc, dict) and rc:
        meta["request_context"] = rc

    native_payload = {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "content_parts": content_parts,
        "meta": meta,
    }
    return native_payload


def _tail_text_file(
    path: Path,
    *,
    lines: int = 200,
    max_bytes: int = 512 * 1024,
) -> str:
    """Read the last N lines from a text file with bounded memory."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        if size == 0:
            return ""
        with open(path, "rb") as f:
            if size <= max_bytes:
                data = f.read()
            else:
                f.seek(max(size - max_bytes, 0))
                data = f.read()
        text = data.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        logger.exception("Failed to read backend debug log file")
        return ""


@router.post(
    "/chat",
    status_code=200,
    summary="Chat with console (streaming response)",
    description="Agent API Request Format. See runtime.agentscope.io. "
    "Use body.reconnect=true to attach to a running stream.",
)
@router.post("/chat/model-only", summary="Send a Portal chat without business tools")
async def post_console_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> StreamingResponse:
    """Stream agent response. Run continues in background after disconnect.
    Stop via POST /console/chat/stop. Reconnect with body.reconnect=true.
    """
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    try:
        native_payload = _extract_session_and_payload(request_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    model_only = request.url.path.endswith("/chat/model-only")
    scope = chat_scope()
    if model_only and (scope is None or getattr(workspace, "session", None) is None):
        raise HTTPException(503, "当前部署未启用隔离会话，无法关闭业务联网。")
    authorize_chat_payload(native_payload, scope)
    await trusted_chat_text.check_portal_input(native_payload["content_parts"], isolated=scope is not None)
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name, first_text = _extract_placeholder_name(
        native_payload["content_parts"],
    )
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        native_payload["sender_id"],
        native_payload["channel_id"],
        name=name,
    )
    tracker = workspace.task_tracker

    is_reconnect = isinstance(request_data, dict) and request_data.get("reconnect") is True
    if is_reconnect:
        if model_only:
            raise HTTPException(status_code=400, detail="Use the normal chat endpoint to reconnect.")
        queue = await tracker.attach(chat.id)
        if queue is None:
            return
    else:
        stop_options = {}
        stream_fn = console_channel.stream_one
        if scope is not None and getattr(workspace, "session", None) is not None:
            turn_id = uuid.uuid4().hex
            native_payload["meta"]["portal_turn_id"] = turn_id
            parts = native_payload["content_parts"]
            question = visible_question(parts)
            text_only = all(trusted_chat_text.get_text_block(part) is not None for part in parts)

            if model_only:
                if not text_only or not question.strip() or len(question) > trusted_chat_text.MAX_INPUT:
                    raise HTTPException(422, "关闭业务联网时仅支持非空的纯文本输入。")

                def stream_fn(_payload):
                    return stream_model_only(workspace, chat, turn_id, question)

            async def save_stop(buffer):
                return await save_stopped_turn(
                    workspace.session, chat, turn_id, question, buffer,
                    cmdb_available=(not model_only and text_only and bool(cmdb_asset_name(question))
                                    and cmdb_enabled(workspace)),
                )

            stop_options["on_stop"] = save_stop
            if scope.human:
                async def prepare_turn():
                    turn = await workspace.session.begin_portal_turn(chat, turn_id)
                    return _sse({"object": "portal_chat_turn", **turn})

                stop_options.update(portal_turn=(workspace.agent_id, turn_id), before_start=prepare_turn)
        queue, started = await _start_chat_stream(
            request, scope, tracker, chat.id, native_payload, stream_fn,
            join_existing=not model_only, **stop_options,
        )
        if queue is None:
            raise HTTPException(409, "当前对话已有任务运行，请先停止或等待任务结束。")
        # Do not start title generation for blocked requests or reconnects.
        if started and not model_only and first_text and chat.name == name:
            asyncio.create_task(generate_and_update_title(
                workspace=workspace,
                chat_id=chat.id,
                user_message=first_text,
                placeholder_name=name,
            ))

    return _chat_stream(tracker, queue, chat.id)


def _chat_stream(tracker, queue, chat_id: str) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        # Hold iterator so finally can aclose(); guarantees stream_from_queue's
        # finally (detach_subscriber) on client abort / generator teardown.
        stream_it = tracker.stream_from_queue(queue, chat_id)
        try:
            try:
                async for event_data in stream_it:
                    yield event_data
            except Exception:
                logger.exception("Console chat stream error")
                # Never surface raw exception text to the client; the full
                # detail is captured in the server log above.
                yield (
                    "data: "
                    + json.dumps(
                        {"error": "服务暂时遇到点问题，请稍后重试。"},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
        finally:
            await stream_it.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/chat/stop",
    status_code=200,
    summary="Stop running console chat",
)
async def post_console_chat_stop(
    request: Request,
    chat_id: str = Query(..., description="Chat id (ChatSpec.id) to stop"),
) -> dict:
    """Report what happened to the local task, independent of SSE disconnect."""
    workspace = await get_agent_for_request(request)
    tracker = workspace.task_tracker
    scope = chat_scope()
    if scope is not None:
        # In the isolated profile, accept only the registered chat UUID.
        await require_owned_chat(workspace.chat_manager, chat_id, scope)
        status, checkpoint = await tracker.stop_run_details(chat_id)
        feedback = {
            "stopped": status != "not_running",
            "status": status,
            "text_continuation": status in {"cancelled", "accepted"}
                and (checkpoint is None or checkpoint["mode"] == "text"),
        }
        if checkpoint is not None:
            feedback["checkpoint"] = checkpoint
        return feedback
    if workspace.chat_manager:
        existing = await workspace.chat_manager.get_chat(chat_id)
        if existing is not None:
            reject_reserved_legacy_namespace(existing.user_id, existing.session_id)
    reject_reserved_legacy_namespace("", chat_id)
    status = await tracker.stop_run(chat_id)
    if status == "not_running" and workspace.chat_manager:
        # Preserve legacy clients that send a session ID instead of a UUID.
        resolved_chat_id = await workspace.chat_manager.get_chat_id_by_session(
            session_id=chat_id, channel="console",
        )
        if resolved_chat_id and resolved_chat_id != chat_id:
            await require_owned_chat(workspace.chat_manager, resolved_chat_id, None)
            status = await tracker.stop_run(resolved_chat_id)
    return {"stopped": status != "not_running", "status": status}


class ChatRecallRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    turn_id: str = Field(min_length=32, max_length=32)


async def _recall_target(request: Request, chat_id: str):
    scope = chat_scope()
    if scope is None or not scope.human:
        raise HTTPException(404, "当前未启用 Portal 对话撤回")
    workspace = await get_agent_for_request(request)
    chat = await require_owned_chat(workspace.chat_manager, chat_id, scope)
    return workspace, chat


@router.get("/chat/recall")
async def get_recall_status(request: Request, response: Response, chat_id: str) -> dict:
    workspace, chat = await _recall_target(request, chat_id)
    response.headers["Cache-Control"] = "no-store"
    state = await workspace.session.get_session_state_dict(chat.session_id, chat.user_id, chat.channel)
    return {"portal_turn": portal_turn_status(state)}


@router.post("/chat/recall")
async def recall_portal_chat_turn(payload: ChatRecallRequest, request: Request) -> dict:
    require_browser_origin(request)
    workspace, chat = await _recall_target(request, payload.chat_id)
    try:
        result = await asyncio.shield(_chat_control(request).recall(workspace, chat, payload.turn_id))
    except PortalChatStopPending as exc:
        raise HTTPException(409, "对话仍在停止中，请稍后再撤回。") from exc
    if result != "recalled":
        raise HTTPException(409, "本轮对话已变化，请刷新会话后再撤回。")
    return {"recalled": True}


class TextContinuationRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=trusted_chat_text.MAX_INPUT)
    draft: str = Field(min_length=1, max_length=trusted_chat_text.MAX_INPUT)
    turn_id: str | None = Field(default=None, min_length=32, max_length=32)


@router.post("/chat/continue", summary="Continue a stopped Portal text reply")
async def post_console_chat_continue(
    payload: TextContinuationRequest,
    request: Request,
) -> StreamingResponse:
    scope = chat_scope()
    if scope is None:
        raise HTTPException(404, "当前未启用会话隔离，无法继续生成。")
    workspace = await get_agent_for_request(request)
    chat = await require_owned_chat(workspace.chat_manager, payload.chat_id, scope)
    await trusted_chat_text.check_portal_input([payload.question], isolated=True)
    await trusted_chat_text.check_portal_input([payload.draft], isolated=True)
    if not payload.question.strip() or not payload.draft.strip():
        raise HTTPException(422, "缺少可继续生成的正文。")

    async def generate(checkpoint):
        stored = None
        question, draft = checkpoint.question, checkpoint.draft
        if checkpoint.turn_id:
            stored = await get_checkpoint(workspace.session, chat, checkpoint.turn_id, "text")
            if stored is None:
                yield _sse({"error": "中止的回复已更新，请重新打开会话。"})
                return
            question, draft = stored[2:4]
        tail = ""
        sent_base = False
        async with aclosing(stream_text_continuation(workspace.agent_id, question, draft)) as stream:
            async for sse in stream:
                for event in stream_events([sse]):
                    if not stored:
                        break
                    if event.get("status") == "completed":
                        await update_checkpoint_reply(workspace.session, chat, stored, draft + tail, completed=True)
                    if isinstance(event.get("text"), str):
                        tail = event["text"]
                        if not sent_base:
                            sent_base = True
                            sse = _sse({**event, "draft": draft})
                yield sse

    async def save_continuation_stop(buffer):
        if not payload.turn_id:
            return None
        stored = await get_checkpoint(workspace.session, chat, payload.turn_id, "text")
        if stored is None:
            return None
        tail = ""
        for event in stream_events(buffer):
            if event.get("object") == "text_continuation" and isinstance(event.get("text"), str):
                tail = event["text"]
        return await update_checkpoint_reply(workspace.session, chat, stored, stored[3] + tail, completed=False)

    queue, _ = await _start_chat_stream(
        request, scope, workspace.task_tracker, chat.id, payload, generate, join_existing=False,
        on_stop=save_continuation_stop if payload.turn_id else None,
        portal_turn=(workspace.agent_id, payload.turn_id) if scope.human and payload.turn_id else None,
    )
    if queue is None:
        raise HTTPException(409, "当前对话仍有任务在运行，请稍后再继续生成。")
    return _chat_stream(workspace.task_tracker, queue, chat.id)


class CmdbRetryRequest(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    turn_id: str = Field(min_length=32, max_length=32)
    approval_level: str = "smart"


@router.post("/chat/retry-cmdb", summary="Retry a stopped Portal exact asset query")
async def post_console_retry_cmdb(payload: CmdbRetryRequest, request: Request) -> StreamingResponse:
    scope = chat_scope()
    if scope is None:
        raise HTTPException(404, "当前未启用会话隔离。")
    workspace = await get_agent_for_request(request)
    chat = await require_owned_chat(workspace.chat_manager, payload.chat_id, scope)
    tracker = workspace.task_tracker

    async def generate(checkpoint):
        stored = await get_checkpoint(workspace.session, chat, checkpoint.turn_id, "cmdb")
        name = cmdb_asset_name(stored[2]) if stored else None
        if not name:
            yield _sse({"error": "没有可继续的 CMDB 查询，请重新打开会话。"})
            return
        level = "strict" if checkpoint.approval_level == "strict" else "smart"
        result = redact_reply(await retry_cmdb_lookup(workspace, chat, name, level))
        draft = stored[3]
        text = result if draft == "本轮已停止，未生成回复。" else f"{draft}\n\n{result}"
        await update_checkpoint_reply(workspace.session, chat, stored, text, completed=True)
        yield _sse({"object": "portal_cmdb_retry", "text": text, "status": "completed"})

    async def preserve_checkpoint(_buffer):
        stored = await get_checkpoint(workspace.session, chat, payload.turn_id, "cmdb")
        return stored[-1].model_dump() if stored else None

    queue, _ = await _start_chat_stream(
        request, scope, tracker, chat.id, payload, generate, join_existing=False, on_stop=preserve_checkpoint,
        portal_turn=(workspace.agent_id, payload.turn_id) if scope.human else None,
    )
    if queue is None:
        raise HTTPException(409, "当前对话仍有任务在运行，请稍后再继续查询。")
    return _chat_stream(tracker, queue, chat.id)


@router.post("/upload", response_model=dict, summary="Upload file for chat")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(..., description="File to attach"),
) -> dict:
    """Save to console channel media_dir."""

    if trusted_chat_text.enabled():
        await trusted_chat_text.check_portal_input([{"type": "file"}], isolated=chat_scope() is not None)
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    media_dir = console_channel.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    check_upload_size(data)
    safe_name = _safe_filename(file.filename or "file")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"

    path = (media_dir / stored_name).resolve()
    path.write_bytes(data)
    return {
        "url": path,
        "file_name": safe_name,
        "size": len(data),
    }


@router.get(
    "/debug/backend-logs",
    response_model=dict,
    summary="Read backend daemon logs for debug page",
)
async def get_backend_debug_logs(
    lines: int = Query(
        200,
        ge=20,
        le=MAX_DEBUG_LOG_LINES,
        description="Number of trailing log lines to return",
    ),
) -> dict:
    """Return the tail of the project log file for the debug UI."""
    log_path = LOG_FILE_PATH.resolve()
    try:
        st = log_path.stat()
        return {
            "path": str(log_path),
            "exists": True,
            "lines": lines,
            "updated_at": st.st_mtime,
            "size": st.st_size,
            "content": _tail_text_file(log_path, lines=lines),
        }
    except FileNotFoundError:
        return {
            "path": str(log_path),
            "exists": False,
            "lines": lines,
            "updated_at": None,
            "size": 0,
            "content": "",
        }


@router.get("/push-messages")
async def get_push_messages(
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages and ALL approval requests.

    Messages:
    - With session_id: consumed messages for that session
    - Without session_id: recent messages (all sessions, last 60s)

    Approvals:
    - Always returns ALL pending approvals across all sessions
    - Frontend filters by current session_id for display
    - Includes session_id in each approval for filtering
    """
    from ..console_push_store import get_recent, take
    from ..approvals import get_approval_service

    # Get messages (session-specific or global)
    if session_id:
        messages = await take(session_id)
    else:
        messages = await get_recent()

    # Get ALL pending approvals (not filtered by session)
    approval_svc = get_approval_service()
    # pylint: disable=protected-access
    async with approval_svc._lock:
        all_pending = list(approval_svc._pending.values())

    # Serialize approval data with root_session_id for frontend filtering
    approvals_data = [
        {
            "request_id": p.request_id,
            "session_id": p.session_id,
            "root_session_id": p.root_session_id,
            "owner_agent_id": p.owner_agent_id,
            "agent_id": p.agent_id,
            "tool_name": p.tool_name,
            **approval_display_fields(p),
            "severity": p.severity,
            "findings_count": p.findings_count,
            "findings_summary": p.result_summary,
            "tool_params": p.extra.get("tool_call", {}).get("input", {}),
            "source_type": p.extra.get("source_type", "tool_guard"),
            "driver": p.extra.get("driver"),
            "created_at": p.created_at,
            "timeout_seconds": p.timeout_seconds,
        }
        for p in all_pending
    ]

    return {"messages": messages, "pending_approvals": approvals_data}


@router.get("/inbox/events")
async def get_inbox_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    unread_only: bool = Query(False),
):
    from ..inbox_store import list_events

    events = await list_events(
        limit=limit,
        offset=offset,
        source_type=source_type,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
    )
    return {"events": events}


@router.post("/inbox/read")
async def post_mark_inbox_read(payload: MarkInboxReadRequest):
    from ..inbox_store import mark_all_read, mark_read

    if payload.all:
        updated = await mark_all_read()
    else:
        updated = await mark_read(payload.event_ids)
    return {"updated": updated}


@router.delete("/inbox/events/{event_id}")
async def delete_inbox_event(event_id: str):
    from ..inbox_store import delete_event
    from ..inbox_trace_store import delete_trace

    deleted, run_id, run_id_still_referenced = await delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="event not found")
    trace_deleted = False
    if run_id and not run_id_still_referenced:
        trace_deleted = await delete_trace(run_id)
    return {
        "deleted": True,
        "trace_deleted": trace_deleted,
        "run_id": run_id,
    }


@router.get("/inbox/traces/{run_id}")
async def get_inbox_trace(run_id: str):
    from ..inbox_trace_store import get_trace

    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail="trace not found",
        )
    return trace


# ── Background chat task endpoints ──


def _parse_sse_payload(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE data line into a dict."""
    stripped = line.strip()
    if stripped.startswith("data: "):
        try:
            return json.loads(stripped[6:])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


@router.post(
    "/chat/task",
    status_code=200,
    summary="Submit a background chat task",
)
async def post_console_chat_task(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> dict:
    """Run an agent chat as a background task.

    Returns a ``task_id`` immediately. Poll status via
    ``GET /console/chat/task/{task_id}``.
    """
    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    task_id = f"task-{uuid.uuid4().hex[:12]}"
    native_payload = _extract_session_and_payload(request_data)
    scope = chat_scope()
    authorize_chat_payload(native_payload, scope)
    await trusted_chat_text.check_portal_input(native_payload["content_parts"], isolated=scope is not None)
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )

    task_timeout: Optional[float] = None
    if isinstance(request_data, dict):
        task_timeout = request_data.get("timeout")
    elif hasattr(request_data, "timeout"):
        task_timeout = getattr(request_data, "timeout", None)

    bg = _BackgroundTask(
        owner=scope.owner if scope is not None else None,
        status="running",
        started_at=time.time(),
    )

    async def _run() -> None:
        last_response: Optional[Dict[str, Any]] = None
        try:
            async for sse_line in console_channel.stream_one(
                native_payload,
            ):
                parsed = _parse_sse_payload(sse_line)
                if parsed and parsed.get("type") != "turn_usage":
                    last_response = parsed
        except asyncio.CancelledError:
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": "Task cancelled"},
            }
            return
        except Exception as exc:
            bg.status = "finished"
            bg.finished_at = time.time()
            bg.result = {
                "status": "failed",
                "error": {"message": str(exc)},
            }
            return

        bg.status = "finished"
        bg.finished_at = time.time()
        if last_response is not None:
            bg.result = {
                "status": "completed",
                "session_id": session_id,
                **last_response,
            }
        else:
            bg.result = {
                "status": "completed",
                "session_id": session_id,
                "output": [],
            }

    atask = asyncio.create_task(_run())
    bg.asyncio_task = atask

    if task_timeout is not None and task_timeout > 0:

        async def _timeout_guard() -> None:
            await asyncio.sleep(task_timeout)
            if not atask.done():
                atask.cancel()

        asyncio.create_task(_timeout_guard())

    async with _bg_lock:
        _bg_tasks[task_id] = bg

    return {"task_id": task_id}


@router.get(
    "/chat/task/{task_id}",
    status_code=200,
    summary="Check background chat task status",
)
async def get_console_chat_task(task_id: str) -> dict:
    """Return the current status of a background chat task."""
    async with _bg_lock:
        bg = _bg_tasks.get(task_id)
    scope = chat_scope()
    if bg is None or bg.owner != (scope.owner if scope is not None else None):
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}",
        )
    response: Dict[str, Any] = {"status": bg.status}
    if bg.started_at is not None:
        response["started_at"] = bg.started_at
    if bg.status == "finished" and bg.result is not None:
        response["result"] = bg.result
    return response
