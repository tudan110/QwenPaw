# -*- coding: utf-8 -*-
"""Trusted INOE userinfo validation and bounded process-local caching."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 15.0
DEFAULT_CACHE_MAX_ENTRIES = 1024
_HTTP_TIMEOUT_SECONDS = 5.0


def normalize_token(token: str) -> str:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return "" if token.lower() == "bearer" else token


def extract_user(body: dict[str, Any]) -> dict[str, Any]:
    """Only retain scalar public identity fields from either INOE shape."""
    nested_user = body.get("user")
    src = nested_user if isinstance(nested_user, dict) else body
    fields = {
        "userId": ("userId", "user_id"),
        "username": ("username", "userName"),
        "nickName": ("nickName", "nick_name"),
        "phonenumber": ("phonenumber", "phone"),
        "deptId": ("deptId", "dept_id"),
        "email": ("email",),
    }
    user: dict[str, Any] = {}
    for field, aliases in fields.items():
        for alias in aliases:
            value = src.get(alias)
            if (
                isinstance(value, (str, int))
                and not isinstance(value, bool)
                and str(value).strip()
            ):
                user[field] = value
                break
    return user


def validate_userinfo(body: dict[str, Any]) -> dict[str, Any]:
    """Require a successful INOE response with a usable identity."""
    code = body.get("code")
    if code is not None and str(code) != "200":
        if str(code) in {"401", "403"}:
            raise HTTPException(401, "INOE 登录态无效或已过期")
        raise HTTPException(502, "SSO 用户信息服务返回异常状态")
    error = body.get("error")
    if error:
        if error in ("invalid_token", "invalid_grant", "access_denied"):
            raise HTTPException(401, "INOE 登录态无效或已过期")
        raise HTTPException(502, "SSO 用户信息服务返回异常状态")
    user = extract_user(body)
    if "userId" not in user and not user.get("username"):
        raise HTTPException(502, "SSO 用户信息响应缺少有效身份")
    return body


def parse_userinfo_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code in {401, 403}:
        raise HTTPException(401, "INOE 登录态无效或已过期")
    if not response.is_success:
        raise HTTPException(502, "SSO 用户信息服务调用失败")
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(502, "SSO 用户信息响应不是有效 JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(502, "SSO 用户信息响应格式异常")
    return validate_userinfo(body)


def _cache_lifetime(token: str, ttl: float) -> float:
    # An optional JWT exp only shortens caching AFTER online validation.
    # Decoding it never establishes identity or substitutes for validation.
    parts = token.split(".")
    if len(parts) != 3:
        return ttl
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        body = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return 0.0
    if not isinstance(body, dict):
        return 0.0
    expires = body.get("exp")
    if expires is None:
        return ttl
    if not isinstance(expires, (int, float)) or isinstance(expires, bool):
        return 0.0
    try:
        remaining = float(expires) - time.time()
    except OverflowError:
        return 0.0
    if not math.isfinite(remaining):
        return 0.0
    return max(0.0, min(ttl, remaining))


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    user: dict[str, Any]


class InoeTokenValidator:
    """One validator per app process; no credentials in cache keys/values."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not math.isfinite(ttl_seconds) or ttl_seconds < 0:
            raise ValueError("Cache TTL must be finite and nonnegative")
        if max_entries < 1:
            raise ValueError("Cache capacity must be positive")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._client = client
        self._cache: OrderedDict[tuple[str, str], _CacheEntry] = OrderedDict()
        self._inflight: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = (
            {}
        )

    async def validate(
        self, token: str, userinfo_url: str, *, use_cache: bool = True
    ) -> dict[str, Any]:
        token = normalize_token(token)
        if not token:
            raise HTTPException(401, "缺少 SSO token，请先登录")
        if len(token) > 16384 or any(
            ord(char) <= 32 or ord(char) >= 127 for char in token
        ):
            raise HTTPException(401, "SSO token 格式无效")
        if not userinfo_url:
            raise HTTPException(503, "SSO 用户信息服务未配置")
        key = (userinfo_url, hashlib.sha256(token.encode()).hexdigest())
        if not use_cache:
            self._cache.pop(key, None)
        entry = self._cache.get(key)
        if entry is not None:
            if entry.expires_at > self._clock():
                self._cache.move_to_end(key)
                return entry.user.copy()
            self._cache.pop(key)

        task = self._inflight.get(key)
        if task is None:
            if len(self._inflight) >= self._max_entries:
                logger.warning("SSO validation concurrency limit reached")
                raise HTTPException(503, "SSO 校验繁忙，请稍后重试")
            task = asyncio.create_task(
                self._validate_and_cache(key, token, userinfo_url)
            )
            self._inflight[key] = task
            # A disconnected caller must not cancel other waiters or leave
            # an unobserved exception when no waiters remain.
            task.add_done_callback(self._observe_completion)
        return (await asyncio.shield(task)).copy()

    @staticmethod
    def _observe_completion(task: asyncio.Task[dict[str, Any]]) -> None:
        if not task.cancelled():
            task.exception()

    async def _validate_and_cache(
        self, key: tuple[str, str], token: str, userinfo_url: str
    ) -> dict[str, Any]:
        started_at = self._clock()
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    timeout=_HTTP_TIMEOUT_SECONDS,
                    limits=httpx.Limits(
                        max_connections=20, max_keepalive_connections=20
                    ),
                    follow_redirects=False,
                    trust_env=False,
                )
            try:
                async with asyncio.timeout(_HTTP_TIMEOUT_SECONDS):
                    request = self._client.build_request(
                        "GET",
                        userinfo_url,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    request.headers.pop("Cookie", None)
                    try:
                        response = await self._client.send(request)
                    finally:
                        self._client.cookies.clear()
            except (httpx.TimeoutException, TimeoutError) as exc:
                logger.warning("SSO online validation timed out")
                raise HTTPException(504, "SSO 网关请求超时") from exc
            except httpx.HTTPError as exc:
                logger.warning("SSO online validation connection failed")
                raise HTTPException(502, "SSO 网关连接失败") from exc

            user = extract_user(parse_userinfo_response(response))
            now = self._clock()
            remaining_ttl = max(0.0, self._ttl - max(0.0, now - started_at))
            lifetime = _cache_lifetime(token, remaining_ttl)
            for old_key, entry in list(self._cache.items()):
                if entry.expires_at <= now:
                    self._cache.pop(old_key)
            if lifetime > 0:
                self._cache[key] = _CacheEntry(now + lifetime, user.copy())
                self._cache.move_to_end(key)
                while len(self._cache) > self._max_entries:
                    self._cache.popitem(last=False)
            return user
        except HTTPException as exc:
            self._cache.pop(key, None)
            logger.info(
                "SSO online validation rejected: status=%s",
                exc.status_code,
            )
            raise
        finally:
            self._inflight.pop(key, None)

    async def aclose(self) -> None:
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._inflight.clear()
        self._cache.clear()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
