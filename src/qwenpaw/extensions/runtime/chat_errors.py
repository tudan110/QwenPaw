# -*- coding: utf-8 -*-
"""Preserve safe Kunlun failure categories after core error normalization."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from qwenpaw.runtime.hooks import HookContext

logger = logging.getLogger(__name__)

_CHAT_PATH = "/api/portal/kunlun-adapter/v1/chat/completions"


def _failure_code(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        body = body.get("error", body)
    if isinstance(body, dict):
        text = " ".join(
            value
            for key in ("message", "msg", "detail")
            if isinstance(value := body.get(key), str)
        )
    else:
        text = body if isinstance(body, str) else ""
    text = (text or str(exc)).lower()
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)

    if re.search(r"\bmodel[ _]+not[ _]+authorized\b", text):
        return "KUNLUN_MODEL_UNAUTHORIZED"
    if "kunlun adapter is not configured" in text:
        return "KUNLUN_NOT_CONFIGURED"
    if status in (401, 403) or re.search(
        r"kunlun token endpoint returned (401|403)\b", text
    ):
        return "KUNLUN_AUTH_FAILED"
    if "jteop_gray" in text and "未匹配到有效的api" in text:
        return "KUNLUN_ROUTE_NOT_FOUND"
    if status == 404:
        return "KUNLUN_NOT_FOUND"
    if status == 429:
        return "KUNLUN_RATE_LIMITED"
    if status == 504 or re.search(r"\btimeout\b|\btimed out\b", text):
        return "KUNLUN_TIMEOUT"
    if re.search(
        r"failed to (?:connect to kunlun upstream|reach kunlun token endpoint)"
        r"|connection error|connecterror",
        text,
    ):
        return "KUNLUN_CONNECTION_FAILED"
    if status in (502, 503):
        return "KUNLUN_SERVICE_UNAVAILABLE"
    return None


def refine_kunlun_chat_error(ctx: HookContext) -> None:
    """Only expose a category, never an upstream body, URL or credential."""
    if getattr(ctx.request, "channel", None) != "console":
        return
    exc = ctx.error
    seen: set[int] = set()
    while isinstance(exc, Exception) and id(exc) not in seen:
        seen.add(id(exc))
        request = getattr(exc, "request", None)
        if request is None:
            request = getattr(getattr(exc, "response", None), "request", None)
        url = getattr(request, "url", None)
        if (
            url is not None
            and urlsplit(str(url)).path.rstrip("/") == _CHAT_PATH
        ):
            code = _failure_code(exc)
            if code:
                ctx.extras["_error_text"] = (
                    f"Kunlun model request failed ({code})"
                )
                logger.info("Classified Kunlun chat failure: %s", code)
            return
        exc = exc.__cause__ or exc.__context__
