"""User-owned restrictions for the actual Portal agent invocation paths."""
from __future__ import annotations

import asyncio
import re
import shlex
import time
from pathlib import Path
from dataclasses import dataclass
from uuid import uuid4

from ..api.access_session import get_access_store
from ..traceability import trace_store

ASK_SECONDS = 60
TEMP_SECONDS = 900
CONTEXT_KEY = "_verified_portal_capabilities"
_OWNER = re.compile(r"qpowner1([0-9a-f]{32})")


@dataclass(frozen=True)
class PortalInvocation:
    owner: str
    agent: str
    session: str


def invocation_for(owner: str, agent: str, session: str, channel: str) -> PortalInvocation | None:
    match = _OWNER.fullmatch(str(owner))
    if channel == "console" and agent and match and re.fullmatch(
        f"qpsession1{match[1]}[0-9a-f]{{32}}", str(session),
    ):
        return PortalInvocation(owner, agent, session)
    return None


def invocation_from_runtime(ctx) -> PortalInvocation | None:
    request = getattr(ctx, "request", None)
    meta = getattr(request, "channel_meta", None)
    if not isinstance(meta, dict) or meta.get("portal_human_session") is not True:
        return None
    return invocation_for(
        getattr(request, "user_id", ""), getattr(ctx, "agent_id", "") or "default",
        getattr(ctx, "session_id", ""), getattr(request, "channel", ""),
    )


def invocation_from_context(context) -> PortalInvocation | None:
    value = (context or {}).get(CONTEXT_KEY)
    return value if isinstance(value, PortalInvocation) else None


def _schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS portal_capabilities (
        owner TEXT NOT NULL, agent TEXT NOT NULL, kind TEXT NOT NULL,
        name TEXT NOT NULL, mode TEXT NOT NULL, expires REAL,
        PRIMARY KEY (owner, agent, kind, name))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS portal_consent (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, agent TEXT NOT NULL,
        session TEXT NOT NULL, service TEXT NOT NULL, tool TEXT NOT NULL,
        state TEXT NOT NULL, expires REAL NOT NULL)""")


def settings(owner: str, agent: str) -> dict:
    with get_access_store()._connect() as conn:
        _schema(conn)
        rows = conn.execute(
            "SELECT kind,name,mode,expires FROM portal_capabilities WHERE owner=? AND agent=?",
            (owner, agent),
        ).fetchall()
    now = time.time()
    return {
        (row["kind"], row["name"]): (
            ("revoked", None) if row["expires"] is not None and row["expires"] <= now
            else (row["mode"], row["expires"])
        )
        for row in rows
    }


async def read_settings(scope: PortalInvocation) -> dict:
    return await asyncio.to_thread(settings, scope.owner, scope.agent)


def change(owner: str, agent: str, kind: str, name: str, mode: str) -> None:
    with get_access_store()._connect() as conn:
        _schema(conn)
        key = (owner, agent, kind, name)
        if mode == "default":
            conn.execute(
                "DELETE FROM portal_capabilities WHERE owner=? AND agent=? AND kind=? AND name=?", key,
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO portal_capabilities VALUES (?,?,?,?,?,?)",
                (*key, mode, time.time() + TEMP_SECONDS if mode == "temporary" else None),
            )
        if kind == "mcp" and mode == "revoked":
            conn.execute(
                "UPDATE portal_consent SET state='revoked' WHERE owner=? AND agent=? AND service=? AND state IN ('pending','allow')",
                (owner, agent, name),
            )


def decision(scope: PortalInvocation, kind: str, name: str) -> tuple[str, float | None]:
    default = "ask" if kind == "mcp" else "inherited"
    return settings(scope.owner, scope.agent).get((kind, name), (default, None))


def pending(scope: PortalInvocation) -> list[dict]:
    with get_access_store()._connect() as conn:
        _schema(conn)
        rows = conn.execute(
            "SELECT id,service,tool,expires FROM portal_consent WHERE owner=? AND agent=? AND session=? AND state='pending' AND expires>? ORDER BY rowid",
            (scope.owner, scope.agent, scope.session, time.time()),
        ).fetchall()
    return [dict(row) for row in rows]


def answer(scope: PortalInvocation, request_id: str, response: str) -> bool:
    with get_access_store()._connect() as conn:
        _schema(conn)
        row = conn.execute(
            "UPDATE portal_consent SET state=? WHERE id=? AND owner=? AND agent=? AND session=? AND state='pending' AND expires>?",
            (response, request_id, scope.owner, scope.agent, scope.session, time.time()),
        )
        return row.rowcount == 1


def _open_consent(scope: PortalInvocation, service: str, tool: str, call_id: str, expires: float) -> None:
    with get_access_store()._connect() as conn:
        _schema(conn)
        conn.execute("DELETE FROM portal_consent WHERE expires<=?", (time.time(),))
        conn.execute(
            "INSERT INTO portal_consent VALUES (?,?,?,?,?,?,?,?)",
            (call_id, scope.owner, scope.agent, scope.session, service, tool, "pending", expires),
        )


def _consent_state(call_id: str) -> str:
    with get_access_store()._connect() as conn:
        row = conn.execute("SELECT state FROM portal_consent WHERE id=?", (call_id,)).fetchone()
    return row[0] if row else "expired"


def _close_consent(call_id: str) -> None:
    with get_access_store()._connect() as conn:
        conn.execute("DELETE FROM portal_consent WHERE id=?", (call_id,))


async def audit(scope: PortalInvocation, kind: str, target: str, permission: str,
                outcome: str, basis: str, *, call_id: str | None = None,
                expires: float | None = None) -> None:
    await trace_store.record_event(
        scope.session, "authorization", {
            "authorization_id": call_id or uuid4().hex,
            "target_kind": kind, "target": target, "permission": permission,
            "decision": outcome, "basis": basis, "expires_at": expires,
        }, agent_id=scope.agent, user_id=scope.owner, channel="console",
    )


async def authorize_mcp(scope: PortalInvocation, service: str, tool: str) -> None:
    """Wait for this exact invocation, then recheck revocation at dispatch."""
    target = f"{service} / {tool}"
    mode, expires = await asyncio.to_thread(decision, scope, "mcp", service)
    call_id = uuid4().hex
    if mode == "ask":
        expires = time.time() + ASK_SECONDS
        await asyncio.to_thread(_open_consent, scope, service, tool, call_id, expires)
        try:
            await audit(scope, "mcp", target, "调用单个工具", "pending", "user_consent", call_id=call_id, expires=expires)
            while time.time() < expires:
                mode = await asyncio.to_thread(_consent_state, call_id)
                if mode != "pending":
                    break
                await asyncio.sleep(0.35)
            if time.time() >= expires:
                mode = "expired"
        except asyncio.CancelledError:
            await audit(scope, "mcp", target, "调用单个工具", "deny", "cancelled", call_id=call_id)
            raise
        finally:
            await asyncio.to_thread(_close_consent, call_id)
    latest, _ = await asyncio.to_thread(decision, scope, "mcp", service)
    if latest == "revoked" or (mode == "temporary" and latest != "temporary"):
        mode = "revoked"
    allowed = mode in {"allow", "temporary"}
    await audit(scope, "mcp", target, "调用单个工具", "allow" if allowed else "deny", mode,
                call_id=call_id, expires=expires)
    if not allowed:
        raise PermissionError("当前用户未授权此 MCP 调用（已拒绝、撤销或超时），没有发送工具请求。")


# Match the Skill storage layout for native guarded tool paths. The existing
# production guard still validates integrity, path boundaries and input.
def _skill_path_names(raw: str, base: Path) -> set[str]:
    path = base / Path(raw.replace("\\", "/")).expanduser()
    names = set()
    candidates = [path]
    try:
        candidates.append(path.resolve())
    except (OSError, RuntimeError, ValueError):
        pass  # The normal path and execution boundary validates syntax.
    for candidate in candidates:
        parts = candidate.parts
        names.update(parts[i + 1] for i, part in enumerate(parts[:-1]) if part == "skills")
    return names


def _tool_skills(tool: str, params: dict, workspace: Path) -> set[str]:
    if tool == "lookup_portal_cmdb_asset":
        return {"zgops-cmdb"}
    names = set()
    for field in ("file_path", "path", "filename", "pattern"):
        raw = params.get(field)
        if isinstance(raw, str) and raw:
            names.update(_skill_path_names(raw, workspace))
    if tool == "execute_shell_command":
        try:
            args = shlex.split(str(params.get("command") or ""))
        except ValueError:
            return names  # The production guard will reject invalid syntax.
        cwd = workspace / str(params.get("cwd") or "")
        if len(args) > 1 and args[1].endswith(".py"):
            names.update(_skill_path_names(args[1], cwd))
            script = Path(args[1]).name
            if script == "kb_search.py":
                names.add("knowledge-base")
            if script == "inspect_resource_metrics.py":
                names.update(("alarm-analyst", "zgops-cmdb"))
    return names


async def check_tool_skills(
    context: dict | None, tool: str, params: dict, *,
    dispatch: bool = False, call_id: str | None = None,
) -> None:
    scope = invocation_from_context(context)
    if scope is None:
        return
    from ...constant import WORKING_DIR

    workspace = Path((context or {}).get("_portal_workspace_dir") or WORKING_DIR)
    names = _tool_skills(tool, params, workspace)
    if not names:
        return
    overrides = await read_settings(scope)
    for name in sorted(names):
        mode, expires = overrides.get(("skill", name), ("inherited", None))
        kind, target = ("api", "智观 CMDB / 资产精确查询") if tool == "lookup_portal_cmdb_asset" else ("skill", name)
        if mode == "revoked":
            await audit(scope, kind, target, name, "deny", "user_revoked", call_id=call_id)
            raise PermissionError(f"当前用户已撤销此智能体的 Skill 权限：{name}。")
        if dispatch:
            basis = "cmdb_current_user" if kind == "api" else mode
            await audit(scope, kind, target, name, "allow", basis, call_id=call_id, expires=expires)


async def track_cmdb_outcome(context: dict | None, result, call_id: str):
    """Record an observed upstream result, without asset data or credentials."""
    from collections.abc import AsyncIterable
    from contextlib import aclosing

    scope = invocation_from_context(context)
    if scope is None:
        return result

    async def observe(chunk):
        status = (getattr(chunk, "metadata", None) or {}).get("portal_cmdb_status")
        if not status:
            return
        if status in {"access_denied", "upstream_auth_rejected", "authentication_required"}:
            outcome = "deny"
        elif status in {"ok", "no_visible_match"}:
            outcome = "allow"
        else:
            outcome = "unconfirmed"
        await audit(scope, "api", "智观 CMDB / 资产精确查询", "精确名称只读查询",
                    outcome, status, call_id=call_id)

    if not isinstance(result, AsyncIterable):
        await observe(result)
        return result

    async def chunks():
        iterator = aiter(result)
        async for chunk in iterator:
            await observe(chunk)
            yield chunk

    # The real FunctionTool iterator is an async generator with aclose.
    async def managed():
        async with aclosing(result):
            async for chunk in chunks():
                yield chunk

    return managed() if hasattr(result, "aclose") else chunks()
