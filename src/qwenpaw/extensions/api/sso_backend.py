# -*- coding: utf-8 -*-
"""Portal-side OAuth2 single-sign-on with the INOE auth gateway (IdP).

The browser handoff works like this:

1. The user is logged into INOE and clicks the portal entry. INOE (which
   knows the logged-in user's phone number) mints a one-time authorization
   ``code`` and 302-redirects the browser to ``<portal>/sso/callback?code=…``.
2. The portal frontend hands that ``code`` to :func:`exchange` here.
3. This module signs a ``/token`` request (HMAC-SHA256 over the canonical
   param string, per the IdP contract), exchanges the ``code`` for the
   IdP's access token, then reads ``/userinfo`` with it.

The phone number never travels through the browser, and the ``client_secret``
never leaves the backend — it is only used to compute the signature. See
``docs/sso/OAuth2-单点登录对接文档.md`` for the wire contract and
``docs/sso/Oauth2SignDemo.java`` for the reference signing implementation.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Body, HTTPException, Request, Response

from qwenpaw.extensions.api import sso_settings_store
from qwenpaw.constant import EnvVarLoader
from .access_session import (
    ACCESS_COOKIE, LOCAL_TOKEN_PREFIX, get_access_store, user_subject,
)
from qwenpaw.extensions.api.sso_auth import (
    extract_user as _extract_user,
    parse_userinfo_response,
    validate_userinfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sso", tags=["sso"])

# The IdP enforces a ±60s window on the request timestamp, so the outbound
# call must be quick. Keep the timeout tight but tolerant of a slow gateway.
_HTTP_TIMEOUT_SECONDS = 15.0

# ``expires_in`` from the token endpoint is in MINUTES (a quirk of the IdP,
# documented in the contract), not the OAuth2-standard seconds.
_EXPIRES_IN_UNIT_SECONDS = 60

# The login token INOE drops in the browser after sign-in. In the "token
# pass-through" flow the user is already logged into INOE, so we reuse this
# token directly: the frontend forwards it (or, when portal shares INOE's
# hostname, the browser sends this cookie automatically) and we validate it
# against /userinfo. No phone number, no authorization code, no signing.
_INOE_LOGIN_COOKIE = "Cnos-Inoe-Admin-Token"

# INOE drops this alongside the token cookie at login — the same
# ``expires_in`` (minutes) its native /login response carries. Only trust it
# as an anchor at the moment we first see a given token (see setSession() on
# the frontend, which keeps the previously-computed deadline instead of
# re-deriving it on every revalidation) — INOE does not refresh this cookie
# as time passes, so re-reading it later and treating it as "N minutes from
# now" would keep pushing the deadline out indefinitely.
_INOE_EXPIRES_IN_COOKIE = "Cnos-Inoe-Admin-Expires-In"


def _clear_inoe_login_cookies(response: Response) -> None:
    response.delete_cookie(_INOE_LOGIN_COOKIE, path="/")
    response.delete_cookie(_INOE_EXPIRES_IN_COOKIE, path="/")


def _strip_bearer(token: str) -> str:
    token = str(token or "").strip()
    if token.lower().startswith("bearer "):
        return token[len("bearer ") :].strip()
    return token


def _cookie_token_from_header(raw_cookie: str | None, name: str) -> str:
    if not raw_cookie:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie)
    except Exception:  # noqa: BLE001 - malformed cookie header falls back empty
        return ""
    morsel = cookie.get(name)
    return _strip_bearer(morsel.value if morsel else "")


def _get_request_cookie(request: Request, name: str) -> str:
    token = _strip_bearer(request.cookies.get(name) or "")
    if token:
        return token
    return _cookie_token_from_header(request.headers.get("cookie"), name)


async def _validate_inoe_token(
    userinfo_url: str, token: str
) -> dict[str, Any]:
    """Validate one INOE login token against userinfo, surfacing auth errors."""
    try:
        user_body = await _get_json(userinfo_url, token, endpoint="userinfo")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="SSO 网关请求超时")
    except httpx.HTTPError as exc:
        logger.warning("SSO 网关连接失败: %s", exc)
        raise HTTPException(status_code=502, detail="SSO 网关连接失败")

    return validate_userinfo(user_body)


def _canonical(params: dict[str, str]) -> str:
    """Join non-empty params as ``key=value&key=value`` sorted by key asc.

    Matches ``Oauth2SignDemo.canonical``: a ``TreeMap`` iterated in key
    order, skipping null/empty values.
    """
    items = sorted(
        (k, v) for k, v in params.items() if v is not None and v != ""
    )
    return "&".join(f"{k}={v}" for k, v in items)


def _sign(params: dict[str, str], secret: str) -> str:
    """HMAC-SHA256 of the canonical string, returned as lowercase hex."""
    canonical = _canonical(params)
    digest = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return digest.hex()


def _now_ms() -> str:
    # Imported lazily so the module stays import-safe under the workflow
    # sandbox (which forbids argless time/date at import time elsewhere).
    import time

    return str(int(time.time() * 1000))


async def _exchange_code_for_token(
    *,
    base_url: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    """POST ``/token``: trade the one-time code for the IdP access token."""
    signed: dict[str, str] = {
        "clientId": client_id,
        "code": code,
        "timestamp": _now_ms(),
        "nonce": uuid.uuid4().hex,
    }
    # redirectUri only participates when configured; if present at /authorize
    # time it must match here and be part of the signature.
    if redirect_uri:
        signed["redirectUri"] = redirect_uri
    sign = _sign(signed, client_secret)

    payload = {
        "grantType": "authorization_code",
        **signed,
        "sign": sign,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.post(f"{base_url}/token", json=payload)
    return _parse_idp_response(resp, endpoint="token")


async def _get_json(
    url: str, token: str, *, endpoint: str
) -> dict[str, Any]:
    """GET ``url`` with a Bearer token, returning the parsed JSON body."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=headers)
    return _parse_idp_response(resp, endpoint=endpoint)


async def _fetch_userinfo(
    *, base_url: str, access_token: str
) -> dict[str, Any]:
    """GET ``/userinfo`` (authorization-code flow)."""
    return await _get_json(
        f"{base_url}/userinfo", access_token, endpoint="userinfo"
    )


def _parse_idp_response(
    resp: httpx.Response, *, endpoint: str
) -> dict[str, Any]:
    """Return the JSON body on success; raise HTTPException on IdP error.

    The IdP returns the RFC-6749 error body ``{error, error_description}``
    on failure. We surface ``error_description`` (never the secret) and keep
    the upstream status code so the frontend can tell the user what to do.
    """
    if endpoint == "userinfo":
        return parse_userinfo_response(resp)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.is_success:
        if not isinstance(body, dict):
            raise HTTPException(
                status_code=502,
                detail=f"SSO {endpoint} 返回了非预期的响应",
            )
        return body
    detail = ""
    if isinstance(body, dict):
        detail = str(
            body.get("error_description") or body.get("error") or ""
        ).strip()
    detail = detail or f"SSO {endpoint} 调用失败 (HTTP {resp.status_code})"
    # Map upstream 5xx to 502 (bad gateway) but keep client errors as-is.
    status = resp.status_code if resp.status_code < 500 else 502
    raise HTTPException(status_code=status, detail=detail)


@router.get("/status")
async def sso_status() -> dict[str, Any]:
    """Whether the backend is ready to log a user in. No secrets exposed.

    ``configured`` is the token-passthrough readiness — it only needs the
    gateway base URL (to call /userinfo). ``authorization_code_ready`` adds
    the client credentials required by the (currently unused) code flow.
    """
    return {
        "configured": sso_settings_store.is_token_login_ready(),
        "authorization_code_ready": sso_settings_store.is_configured(),
        "sso_required": EnvVarLoader.get_str(
            "QWENPAW_SSO_TOKEN_REQUIRED", "true"
        ).strip().lower() not in {"false", "0", "no", "off"},
        "login_url": EnvVarLoader.get_str("QWENPAW_INOE_LOGIN_URL", ""),
    }


@router.post("/token-login")
async def token_login(
    request: Request,
    response: Response,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Log in by validating an existing INOE login token (token pass-through).

    The token is taken from the request body (``{"token": "..."}``) or, when
    portal shares INOE's hostname, from the ``Cnos-Inoe-Admin-Token`` cookie
    the browser sends automatically. We validate it against ``/userinfo`` —
    a success both proves the token is genuine and yields the user. Returns
    the same shape as :func:`exchange` so the frontend treats both uniformly.
    """
    body_token = _strip_bearer(body.get("token") or "")
    cookie_token = _get_request_cookie(request, _INOE_LOGIN_COOKIE)
    if not cookie_token:
        cookie_token = _strip_bearer(unquote(
            request.cookies.get("qwenpaw_sso_token", "")
            or request.cookies.get(ACCESS_COOKIE, "")
        ))
        if not body_token and cookie_token.startswith(LOCAL_TOKEN_PREFIX):
            body_token, cookie_token = cookie_token, ""
    if body_token.startswith(LOCAL_TOKEN_PREFIX):
        identity = get_access_store().resolve(body_token)
        user_body = await _validate_inoe_token(
            sso_settings_store.get_userinfo_url(), identity.inoe_token
        )
        user = _extract_user(user_body)
        if user_subject(user) != user_subject(identity.user):
            raise HTTPException(401, "登录身份已变化")
        result = get_access_store().issue(
            identity.inoe_token, user, family_id=identity.family_id
        )
        response.set_cookie(
            ACCESS_COOKIE, result["access_token"], httponly=True,
            secure=request.url.scheme == "https", samesite="strict",
            max_age=result["expires_in_seconds"], path="/",
        )
        return result
    if not (body_token or cookie_token):
        raise HTTPException(status_code=401, detail="缺少 INOE 登录凭证")

    userinfo_url = sso_settings_store.get_userinfo_url()
    if not userinfo_url:
        raise HTTPException(
            status_code=400, detail="SSO 未配置(平台 INOE 网关地址缺失)"
        )

    candidates = [body_token]
    if cookie_token and cookie_token != body_token:
        candidates.append(cookie_token)
    candidates = [token for token in candidates if token]

    user_body = None
    token = ""
    last_401: HTTPException | None = None
    for token in candidates:
        try:
            user_body = await _validate_inoe_token(userinfo_url, token)
            break
        except HTTPException as exc:
            if exc.status_code == 401:
                last_401 = exc
                continue
            raise
    if user_body is None:
        raise last_401 or HTTPException(
            status_code=401, detail="INOE 登录态校验失败"
        )

    user = _extract_user(user_body)
    if "userId" not in user and not user.get("username"):
        raise HTTPException(
            status_code=401, detail="未能从 INOE 获取用户信息,token 可能已失效"
        )
    try:
        expires_in_minutes = float(
            _get_request_cookie(request, _INOE_EXPIRES_IN_COOKIE) or 0
        )
    except (TypeError, ValueError):
        expires_in_minutes = 0.0
    result = get_access_store().issue(token, user)
    response.set_cookie(
        ACCESS_COOKIE, result["access_token"], httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
        max_age=result["expires_in_seconds"], path="/",
    )
    return result


@router.post("/clear-login-cookie")
async def clear_login_cookie(request: Request, response: Response) -> dict[str, Any]:
    """Clear stale INOE login cookies so portal can force a clean re-login."""
    _clear_inoe_login_cookies(response)
    token = request.cookies.get(ACCESS_COOKIE, "")
    if token:
        get_access_store().revoke(token)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    return {"cleared": True}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    identity = getattr(request.state, "access_identity", None)
    if identity is None or not identity.access_token:
        raise HTTPException(401, "没有可撤销的本地登录会话")
    get_access_store().revoke(identity.access_token)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    _clear_inoe_login_cookies(response)
    return {"logged_out": True}


@router.get("/session")
async def session_status(request: Request) -> dict[str, Any]:
    identity = getattr(request.state, "access_identity", None)
    if identity is None:
        raise HTTPException(401, "没有可信登录身份")
    return {
        "user": identity.user,
        "token_kind": identity.source,
        "access_token": identity.access_token,
    }


@router.post("/exchange")
async def exchange(
    request: Request,
    response: Response,
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Exchange an authorization ``code`` for portal login material.

    Body: ``{"code": "...", "state": "..."}``. Returns
    ``{access_token, token_type, expires_in_seconds, user}``. The frontend
    stores this as its login state.
    """
    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少授权码 code")

    base_url = sso_settings_store.get_gateway_base_url()
    client_id = sso_settings_store.get_client_id()
    client_secret = sso_settings_store.get_client_secret()
    redirect_uri = sso_settings_store.get_redirect_uri()
    if not (base_url and client_id and client_secret):
        raise HTTPException(
            status_code=400,
            detail="SSO 未配置(网关地址 / client_id / client_secret 缺失)",
        )

    try:
        token_body = await _exchange_code_for_token(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
        access_token = str(token_body.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(
                status_code=502, detail="SSO token 响应缺少 access_token"
            )
        user_body = await _fetch_userinfo(
            base_url=base_url, access_token=access_token
        )
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="SSO 网关请求超时")
    except httpx.HTTPError as exc:
        logger.warning("SSO 网关连接失败: %s", exc)
        raise HTTPException(status_code=502, detail="SSO 网关连接失败")

    try:
        expires_in_minutes = float(token_body.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in_minutes = 0.0
    expires_in_seconds = int(expires_in_minutes * _EXPIRES_IN_UNIT_SECONDS)
    result = get_access_store().issue(access_token, _extract_user(user_body))
    response.set_cookie(
        ACCESS_COOKIE, result["access_token"], httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
        max_age=result["expires_in_seconds"], path="/",
    )
    return result


# ---------------------------------------------------------------------------
# Settings API: /sso/sso-settings GET/PUT + reset (mirrors inoe-settings)
# ---------------------------------------------------------------------------


@router.get("/sso-settings")
async def get_sso_settings() -> dict[str, Any]:
    """Return SSO credentials as ``{effective, env, overrides}``.

    The client secret is masked in both layers.
    """
    return sso_settings_store.build_settings_payload()


@router.put("/sso-settings")
async def put_sso_settings(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Persist a partial update of the SSO credentials.

    Page values win over env. The secret left empty keeps the stored value;
    sending ``sso_settings_store.CLEAR_SENTINEL`` clears it.
    """
    try:
        sso_settings_store.apply_settings_update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return sso_settings_store.build_settings_payload()


@router.post("/sso-settings/reset")
async def reset_sso_setting(
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    """Drop one SSO field's override so it falls back to env/default.

    Body: ``{"key": "<field>"}``.
    """
    key = str(body.get("key") or "").strip()
    try:
        sso_settings_store.reset_setting(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return sso_settings_store.build_settings_payload()
