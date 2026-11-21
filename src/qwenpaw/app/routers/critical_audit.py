"""Administrator-only critical audit query, export, and integrity controls."""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator

from ...governance import audit_integrity
from . import security_evidence as evidence

logger = logging.getLogger(__name__)
_verify_lock = Lock()
router = APIRouter(
    prefix="/security/evidence/critical-audit",
    tags=["critical-audit"],
    dependencies=[Depends(evidence.require_evidence_admin)],
)

_KIND = """CASE
    WHEN decision <> '' THEN 'policy_decision'
    WHEN json_valid(extra) THEN CASE json_extract(extra, '$.kind')
        WHEN 'governance_activity' THEN 'governance_activity' ELSE 'tool_execution' END
    ELSE 'tool_execution' END"""
_ACTOR = """COALESCE(NULLIF(CASE WHEN json_valid(extra) THEN
    CASE WHEN json_type(extra, '$.auth_user_id') = 'text'
        THEN json_extract(extra, '$.auth_user_id') END END, ''), NULLIF(agent_id, ''), '')"""
_RESULTS = {
    "started",
    "success",
    "error",
    "denied",
    "cancelled",
    "returned",
    "unconfirmed",
    "http_completed",
    "http_error",
    "http_other",
}


class AuditQuery(BaseModel):
    kind: Literal["policy_decision", "tool_execution", "governance_activity"] | None = (
        None
    )
    subject: str | None = Field(None, max_length=200)
    operation: str | None = Field(None, max_length=200)
    result: (
        Literal[
            "allow",
            "deny",
            "ask",
            "sandbox_fallback",
            "started",
            "success",
            "error",
            "denied",
            "cancelled",
            "returned",
            "unconfirmed",
            "http_completed",
            "http_error",
            "http_other",
        ]
        | None
    ) = None
    since: int | None = Field(None, ge=0, le=253402300799999)
    until: int | None = Field(None, ge=0, le=253402300799999)
    before_id: int | None = Field(None, ge=1, le=2**63 - 1)
    through_id: int | None = Field(None, ge=0, le=2**63 - 1)
    limit: int = Field(50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_times(self):
        if (
            self.since is not None
            and self.until is not None
            and self.since > self.until
        ):
            raise ValueError("开始时间不能晚于结束时间")
        return self


@contextmanager
def _database(path: Path):
    if not path.is_file():
        yield None
        return
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    except sqlite3.Error as exc:
        logger.exception("Cannot read critical audit storage")
        raise HTTPException(503, "审计存储暂不可读，请检查服务日志") from exc
    finally:
        if conn is not None:
            conn.close()


def _path() -> Path:
    return evidence.WORKING_DIR / "governance" / "audit.db"


def _supported(conn: sqlite3.Connection) -> bool:
    fields = {
        row[1]: row[2].upper()
        for row in conn.execute("PRAGMA table_info(audit_events)")
    }
    return (
        fields.get("ts") == "INTEGER"
        and set(audit_integrity.EVENT_FIELDS.split(", ")) <= fields.keys()
    )


def _status(conn: sqlite3.Connection | None) -> dict:
    if conn is None:
        return {"state": "not_created"}
    if not _supported(conn):
        return {"state": "unsupported_schema"}
    return audit_integrity.status(conn)


def _decode(row: sqlite3.Row) -> dict:
    try:
        extra = json.loads(row["extra"])
    except (TypeError, ValueError):
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    kind, target = row["kind"], row["target"]
    tool = row["tool_name"] if isinstance(row["tool_name"], str) else "[未记录]"
    # This surface deliberately excludes raw paths, commands, and arguments.
    if kind == "governance_activity":
        target = evidence.safe_text(target) if isinstance(target, str) else "[未记录]"
    elif (
        kind == "policy_decision"
        and isinstance(target, str)
        and target.startswith(("https://", "http://"))
    ):
        target = evidence.safe_origin(target)
    elif target and target != tool:
        target = "[工具参数已隐藏]"
    else:
        target = evidence.safe_text(tool) or "[未记录]"
    result = extra.get("result")
    if kind == "policy_decision":
        result = "not_recorded"
    elif not isinstance(result, str) or result not in _RESULTS:
        result = "unconfirmed"
    call_id = extra.get("call_id")
    status = extra.get("http_status")
    timestamp = row["ts"]
    subject = extra.get("auth_user_id")
    has_account = isinstance(subject, str) and bool(subject)
    return {
        "id": row["rowid"],
        "kind": kind,
        "ts": (
            timestamp
            if type(timestamp) is int and 0 <= timestamp <= 253402300799999
            else None
        ),
        "subject": evidence.safe_text(row["subject"]) or "未记录",
        "subject_kind": (
            "anonymous"
            if extra.get("unverified") is True
            else "account" if has_account else "agent" if row["subject"] else "unknown"
        ),
        "operation": evidence.safe_text(tool),
        "target": target,
        "result": result,
        "decision": (
            evidence.safe_text(row["decision"]) if kind == "policy_decision" else None
        ),
        "call_id": (
            call_id
            if isinstance(call_id, str) and re.fullmatch(r"[0-9a-f]{32}", call_id)
            else None
        ),
        "http_status": status if type(status) is int and 100 <= status <= 599 else None,
    }


def _events(filters: AuditQuery) -> dict:
    base = {"records": [], "next_before_id": None, "through_id": 0}
    with _database(_path()) as conn:
        info = _status(conn)
        if info["state"] in {"not_created", "unsupported_schema"}:
            return {**base, "storage": info}
        through = filters.through_id
        if through is None:
            through = conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM audit_events"
            ).fetchone()[0]
        clauses, params = ["rowid <= ?"], [through]
        pairs = (
            (f"({_KIND}) = ?", filters.kind),
            (f"({_ACTOR}) = ?", filters.subject),
            ("tool_name = ?", filters.operation),
            ("ts >= ?", filters.since),
            ("ts <= ?", filters.until),
            ("rowid < ?", filters.before_id),
        )
        for clause, value in pairs:
            if value is not None:
                clauses.append(clause)
                params.append(value)
        if filters.result in {"allow", "deny", "ask", "sandbox_fallback"}:
            clauses.append("decision = ?")
            params.append(filters.result)
        elif filters.result is not None:
            clauses.append(
                "decision = '' AND (CASE WHEN json_valid(extra) THEN json_extract(extra, '$.result') END) = ?"
            )
            params.append(filters.result)
        rows = conn.execute(
            f"SELECT rowid, ts, tool_name, target, decision, extra, ({_KIND}) AS kind, ({_ACTOR}) AS subject "
            f"FROM audit_events WHERE {' AND '.join(clauses)} ORDER BY rowid DESC LIMIT ?",
            (*params, filters.limit + 1),
        ).fetchall()
        return {
            "storage": info,
            "records": [_decode(row) for row in rows[: filters.limit]],
            "through_id": through,
            "next_before_id": (
                rows[filters.limit - 1]["rowid"] if len(rows) > filters.limit else None
            ),
        }


@router.get("")
def get_critical_audit(filters: Annotated[AuditQuery, Query()]) -> dict:
    return {**_events(filters), "retention": audit_integrity.retention_policy()}


@router.post("/verify")
def verify_critical_audit(
    checkpoint: Annotated[str | None, Body(embed=True, max_length=120)] = None,
) -> dict:
    checkpoint = checkpoint.strip() if checkpoint is not None else None
    if checkpoint is not None and not audit_integrity.valid_checkpoint(checkpoint):
        raise HTTPException(422, "校验锚点格式无效")
    if not _verify_lock.acquire(blocking=False):
        raise HTTPException(429, "已有完整性校验正在执行")
    try:
        with _database(_path()) as conn:
            info = _status(conn)
            result = (
                audit_integrity.verify(conn, checkpoint)
                if info["state"] == "protected"
                else {
                    **info,
                    "checked_events": 0,
                    "external_match": False if checkpoint else None,
                }
            )
        return {**result, "checked_at": datetime.now(timezone.utc).isoformat()}
    finally:
        _verify_lock.release()


def _csv_cell(value: object) -> object:
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n"))
        or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


@router.post("/export")
def export_critical_audit(filters: AuditQuery) -> Response:
    if filters.through_id is None:
        raise HTTPException(422, "请先查询，再导出当前页")
    data = _events(filters)
    if data["storage"]["state"] != "protected":
        raise HTTPException(503, "审计存储状态异常")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    fields = (
        "id",
        "ts",
        "subject",
        "subject_kind",
        "kind",
        "operation",
        "target",
        "result",
        "decision",
        "http_status",
        "call_id",
    )
    writer.writerow((*fields, "time_utc"))
    for row in data["records"]:
        timestamp = (
            (
                datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(milliseconds=row["ts"])
            ).isoformat(timespec="milliseconds")
            if row["ts"] is not None
            else ""
        )
        writer.writerow((*(_csv_cell(row[key]) for key in fields), timestamp))
    return Response(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="critical-audit.csv"',
            "Cache-Control": "no-store",
        },
    )
