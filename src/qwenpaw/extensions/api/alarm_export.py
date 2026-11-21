"""Controlled alarm exports and the shared export policy/ledger."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import runtime_data_paths
from ..integrations.portal_real_alarms import MAX_REAL_ALARM_LIMIT, read_alarm_export_rows
from ..portal_real_alarm_registry import filter_alarm_records, load_alarm_records
from . import text_privacy
from .access_policy import require_browser_origin
from .access_session import CURRENT_IDENTITY
from .inoe_settings_store import get_effective_token

router = APIRouter(tags=["alarm-export"])
DEFAULT_LIMIT = 10
CONFIRM_TTL = 300
_DATE = "%Y-%m-%d %H:%M:%S"


class RegistrySelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: Literal["registry"]
    status: str = Field(default="", max_length=256)
    search: str = Field(default="", max_length=256)


class LiveSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: Literal["live"]
    begin_time: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
    end_time: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
    is_clear: Literal["0", "1"]
    severity: str = Field(default="1,2,3,4", pattern=r"^[1-4](,[1-4]){0,3}$")
    keyword: str = Field(default="", max_length=120)
    manage_ip: str = Field(default="", max_length=128)
    resource_type: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def check_scope(self):
        if self.manage_ip and self.keyword:
            raise ValueError("告警导出不能同时使用管理 IP 和关键词")
        if datetime.strptime(self.begin_time, _DATE) >= datetime.strptime(self.end_time, _DATE):
            raise ValueError("告警导出的结束时间必须晚于开始时间")
        return self


Selection = Annotated[RegistrySelection | LiveSelection, Field(discriminator="source")]


class ConfirmExport(BaseModel):
    selection: Selection
    ticket: str = Field(min_length=43, max_length=43)


class ExportPolicy(BaseModel):
    max_rows: int = Field(strict=True, ge=1, le=MAX_REAL_ALARM_LIMIT)


def _actor(request: Request | None = None, *, admin: bool = False) -> str:
    identity = CURRENT_IDENTITY.get()
    if identity is None or not identity.user_id or identity.source not in {"inoe", "qwenpaw", "mixed"}:
        raise HTTPException(401, "请先登录智观")
    if admin and not identity.is_admin:
        raise HTTPException(403, "需要智观 AI 管理员权限")
    if request is not None and request.method != "GET":
        require_browser_origin(request)
    return identity.user_id


@contextmanager
def _db():
    path = runtime_data_paths.SETTINGS_DATA_DIR / "alarm_export.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS policy (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                max_rows INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                hash TEXT PRIMARY KEY, actor TEXT NOT NULL,
                fingerprint TEXT NOT NULL, expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS work_order_exports (
                hash TEXT PRIMARY KEY, binding TEXT NOT NULL,
                scope_agent TEXT NOT NULL, selection TEXT NOT NULL,
                records INTEGER NOT NULL, expires REAL NOT NULL,
                snapshot TEXT NOT NULL, confirm_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS work_order_expiry ON work_order_exports(expires);
            CREATE TABLE IF NOT EXISTS events (
                at REAL NOT NULL, actor TEXT NOT NULL, source TEXT NOT NULL,
                decision TEXT NOT NULL, records INTEGER NOT NULL,
                max_rows INTEGER NOT NULL
            );
        """)
        # Serialize policy changes and final release checks across web workers.
        db.execute("BEGIN IMMEDIATE")
        yield db


def _limit(db) -> int:
    row = db.execute("SELECT max_rows FROM policy WHERE singleton=1").fetchone()
    return ExportPolicy(max_rows=row[0]).max_rows if row else DEFAULT_LIMIT


def _audit(db, actor, source, decision, count, limit):
    db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
               (time.time(), actor, source, decision, count, limit))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _fingerprint(selection: Selection, rows: list[dict]) -> str:
    # Stable across equal-time row reordering by upstream. No alarm data is stored in the ticket.
    serialized = sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)
    return _digest(json.dumps([selection.model_dump(), serialized], sort_keys=True))


def registry_export_rows(status: str, search: str) -> list[dict]:
    return filter_alarm_records(load_alarm_records().values(), status, search)


def _records(selection: Selection, limit: int) -> tuple[int, list[dict]]:
    if isinstance(selection, RegistrySelection):
        rows = registry_export_rows(selection.status, selection.search)
        return len(rows), rows
    if not get_effective_token():
        raise HTTPException(403, "当前账号未连接告警平台，无法导出实时告警。")
    filters = {"isClear": selection.is_clear, "alarmSeverity": selection.severity}
    if selection.manage_ip:
        filters["neIp"] = selection.manage_ip
    if selection.keyword:
        filters["queryKey"] = selection.keyword
    if selection.resource_type:
        filters["alarmClassType"] = selection.resource_type
    try:
        return read_alarm_export_rows(
            limit, selection.begin_time, selection.end_time, filters,
        )
    except Exception as exc:
        raise HTTPException(502, "告警平台未返回可核实的完整数据，未导出文件。") from exc


def _preview(count: int, limit: int) -> dict:
    if count > limit:
        message = f"本次请求导出 {count} 条，单次最多 {limit} 条。请缩小时间范围或筛选条件后重试。"
    elif count == 0:
        message = "当前范围没有可导出的告警。"
    else:
        message = f"将导出 {count} 条告警明细，单次最多 {limit} 条。"
    return {"count": count, "max_rows": limit, "message": message}


def check_agent_export(selection: Selection) -> None:
    """Check real scoped row count before a tool offers any export action."""
    actor = _actor()
    with _db() as db:
        limit = _limit(db)
    count, rows = _records(selection, limit)
    with _db() as db:
        current_limit = _limit(db)
        if count > current_limit:
            _audit(db, actor, selection.source, "agent_blocked_limit", count, current_limit)
    if count > current_limit:
        raise HTTPException(422, _preview(count, current_limit)["message"])
    if count == 0:
        raise HTTPException(422, _preview(count, current_limit)["message"])
    if len(rows) != count:
        raise HTTPException(409, "无法核实本次导出的完整范围，请重试。")
    text_privacy.check_http("exports", rows)


def check_work_order_limit(count: int) -> tuple[int, bool]:
    """Use the same stored batch limit as alarm exports; never issue a ticket."""
    actor = _actor()
    with _db() as db:
        limit = _limit(db)
        if count > limit:
            _audit(db, actor, "work_order", "agent_blocked_limit", count, limit)
    return limit, count > limit


def work_order_limit() -> int:
    """Read the current limit for authenticated, non-release decisions."""
    _actor()
    with _db() as db:
        return _limit(db)


@router.get("/alarm-export-settings")
def get_export_policy(request: Request):
    _actor(request, admin=True)
    with _db() as db:
        return JSONResponse({"max_rows": _limit(db)}, headers={"Cache-Control": "no-store"})


@router.put("/alarm-export-settings")
def set_export_policy(policy: ExportPolicy, request: Request):
    actor = _actor(request, admin=True)
    with _db() as db:
        previous = _limit(db)
        db.execute("INSERT OR REPLACE INTO policy VALUES (1, ?)", (policy.max_rows,))
        _audit(db, actor, "policy", "limit_changed", previous, policy.max_rows)
    return policy


@router.get("/alarm-registry/export")
def legacy_export(request: Request, status: str = "", search: str = ""):
    """Never let the old GET endpoint bypass explicit confirmation."""
    actor = _actor(request)
    count = len(registry_export_rows(status, search))
    with _db() as db:
        limit = _limit(db)
        if count > limit:
            _audit(db, actor, "registry", "blocked_limit", count, limit)
    if count > limit:
        raise HTTPException(422, _preview(count, limit)["message"])
    raise HTTPException(409, "告警导出需要确认，请在告警处理台账中点击导出。")


@router.post("/alarm-export/preview")
def preview_export(selection: Selection, request: Request):
    actor = _actor(request)
    with _db() as db:
        limit = _limit(db)
    count, rows = _records(selection, limit)
    with _db() as db:
        limit = _limit(db)
        result = _preview(count, limit)
        if count > limit:
            _audit(db, actor, selection.source, "blocked_limit", count, limit)
        elif count > 0 and len(rows) == count:
            text_privacy.check_http("exports", rows)
            ticket = secrets.token_urlsafe(32)
            db.execute("DELETE FROM tickets WHERE expires <= ?", (time.time(),))
            db.execute("INSERT INTO tickets VALUES (?, ?, ?, ?)",
                       (_digest(ticket), actor, _fingerprint(selection, rows), time.time() + CONFIRM_TTL))
            result["ticket"] = ticket
        elif count > 0:
            result["message"] = "导出上限已变化，请重新预览。"
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/alarm-export/download")
def download_export(payload: ConfirmExport, request: Request):
    actor = _actor(request)
    selection = payload.selection
    key = _digest(payload.ticket)
    with _db() as db:
        grant = db.execute(
            "SELECT fingerprint FROM tickets WHERE hash=? AND actor=? AND expires>?", (key, actor, time.time()),
        ).fetchone()
        limit = _limit(db)
        if not grant:
            raise HTTPException(409, "导出确认已失效，请重新预览并确认。")
    count, rows = _records(selection, limit)
    error = None
    with _db() as db:
        current_limit = _limit(db)
        redeemed = db.execute(
            "DELETE FROM tickets WHERE hash=? AND actor=? AND expires>?", (key, actor, time.time()),
        ).rowcount
        if not redeemed:
            error = (409, "导出确认已失效，请重新预览并确认。")
        elif count > current_limit:
            _audit(db, actor, selection.source, "blocked_limit", count, current_limit)
            error = (422, _preview(count, current_limit)["message"])
        elif not count or len(rows) != count or _fingerprint(selection, rows) != grant[0]:
            _audit(db, actor, selection.source, "changed_selection", count, current_limit)
            error = (409, "告警范围或明细已变化，请重新预览并确认。")
        else:
            # Check again after confirmation; policy may have changed since preview.
            try:
                text_privacy.check_http("exports", rows)
            except HTTPException as exc:
                _audit(db, actor, selection.source, "blocked_privacy", count, current_limit)
                error = (exc.status_code, exc.detail)
            else:
                _audit(db, actor, selection.source, "released", count, current_limit)
    if error:
        raise HTTPException(*error)
    return JSONResponse({"total": count, "items": rows}, headers={
        "Cache-Control": "no-store", "Content-Disposition": "attachment; filename=alarms.json",
    })
