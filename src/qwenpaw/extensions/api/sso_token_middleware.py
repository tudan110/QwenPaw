"""Temporary SSO token-presence gate; this does NOT validate tokens."""

from urllib.parse import unquote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from qwenpaw.constant import EnvVarLoader

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


def _has_sso_token(request: Request) -> bool:
    """Replace with trusted SSO validation when the contract is available."""
    header = request.headers.get("X-Inoe-Token", "").strip()
    if header.lower().startswith("bearer "):
        header = header[7:].strip()
    if header.lower() == "bearer":
        header = ""
    cookie = unquote(request.cookies.get(_TOKEN_COOKIE, "")).strip()
    return bool(header or cookie)


class SsoTokenMiddleware(BaseHTTPMiddleware):
    """Require a non-empty SSO token on business HTTP APIs by default."""

    async def dispatch(self, request: Request, call_next):
        enabled = EnvVarLoader.get_str("QWENPAW_SSO_TOKEN_REQUIRED", "true")
        if enabled.strip().lower() in {"false", "0", "no", "off"}:
            return await call_next(request)

        path = _canonical_path(request.url.path)
        if (
            request.method == "OPTIONS"
            or not (path == "/api" or path.startswith("/api/"))
            or (request.method, path) in _PUBLIC_ENDPOINTS
        ):
            return await call_next(request)

        if not _has_sso_token(request):
            return JSONResponse(
                status_code=401,
                content={
                    "code": "SSO_TOKEN_REQUIRED",
                    "detail": "缺少 SSO token，请先登录",
                },
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)
