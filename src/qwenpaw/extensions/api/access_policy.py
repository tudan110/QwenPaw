# -*- coding: utf-8 -*-
"""Default-deny administrative API policy, independent of client user_id."""

from __future__ import annotations

from fastapi import HTTPException, Request
from qwenpaw.constant import EnvVarLoader

from .access_session import AccessIdentity


def require_browser_origin(request: Request) -> None:
    """Require a trusted Origin for cookie-bearing or browser writes."""
    origin = request.headers.get("Origin", "")
    if (
        not origin
        and not request.cookies
        and not request.headers.get("Sec-Fetch-Site")
    ):
        return
    allowed = {
        f"{request.url.scheme}://{request.url.netloc}",
        *(
            value.strip()
            for value in EnvVarLoader.get_str(
                "QWENPAW_BROWSER_ORIGINS", ""
            ).split(",")
            if value.strip()
        ),
    }
    if not origin or origin not in allowed:
        raise HTTPException(403, "登录或 Cookie 写请求来源不被允许")


_ADMIN_PREFIXES = (
    "/api/envs",
    "/api/providers",
    "/api/mcp",
    "/api/plugins",
    "/api/skills",
    "/api/security",
    "/api/workspace",
    "/api/agent-config",
    "/api/approval",
    "/api/backup",
    "/api/backups",
    "/api/config",
    "/api/tools",
    "/api/access-control",
    "/api/local-models",
    "/api/acp",
    "/api/coding",
    "/api/coding-mode",
    "/api/loops",
)
_USER_POST_PATHS = {
    "/api/chats",
    "/api/console/chat",
    "/api/console/chat/task",
    "/api/console/chat/stop",
    "/api/console/chat/continue",
    "/api/console/upload",
    "/api/console/inbox/read",
    "/api/portal/sso/logout",
    "/api/portal/sso/token-login",
    "/api/portal/sso/exchange",
    "/api/portal/sso/clear-login-cookie",
    "/api/portal/knowledge-base/query",
    "/api/portal/knowledge-base/rag-synthesize",
    "/api/portal/alarm-analyst/diagnose",
    "/api/portal/alarm-analyst/cards",
    "/api/portal/fault-disposal/diagnose",
    "/api/portal/kunlun-adapter/v1/chat/completions",
    "/api/portal/qiming-adapter/v1/chat/completions",
    "/api/portal/xingchen-adapter/v1/chat/completions",
}
_SECURITY_KEYS = {
    "SSO_TOKEN_REQUIRED",
    "AUTH_ENABLED",
    "AUTH_USERNAME",
    "AUTH_PASSWORD",
    "ADMIN_INOE_USER_IDS",
    "PRODUCTION_GUARDS",
    "TRUSTED_CHAT_ISOLATION",
    "TRUSTED_CHAT_TEXT_GUARD",
    "CONTROLLED_DOCUMENTS",
    "ALLOWED_SCRIPT_HASHES",
    "INTERNAL_API_ORIGINS",
    "SKILL_SEED_PATH",
    "DELETE_OPS_DISABLED",
    "SSO_USERINFO_PATH",
    "SSO_GATEWAY_BASE_URL",
    "INTERNAL_MODEL_KEY",
    "READONLY_TOOL_NAMES",
    "TRUSTED_PROXY_CIDRS",
    "INOE_LOGIN_URL",
    "MCP_ALLOWED_HOSTS",
    "MCP_ALLOWED_ENDPOINTS",
    "MCP_ALLOWED_COMMANDS",
    "BROWSER_ORIGINS",
    "REQUEST_ACCESS_TOKEN",
    "REQUEST_INOE_TOKEN",
    "REQUEST_COLLABORATION_TOKEN",
    "CORS_ORIGINS",
    "ALLOWED_MEDIA_HOSTS",
}


def protected_env_key(key: str) -> bool:
    if key in {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "PATH",
        "PYTHONPATH",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    }:
        return True
    for prefix in ("QWENPAW_", "COPAW_"):
        if key.startswith(prefix):
            return key[len(prefix) :] in _SECURITY_KEYS
    return False


def is_model_adapter(path: str) -> bool:
    path = resource_path(path)
    return path in {
        f"/api/portal/{provider}-adapter/v1/{endpoint}"
        for provider in ("kunlun", "qiming", "xingchen")
        for endpoint in ("models", "chat/completions")
    }


def resource_path(path: str) -> str:
    if path.startswith("/api/agents/"):
        parts = path.split("/", 4)
        return "/api/" + parts[4] if len(parts) == 5 else "/api/agents"
    return path


def requires_admin(method: str, path: str) -> bool:
    # Complete profiles contain channel, MCP and tool credentials. Discovery
    # and agent-scoped business APIs retain their own resource policies.
    if (
        path.startswith("/api/agents/")
        and len(path.rstrip("/").split("/")) == 4
    ):
        return True
    path = resource_path(path)
    if any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in _ADMIN_PREFIXES
    ):
        return True
    if path.startswith("/api/portal/") and (
        path.split("/")[3].endswith("-settings")
        or path.split("/")[3] == "settings"
        or path.startswith("/api/portal/sso/sso-settings")
        or "/fde/" in path
        or "/app-artifacts" in path
        or "/proxy-datasources" in path
    ):
        return True
    if path.startswith("/api/models") and path != "/api/models/active":
        return True
    # The resource router checks owner/grant on user requests and admin on its admin subtree.
    if path.startswith("/api/portal/controlled-documents/"):
        return path.startswith("/api/portal/controlled-documents/admin/")
    if method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if method == "POST" and path in _USER_POST_PATHS:
        return False
    if method in {"PUT", "PATCH"} and path.startswith("/api/chats/"):
        return False
    return True


def can_manage_ai(identity: AccessIdentity | None) -> bool:
    """Match the administrative API policy for the current request."""
    from qwenpaw.extensions.security.execution_policy import enabled

    return not enabled() or (identity is not None and identity.is_admin)


def authorize_request(
    identity: AccessIdentity, method: str, path: str
) -> None:
    if requires_admin(method, path) and not can_manage_ai(identity):
        raise HTTPException(403, "此操作仅允许授权的 AI 管理员执行")
