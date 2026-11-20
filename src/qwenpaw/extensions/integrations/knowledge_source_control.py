"""Verified, account-bound confirmation for Portal knowledge deletion and archiving."""

from datetime import datetime, timezone
import hashlib
import os
import secrets
import time

from fastapi import HTTPException, Request

from ..api.access_policy import require_browser_origin
from ..api.access_session import CURRENT_IDENTITY
from ..api.delete_block_middleware import _delete_ops_disabled
from ..api.sso_settings_store import get_userinfo_url
from . import knowledge_base as kb

_CONFIRM_SECONDS = 180
_PROCESS = "qwenpaw:portal-knowledge-base"


def actor(request: Request) -> tuple[str, str]:
    identity = CURRENT_IDENTITY.get()
    if identity is None or not identity.user_id or identity.source not in {"inoe", "qwenpaw", "mixed"}:
        raise HTTPException(401, "请先通过智观认证")
    if not identity.is_admin:
        raise HTTPException(403, "需要智观 AI 管理员权限")
    if request.method != "GET":
        require_browser_origin(request)
    subject = identity.user_id
    scope = f"{get_userinfo_url()}\0{subject}\0{identity.family_id}"
    return hashlib.sha256(scope.encode()).hexdigest(), subject


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _connection():
    kb._ensure_engine()
    from core import db

    return db.connect()


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS portal_kb_source_confirmation (
        id INTEGER PRIMARY KEY AUTOINCREMENT, token_digest TEXT UNIQUE NOT NULL,
        owner TEXT NOT NULL, subject TEXT NOT NULL, source_id INTEGER NOT NULL,
        upload_version TEXT NOT NULL, archived_at TEXT, title TEXT NOT NULL,
        operation TEXT NOT NULL, unit_count INTEGER NOT NULL, expires REAL NOT NULL, updated TEXT NOT NULL,
        process TEXT NOT NULL, pid INTEGER NOT NULL, status TEXT NOT NULL,
        removed_files INTEGER, expected_files INTEGER)""")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare(owner: str, subject: str, source_id: int, *, operation: str = "delete") -> dict:
    if operation == "delete" and _delete_ops_disabled():
        raise HTTPException(403, "系统已禁用彻底删除。可改用归档，归档后可恢复。")
    token = secrets.token_urlsafe(32)
    expires = time.time() + _CONFIRM_SECONDS
    with _connection() as conn:
        _schema(conn)
        row = conn.execute("""SELECT id, filename, uploaded_at, archived_at,
            (SELECT COUNT(*) FROM child_chunk WHERE document_id=document.id) AS units
            FROM document WHERE id=?""", (source_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "知识库资料不存在")
        if operation == "archive" and row["archived_at"]:
            raise HTTPException(409, "资料已经归档")
        # Filename is used in the risk prompt; no paths, document contents or tokens go into audit.
        title = row["filename"]
        conn.execute("""INSERT INTO portal_kb_source_confirmation
            (token_digest,owner,subject,source_id,upload_version,archived_at,title,
             operation,unit_count,expires,updated,process,pid,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'prepared')""",
            (_digest(token), owner, subject, source_id, row["uploaded_at"],
             row["archived_at"], title, operation, row["units"], expires, _now(), _PROCESS, os.getpid()))
    return {"confirmation_token": token, "source_id": source_id, "title": title,
            "unit_count": row["units"], "expires_at": expires, "operation": operation,
            "risk": "高" if operation == "delete" else "中",
            "impact": ("资料及其检索片段将永久从知识库移除，智能体不再检索这份资料。系统会尝试清理原始上传文件。此操作无法撤销；需要保留资料时请先归档。"
                       if operation == "delete" else "归档后企业用户和智能体无法从知识库检索这份资料。原件保留，可在含归档列表中恢复。")}



def decide(owner: str, source_id: int, token: str, *, confirm: bool, phrase: str = "", operation: str = "delete") -> dict:
    expected = "确认归档" if operation == "archive" else "确认删除"
    if confirm and phrase != expected:
        raise HTTPException(400, f"请输入「{expected}」")
    if confirm and operation == "delete" and _delete_ops_disabled():
        raise HTTPException(403, "系统已禁用彻底删除")
    outcome = "cancelled"
    ids: list[int] = []
    paths: list[str] = []
    with _connection() as conn:
        _schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        entry = conn.execute("""SELECT * FROM portal_kb_source_confirmation
            WHERE token_digest=? AND owner=? AND source_id=? AND operation=? AND status='prepared'""",
            (_digest(token), owner, source_id, operation)).fetchone()
        if entry is None:
            raise HTTPException(409, "删除确认不存在、已使用或不属于当前登录会话")
        if time.time() >= entry["expires"]:
            outcome = "expired"
        elif confirm:
            current = conn.execute("""SELECT filename, uploaded_at, archived_at
                FROM document WHERE id=?""", (source_id,)).fetchone()
            if current is None or tuple(current) != (entry["title"], entry["upload_version"], entry["archived_at"]):
                outcome = "changed"
            elif operation == "archive":
                kb._archive_source_rows(conn, [source_id], "portal confirmed archive")
                outcome = "archived"
            else:
                ids, paths = kb._delete_source_rows(conn, [source_id])
                outcome = "index_deleted"
        conn.execute("""UPDATE portal_kb_source_confirmation
            SET status=?, updated=?, pid=?, expected_files=? WHERE id=?""",
            (outcome, _now(), os.getpid(), len(paths) if ids else None, entry["id"]))
    if outcome in {"expired", "changed"}:
        raise HTTPException(409, "删除确认已过期或资料状态已变化，请重新发起")
    if not ids:
        return {"status": outcome}
    result = kb._finish_source_deletion(ids, paths, "portal confirmed delete")
    status = "deleted" if result["removed_files"] == len(paths) else "file_cleanup_incomplete"
    with _connection() as conn:
        conn.execute("""UPDATE portal_kb_source_confirmation
            SET status=?, updated=?, removed_files=? WHERE id=?""",
            (status, _now(), result["removed_files"], entry["id"]))
    return {**result, "status": status}


def recent() -> list[dict]:
    with _connection() as conn:
        _schema(conn)
        rows = conn.execute("""SELECT id, updated, subject, process, pid, source_id,
            title, operation, unit_count, CASE WHEN status='prepared' AND expires<=?
                THEN 'expired' ELSE status END AS status,
            expected_files, removed_files FROM portal_kb_source_confirmation
            ORDER BY id DESC LIMIT 30""", (time.time(),)).fetchall()
    return [dict(row) for row in rows]
