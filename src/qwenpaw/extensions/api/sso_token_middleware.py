"""Validate INOE login state before protected HTTP requests."""

from urllib.parse import unquote

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qwenpaw.constant import EnvVarLoader
from qwenpaw.extensions.api import inoe_settings_store, sso_settings_store
from qwenpaw.extensions.api.sso_auth import (
    InoeTokenValidator,
    normalize_token,
)

_TOKEN_COOKIE = "qwenpaw_sso_token"
_PUBLIC_ENDPOINTS = {
    ("GET", "/api/portal/health"),
    ("GET", "/api/portal/employee-status"),
    ("GET", "/api/portal/sso/status"),
    ("POST", "/api/portal/knowledge-base/query"),
    ("POST", "/api/portal/sso/token-login"),
    ("POST", "/api/portal/sso/exchange"),
    ("POST", "/api/portal/sso/clear-login-cookie"),
}


def _canonical_path(path: str) -> str:
    if path == "/portal-api" or path.startswith("/portal-api/"):
        path = "/api/portal" + path[len("/portal-api") :]
    elif path.startswith("/copaw-api/"):
        path = path[len("/copaw-api") :]
    return path.rstrip("/") or "/"


def _request_token(request: Request) -> str:
    if "X-Inoe-Token" in request.headers:
        return normalize_token(request.headers["X-Inoe-Token"])
    return normalize_token(unquote(request.cookies.get(_TOKEN_COOKIE, "")))


def _use_cache(method: str, path: str) -> bool:
    if method in {"GET", "HEAD"}:
        return True
    if path.startswith("/api/agents/"):
        parts = path.split("/", 4)
        if len(parts) == 5:
            path = "/api/" + parts[4]
    return method == "POST" and path in {
        "/api/console/chat",
        "/api/console/chat/task",
    }


class SsoTokenMiddleware:
    """Keep verified credentials scoped to the complete streaming request."""

    def __init__(
        self, app: ASGIApp, validator: InoeTokenValidator | None = None
    ) -> None:
        self.app = app
        self.validator = validator or InoeTokenValidator()

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] == "lifespan":

            async def lifespan_send(message: Message) -> None:
                if message["type"] in {
                    "lifespan.shutdown.complete",
                    "lifespan.shutdown.failed",
                }:
                    await self.validator.aclose()
                await send(message)

            await self.app(scope, receive, lifespan_send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        enabled = EnvVarLoader.get_str("QWENPAW_SSO_TOKEN_REQUIRED", "true")
        if enabled.strip().lower() in {"false", "0", "no", "off"}:
            await self.app(scope, receive, send)
            return

        path = _canonical_path(request.url.path)
        if (
            request.method == "OPTIONS"
            or not (path == "/api" or path.startswith("/api/"))
            or (request.method, path) in _PUBLIC_ENDPOINTS
        ):
            await self.app(scope, receive, send)
            return

        token = _request_token(request)
        if not token:
            response = JSONResponse(
                status_code=401,
                content={
                    "code": "SSO_TOKEN_REQUIRED",
                    "detail": "缺少 SSO token，请先登录",
                },
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        try:
            user = await self.validator.validate(
                token,
                sso_settings_store.get_userinfo_url(),
                use_cache=_use_cache(request.method, path),
            )
        except HTTPException as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": (
                        "SSO_TOKEN_INVALID"
                        if exc.status_code == 401
                        else "SSO_VALIDATION_UNAVAILABLE"
                    ),
                    "detail": exc.detail,
                },
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        request.state.sso_user = user
        request.state.inoe_token = token
        ctx_token = inoe_settings_store.CURRENT_REQUEST_TOKEN.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            inoe_settings_store.CURRENT_REQUEST_TOKEN.reset(ctx_token)
