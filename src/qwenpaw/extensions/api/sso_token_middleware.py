"""Validate INOE login state before protected HTTP requests."""

from urllib.parse import unquote
from datetime import datetime, timezone
import logging
import sqlite3

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
from .access_session import (
    ACCESS_COOKIE,
    CURRENT_IDENTITY,
    LOCAL_TOKEN_PREFIX,
    AccessIdentity,
    get_access_store,
    user_subject,
)
from .access_policy import authorize_request, is_model_adapter, requires_admin
from .model_access import verify_model_service_key

logger = logging.getLogger(__name__)

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


def _local_token(request: Request) -> str:
    if "X-QwenPaw-Access-Token" in request.headers:
        return normalize_token(request.headers["X-QwenPaw-Access-Token"])
    authorization = normalize_token(request.headers.get("Authorization", ""))
    if authorization.startswith(LOCAL_TOKEN_PREFIX):
        return authorization
    if "X-Inoe-Token" in request.headers:
        legacy = _request_token(request)
        return legacy if legacy.startswith(LOCAL_TOKEN_PREFIX) else ""
    cookie = request.cookies.get(ACCESS_COOKIE, "")
    if cookie:
        return unquote(cookie)
    legacy = _request_token(request)
    return legacy if legacy.startswith(LOCAL_TOKEN_PREFIX) else ""


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
        "/api/portal/sso/logout",
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
        disabled = enabled.strip().lower() in {"false", "0", "no", "off"}

        path = _canonical_path(request.url.path)
        if (
            request.method == "OPTIONS"
            or not (path == "/api" or path.startswith("/api/"))
            or (request.method, path) in _PUBLIC_ENDPOINTS
        ):
            await self.app(scope, receive, send)
            return

        local_token = _local_token(request)
        token = _request_token(request)
        model_key = (
            request.headers.get("X-QwenPaw-Model-Key", "")
            if is_model_adapter(path)
            else ""
        )
        if disabled and not local_token and not token:
            from qwenpaw.extensions.security.execution_policy import (
                enabled as production_guards_enabled,
            )

            strict = production_guards_enabled()
            if not strict or not is_model_adapter(path):
                if strict and requires_admin(request.method, path):
                    response = JSONResponse(
                        status_code=403,
                        content={
                            "code": "ACCESS_DENIED",
                            "detail": "管理操作需要可信管理员身份",
                        },
                    )
                    await response(scope, receive, send)
                else:
                    await self.app(scope, receive, send)
                return
        if "X-QwenPaw-Access-Token" in request.headers and not local_token:
            token = ""
            model_key = ""
        if not token and not local_token and not model_key:
            response = JSONResponse(
                status_code=401,
                content={
                    "code": "SSO_TOKEN_REQUIRED",
                    "detail": "缺少 SSO token，请先登录",
                    "stage": "request_authentication",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        try:
            explicit = (
                "X-Inoe-Token" in request.headers
                or "X-QwenPaw-Access-Token" in request.headers
                or normalize_token(
                    request.headers.get("Authorization", "")
                ).startswith(LOCAL_TOKEN_PREFIX)
            )
            if (
                not explicit
                and (token or local_token)
                and request.method not in {"GET", "HEAD", "OPTIONS"}
            ):
                origin = request.headers.get("Origin", "")
                current_origin = f"{request.url.scheme}://{request.url.netloc}"
                allowed = {
                    current_origin,
                    *(
                        value.strip()
                        for value in EnvVarLoader.get_str(
                            "QWENPAW_BROWSER_ORIGINS", ""
                        ).split(",")
                        if value.strip()
                    ),
                }
                if not origin or origin not in allowed:
                    raise HTTPException(403, "Cookie 写请求来源不被允许")
            if (
                is_model_adapter(path)
                and model_key
                and not local_token
                and not token
                and "X-Inoe-Token" not in request.headers
                and verify_model_service_key(model_key)
            ):
                request.state.access_identity = AccessIdentity(
                    user={}, inoe_token="", source="model_service"
                )
                await self.app(scope, receive, send)
                return
            cached = _use_cache(request.method, path)
            authorization = normalize_token(
                request.headers.get("Authorization", "")
            )
            if (
                authorization.startswith(LOCAL_TOKEN_PREFIX)
                and "X-QwenPaw-Access-Token" in request.headers
                and authorization != local_token
            ):
                raise HTTPException(401, "本地访问凭据冲突")
            if local_token:
                identity = get_access_store().resolve(local_token)
                if not cached:
                    user = await self.validator.validate(
                        identity.inoe_token,
                        sso_settings_store.get_userinfo_url(),
                        use_cache=False,
                    )
                    if user_subject(user) != user_subject(identity.user):
                        raise HTTPException(401, "登录身份已变化")
                if "X-Inoe-Token" in request.headers:
                    if token.startswith(LOCAL_TOKEN_PREFIX):
                        if token != local_token:
                            raise HTTPException(401, "本地访问凭据冲突")
                        token = ""
                if token and "X-Inoe-Token" in request.headers:
                    user = await self.validator.validate(
                        token,
                        sso_settings_store.get_userinfo_url(),
                        use_cache=cached,
                    )
                    if user_subject(user) != user_subject(identity.user):
                        raise HTTPException(401, "访问凭据身份冲突")
                    identity = AccessIdentity(
                        user=user,
                        inoe_token=token,
                        access_token=local_token,
                        source="mixed",
                    )
            else:
                user = await self.validator.validate(
                    token,
                    sso_settings_store.get_userinfo_url(),
                    use_cache=cached,
                )
                identity = AccessIdentity(user=user, inoe_token=token)
            authorize_request(identity, request.method, path)
        except HTTPException as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": (
                        "SSO_TOKEN_INVALID"
                        if exc.status_code == 401
                        else (
                            "ACCESS_DENIED"
                            if exc.status_code == 403
                            else "SSO_VALIDATION_UNAVAILABLE"
                        )
                    ),
                    "detail": exc.detail,
                    "stage": "request_authentication",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                },
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        except (OSError, sqlite3.Error, ValueError) as exc:
            logger.error(
                "Local access session unavailable: %s", type(exc).__name__
            )
            response = JSONResponse(
                status_code=503,
                content={
                    "code": "ACCESS_SESSION_UNAVAILABLE",
                    "detail": "本地认证会话服务不可用",
                },
            )
            await response(scope, receive, send)
            return

        request.state.sso_user = identity.user
        request.state.inoe_token = identity.inoe_token
        request.state.access_identity = identity
        ctx_identity = CURRENT_IDENTITY.set(identity)
        ctx_token = inoe_settings_store.CURRENT_REQUEST_TOKEN.set(
            identity.inoe_token
        )
        try:
            await self.app(scope, receive, send)
        finally:
            inoe_settings_store.CURRENT_REQUEST_TOKEN.reset(ctx_token)
            CURRENT_IDENTITY.reset(ctx_identity)
