# -*- coding: utf-8 -*-
"""Read-only security evidence; never initialize or migrate audit storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import logging
import sqlite3
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)


def require_evidence_admin(request: Request, response: Response) -> None:
    """Protect sensitive records even when production guards are disabled."""
    response.headers["Cache-Control"] = "no-store"
    identity = getattr(request.state, "access_identity", None)
    if identity is None or not identity.is_admin:
        raise HTTPException(403, "安全取证仅允许已验证的管理员访问")


router = APIRouter(
    prefix="/security/evidence",
    tags=["security-evidence"],
    dependencies=[Depends(require_evidence_admin)],
)

_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+")
_ASSIGNMENT = re.compile(
    r"(?i)((?:[\w-]*(?:token|password|passwd|secret|api[_-]?key|"
    r"access[_-]?key|credential|cookie|authorization)[\w-]*)"
    r"[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
)


def safe_origin(value: str) -> str:
    """Show only scheme/host/port, excluding URL credentials and all paths."""
    try:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return "[地址已隐藏]"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme}://{host}{port}"
    except ValueError:
        return "[地址已隐藏]"


def safe_text(value: object) -> str:
    """Bound and redact text; never return arbitrary extra payloads."""
    text = str(value or "")
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
        r"-----END [A-Z ]*PRIVATE KEY-----",
        "[已隐藏]",
        text,
    )
    text = _URL.sub(lambda match: safe_origin(match.group()), text)
    text = re.sub(r"(?i)\b(?:Bearer|Basic)\s+\S+", "[已隐藏]", text)
    text = _ASSIGNMENT.sub(r"\1[已隐藏]", text)
    text = re.sub(
        r"(?i)(--?[\w-]*(?:token|password|passwd|secret|api[_-]?key|"
        r"access[_-]?key|credential)[\w-]*\s+)"
        r"(?:\"[^\"]*\"|'[^']*'|\S+)",
        r"\1[已隐藏]",
        text,
    )
    text = re.sub(
        r"\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{16,}",
        "[已隐藏]",
        text,
    )
    text = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        "[已隐藏]",
        text,
    )
    return text[:2000]


def read_audit_page(db_path: Path, **filters) -> dict:
    """Read existing INTEGER-timestamp records without opening a writer."""
    base = {"records": [], "total": 0, "source": "governance/audit.db"}
    if not db_path.is_file():
        return {**base, "storage_status": "not_created"}
    clauses = []
    params = []
    for key in ("agent_id", "tool_name", "decision"):
        if filters.get(key):
            clauses.append(f"{key} = ?")
            params.append(filters[key])
    for key, operator in (("since", ">="), ("until", "<=")):
        if filters.get(key) is not None:
            clauses.append(f"ts {operator} ?")
            params.append(filters[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    try:
        # mode=ro also prevents accidentally creating a missing database.
        conn = sqlite3.connect(
            db_path.resolve().as_uri() + "?mode=ro",
            uri=True,
        )
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            schema = conn.execute("PRAGMA table_info(audit_events)")
            types = {row["name"]: row["type"].upper() for row in schema}
            if types.get("ts") != "INTEGER":
                return {**base, "storage_status": "unsupported_schema"}
            conn.execute("BEGIN")
            total = conn.execute(
                "SELECT COUNT(*) FROM audit_events" + where,
                params,
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT rowid, ts, agent_id, session_id, tool_name, target, "
                "decision, reason FROM audit_events"
                + where
                + " ORDER BY ts DESC, rowid DESC LIMIT ? OFFSET ?",
                [*params, filters["limit"], filters["offset"]],
            ).fetchall()
            records = []
            for row in rows:
                record = {
                    key: safe_text(value) if isinstance(value, str) else value
                    for key, value in dict(row).items()
                }
                # Shell/code targets may contain positional credentials.
                record["target"] = (
                    "[命令或代码参数已隐藏，请在受控环境核对原始请求]"
                    if any(
                        part in row["tool_name"].lower()
                        for part in ("shell", "python", "exec", "code")
                    )
                    else safe_text(row["target"])
                )
                record["reason"] = safe_text(row["reason"])
                records.append(record)
            return {
                **base,
                "storage_status": "available",
                "records": records,
                "total": total,
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # A read failure is not an empty successful audit query.
        logger.exception("Cannot read security audit evidence")
        raise HTTPException(503, "审计存储暂不可读，请检查服务日志") from exc


@router.get("/audit")
def get_audit(
    agent_id: str | None = Query(None, max_length=200),
    tool_name: str | None = Query(None, max_length=200),
    decision: Literal["allow", "deny", "ask", "sandbox_fallback"]
    | None = None,
    since: int | None = Query(None, ge=0),
    until: int | None = Query(None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
) -> dict:
    if since is not None and until is not None and since > until:
        raise HTTPException(422, "开始时间必须早于结束时间")
    return {
        **read_audit_page(
            WORKING_DIR / "governance" / "audit.db",
            agent_id=agent_id,
            tool_name=tool_name,
            decision=decision,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        ),
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "record_kind": "policy_decision",
        "execution_result": "not_recorded",
    }


@router.get("/protection")
def get_protection() -> dict:
    from ...extensions.security.output_guard import load_config
    from ...extensions.security.output_guard.redactor import _BUILTIN_PATTERNS
    from ...constant import EnvVarLoader

    settings = load_config()
    return {
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "output_guard": {
            "enabled": settings.enabled,
            "mode": settings.mode,
            "active": settings.active,
            "mask_streaming": settings.mask_streaming,
            "lexicon": "custom" if settings.lexicon_path else "bundled",
            "patterns": [
                {
                    "id": pattern.id,
                    "enabled": pattern.id not in settings.disabled_patterns,
                }
                for pattern in _BUILTIN_PATTERNS
            ],
        },
        "mcp_boundary": {
            "production_guards": EnvVarLoader.get_str(
                "QWENPAW_PRODUCTION_GUARDS",
                "true",
            ).lower()
            not in {"false", "0", "off", "no"},
            "declared_host_count": len(
                [
                    host
                    for host in EnvVarLoader.get_str(
                        "QWENPAW_MCP_ALLOWED_HOSTS",
                        "",
                    ).split(",")
                    if host.strip()
                ]
            ),
        },
        "scope": "resolved_configuration_only",
    }


@router.post("/redaction-check")
def check_redaction() -> dict:
    """Evaluate fixed fictional samples through the existing redactor only."""
    from ...extensions.security.output_guard import load_config, redact

    settings = load_config()
    samples = [
        ("API密钥（虚构）", "sk-demo0123456789abcdefghijklmnop"),
        ("Bearer凭据（虚构）", "Bearer demo0123456789abcdefghijklmnop"),
        ("普通文本", "这是一段普通的测试文本。"),
    ]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "synthetic_redactor_only",
        "active": settings.active,
        "results": [
            {
                "label": label,
                "input": text,
                "output": result,
                "hit_ids": hits,
                "changed": result != text,
            }
            for label, text in samples
            for result, hits in [redact(text, cfg=settings)]
        ],
    }
