"""Record selected critical API actions without collecting request payloads."""

from __future__ import annotations

import asyncio
import logging
import re
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .audit import AuditLog

logger = logging.getLogger(__name__)

# Use a small, explicit catalogue of routes. Only server-generated opaque
# document/operation IDs may be written; never store bodies or query strings.
_FIXED = {
    ("PUT", "/api/portal/platform-ai-model-settings"): "model.settings.update",
    (
        "POST",
        "/api/security/boundaries/delete-protection/enable",
    ): "security.delete-protection.enable",
    ("PUT", "/api/config/security/tool-guard"): "security.tool-guard.update",
    ("PUT", "/api/config/security/file-guard"): "security.file-guard.update",
    ("PUT", "/api/config/security/skill-scanner"): "security.skill-scanner.update",
    (
        "PUT",
        "/api/config/security/allow-no-auth-hosts",
    ): "security.allowed-hosts.update",
    ("POST", "/api/mcp"): "mcp.client.register",
    ("POST", "/api/console/chat/control"): "chat.control.update",
    ("POST", "/api/console/chat/control/rollback"): "chat.control.rollback",
    ("POST", "/api/console/chat/control/incidents/stop"): "chat.incident.stop",
    ("POST", "/api/console/chat/control/incidents/resume"): "chat.incident.resume",
    ("POST", "/api/portal/agent-permissions"): "agent.permission.request",
    ("PUT", "/api/portal/alarm-export-settings"): "alarm.export.policy",
    ("POST", "/api/portal/alarm-export/download"): "alarm.export.download",
    ("POST", "/api/portal/work-order-export/download"): "work_order.export.download",
    ("POST", "/api/security/evidence/critical-audit/export"): "audit.export",
    **{
        ("POST", f"/api/access-control/{route}"): "access." + route.replace("/", ".")
        for route in (
            "pending/approve",
            "pending/deny",
            "pending/dismiss",
            "whitelist/add",
            "whitelist/remove",
            "blacklist/add",
            "blacklist/remove",
        )
    },
}
_DOCS = "/api/portal/controlled-documents"
_FIXED.update(
    {
        ("POST", _DOCS + route): operation
        for route, operation in {
            "/documents": "document.register",
            "/operations": "document.operation.request",
            "/admin/sensitive-data/check": "document.sensitive-data.check",
            "/admin/emergency": "document.emergency.update",
            "/admin/policy": "document.policy.update",
        }.items()
    }
)
_DYNAMIC = [
    ("PUT", re.compile("/api/mcp/policy/(.+)"), "mcp.policy.update"),
    (
        "POST",
        re.compile("/api/portal/agent-permissions/requests/([^/]+)"),
        "agent.permission.review",
    ),
    *(
        (method, re.compile(_DOCS + route), operation)
        for method, route, operation in (
            ("GET", r"/documents/([^/]+)", "document.read"),
            ("POST", r"/admin/documents/([^/]+)/publish", "document.publish"),
            ("POST", r"/operations/([^/]+)/confirm", "document.operation.confirm"),
            ("POST", r"/admin/review/([^/]+)", "document.operation.review"),
            ("POST", r"/operations/([^/]+)/execute", "document.operation.execute"),
            ("POST", r"/operations/([^/]+)/download", "document.download"),
            (
                "POST",
                r"/operations/([^/]+)/control/[^/]+",
                "document.operation.control",
            ),
            ("POST", r"/grants/([^/]+)/revoke", "document.grant.revoke"),
            ("POST", r"/admin/policy/([^/]+)/restore", "document.policy.restore"),
            ("POST", r"/admin/incidents/([^/]+)/resolve", "document.incident.resolve"),
        )
    ),
]


def classify_operation(method: str, path: str) -> tuple[str, str] | None:
    path = path.rstrip("/")
    operation = _FIXED.get((method, path))
    if operation:
        return operation, path
    for verb, pattern, operation in _DYNAMIC:
        match = pattern.fullmatch(path) if method == verb else None
        if match:
            identifier = match.group(1)
            target = (
                identifier
                if re.fullmatch(r"[a-f0-9]{32}", identifier)
                else "[ID 未记录]"
            )
            return operation, target
    return None


class CriticalActivityAuditMiddleware:
    """Journal before dispatch; distinguish HTTP results from business outcomes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        activity = None
        if scope["type"] == "http":
            path, root = scope["path"], scope.get("root_path", "").rstrip("/")
            if root and path.startswith(root + "/"):
                path = path[len(root) :]
            activity = classify_operation(scope["method"], path)
        if activity is None:
            await self.app(scope, receive, send)
            return
        operation, target = activity
        state = scope.get("state", {})
        identity = state.get("access_identity")
        local = state.get("user")
        subject = getattr(identity, "user_id", None) or (
            f"local:{local}" if local else ""
        )
        call_id = uuid4().hex

        def record(result: str, status: int | None = None) -> None:
            AuditLog.get_instance().record_activity(
                subject=subject or "anonymous",
                operation=operation,
                target=target,
                call_id=call_id,
                result=result,
                http_status=status,
                unverified=not subject,
            )

        try:
            await run_in_threadpool(record, "started")
        except Exception:
            logger.exception(
                "Cannot start critical activity audit: operation=%s", operation
            )
            await JSONResponse(
                {"detail": "审计存储不可写，未执行该操作"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return

        status = None

        async def observe(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        result = "unconfirmed"
        try:
            await self.app(scope, receive, observe)
            if status is not None:
                result = (
                    "http_completed"
                    if 200 <= status < 300
                    else (
                        "denied"
                        if status in (401, 403)
                        else "http_error" if status >= 400 else "http_other"
                    )
                )
        except asyncio.CancelledError:
            result = "cancelled"
            raise
        except Exception:
            result = "http_error"
            raise
        finally:
            try:
                await run_in_threadpool(record, result, status)
            except Exception:
                logger.exception(
                    "Cannot finish critical activity audit: call_id=%s", call_id
                )
