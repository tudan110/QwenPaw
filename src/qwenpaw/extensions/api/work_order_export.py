"""One-time browser release of an already authorized work-order snapshot."""
from __future__ import annotations

import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..security import portal_capabilities as permissions
from ..security.call_admission import Target, require_agent_tool, require_not_blocked
from ...security.secret_store import decrypt, encrypt, is_encrypted
from . import alarm_export, text_privacy
from .chat_isolation import chat_scope
from .sso_settings_store import get_userinfo_url

router = APIRouter(tags=["work-order-export"])
_HEADERS = {"Cache-Control": "no-store"}
_TOKEN = r"^[A-Za-z0-9_-]{43}$"
_MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_GONE = "这次工单导出已失效或已下载，请在对话中重新发起导出。"


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: str = Field(pattern=_TOKEN)


class DownloadInput(PreviewInput):
    ticket: str = Field(pattern=_TOKEN)


def _binding(actor: str) -> str:
    return alarm_export._digest(f"{get_userinfo_url()}\0{actor}")


def verify_actor_scope(context: dict) -> str:
    """Do not mint a browser grant for another human's scoped tool call."""
    alarm_export._actor()
    chat = chat_scope()
    scope = permissions.invocation_from_context(context)
    if chat is None and scope is None:
        return ""
    if chat is None or not chat.human or scope is None or scope.owner != chat.owner:
        raise HTTPException(403, "当前会话不允许导出工单，请在本人对话中重新发起。")
    return scope.agent


def _require_release_access(scope_agent: str) -> None:
    try:
        # Honor an administrator's newly saved tool/service deny and a user's
        # revocation. Do not ask again for an already authorized source read.
        require_agent_tool("check_work_order_export")
        require_not_blocked(Target("mcp_tool", "listWorkOrders", "order"))
    except PermissionError as exc:
        raise HTTPException(403, "当前权限不允许导出工单，未导出文件。") from exc
    chat = chat_scope()
    if bool(chat) != bool(scope_agent) or (chat and not chat.human):
        raise HTTPException(403, "当前会话不允许导出这批工单。")
    if chat and permissions.settings(chat.owner, scope_agent).get(("mcp", "order"), ("ask", None))[0] == "revoked":
        raise HTTPException(403, "工单访问权限已撤销，未导出文件。")


def _message(count: int, limit: int, selection: dict) -> str:
    label = "已办工单" if selection["classify"] == 5 else "待办工单"
    if count > limit:
        return f"已触发导出管控上限：当前范围匹配 {count} 条{label}，单次最多导出 {limit} 条。本次未导出。"
    return f"将导出 {count} 条{label}，单次最多导出 {limit} 条。"


def _prune(db, now: float) -> None:
    db.execute("DELETE FROM work_order_exports WHERE expires<=?", (now,))


def prepare(selection: dict, rows: list[dict], scope_agent: str) -> tuple[str, int]:
    """Stage only a bounded, policy-checked, encrypted snapshot; never rows in the link."""
    actor = alarm_export._actor()
    count = len(rows)
    with alarm_export._db() as db:
        limit = alarm_export._limit(db)
        if count > limit:
            alarm_export._audit(db, actor, "work_order", "agent_blocked_limit", count, limit)
    if count > limit:
        raise HTTPException(422, _message(count, limit, selection))
    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if not count or len(data.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
        raise HTTPException(422, "工单明细文件过大，请缩小查询范围后重试。")
    _require_release_access(scope_agent)
    text_privacy.check_http("exports", rows)
    text_privacy.check_http("cache", rows)
    encrypted = encrypt(data)
    intent = secrets.token_urlsafe(32)
    now = time.time()
    binding = _binding(actor)
    with alarm_export._db() as db:
        limit = alarm_export._limit(db)
        if count > limit:
            alarm_export._audit(db, actor, "work_order", "agent_blocked_limit", count, limit)
        else:
            _prune(db, now)
            db.execute("""DELETE FROM work_order_exports WHERE hash IN (
                SELECT hash FROM work_order_exports WHERE binding=? ORDER BY expires DESC LIMIT -1 OFFSET 3
            )""", (binding,))
            db.execute("INSERT INTO work_order_exports VALUES (?, ?, ?, ?, ?, ?, ?, NULL)", (
                alarm_export._digest(intent), binding, scope_agent, json.dumps(selection),
                count, now + alarm_export.CONFIRM_TTL, encrypted,
            ))
    if count > limit:
        raise HTTPException(422, _message(count, limit, selection))
    return intent, limit


@router.post("/work-order-export/preview")
def preview_work_order_export(payload: PreviewInput, request: Request):
    actor = alarm_export._actor(request)
    binding, key = _binding(actor), alarm_export._digest(payload.intent)
    with alarm_export._db() as db:
        now = time.time()
        grant = db.execute("""SELECT scope_agent, selection, records FROM work_order_exports
                            WHERE hash=? AND binding=? AND expires>?""", (key, binding, now)).fetchone()
        if not grant:
            _prune(db, now)
            return JSONResponse({"detail": _GONE}, status_code=409, headers=_HEADERS)
        agent, saved_selection, count = grant
        _require_release_access(agent)
        selection = json.loads(saved_selection)
        limit = alarm_export._limit(db)
        result = {"count": count, "max_rows": limit, "message": _message(count, limit, selection), "scope": selection}
        if count <= limit:
            ticket = secrets.token_urlsafe(32)
            db.execute("UPDATE work_order_exports SET confirm_hash=? WHERE hash=?", (alarm_export._digest(ticket), key))
            result["ticket"] = ticket
        else:
            db.execute("UPDATE work_order_exports SET confirm_hash=NULL WHERE hash=?", (key,))
            alarm_export._audit(db, actor, "work_order", "blocked_limit", count, limit)
        _prune(db, now)
    return JSONResponse(result, headers=_HEADERS)


@router.post("/work-order-export/download")
def download_work_order_export(payload: DownloadInput, request: Request):
    actor = alarm_export._actor(request)
    key, binding = alarm_export._digest(payload.intent), _binding(actor)
    confirm = alarm_export._digest(payload.ticket)
    error = None
    with alarm_export._db() as db:
        now = time.time()
        grant = db.execute("""SELECT scope_agent, selection, records, snapshot FROM work_order_exports
                         WHERE hash=? AND binding=? AND confirm_hash=? AND expires>?""",
                           (key, binding, confirm, now)).fetchone()
        if not grant:
            _prune(db, now)
            return JSONResponse({"detail": _GONE}, status_code=409, headers=_HEADERS)
        agent, saved_selection, count, snapshot = grant
        db.execute("DELETE FROM work_order_exports WHERE hash=?", (key,))
        _prune(db, now)
        limit = alarm_export._limit(db)
        if count > limit:
            alarm_export._audit(db, actor, "work_order", "blocked_limit", count, limit)
            error = HTTPException(422, _message(count, limit, json.loads(saved_selection)))
        else:
            try:
                _require_release_access(agent)
                if not is_encrypted(snapshot):
                    raise ValueError
                rows = json.loads(decrypt(snapshot))
                if not isinstance(rows, list) or len(rows) != count:
                    raise ValueError
                text_privacy.check_http("exports", rows)
            except HTTPException as exc:
                error = exc
                decision = "blocked_access" if exc.status_code in {401, 403} else "blocked_privacy"
                alarm_export._audit(db, actor, "work_order", decision, count, limit)
            except (TypeError, ValueError):
                error = HTTPException(409, _GONE)
            else:
                alarm_export._audit(db, actor, "work_order", "released", count, limit)
    if error:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=_HEADERS)
    return JSONResponse({"total": count, "items": rows}, headers={
        **_HEADERS, "Content-Disposition": 'attachment; filename="work-orders.json"',
    })
