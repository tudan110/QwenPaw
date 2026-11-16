# -*- coding: utf-8 -*-
"""Reject undeclared MCP endpoints before resolving or exposing credentials."""

from __future__ import annotations

import json
import shlex
from typing import Any
from urllib.parse import urlsplit

from qwenpaw.constant import EnvVarLoader
from .execution_policy import enabled


def endpoint_key(url: str) -> tuple[str, str, int, str]:
    """Exact protocol/host/port/path; credentials and ambiguous URLs denied."""
    try:
        target = urlsplit(url)
        if (
            target.scheme not in {"http", "https"}
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
            or any(c in url for c in ("\\", "%"))
            or any(ord(c) <= 32 for c in url)
            or any(p in {".", ".."} for p in target.path.split("/"))
        ):
            raise ValueError("invalid endpoint")
        return (
            target.scheme,
            target.hostname.lower(),
            target.port or (443 if target.scheme == "https" else 80),
            target.path or "/",
        )
    except ValueError:
        raise PermissionError("MCP 服务端点格式不安全") from None


def validate_endpoint(endpoint: dict[str, Any]) -> None:
    if not enabled():
        return
    transport = str(endpoint.get("transport") or "stdio")
    if transport not in {"stdio", "sse", "streamable_http"}:
        raise PermissionError("不支持的生产 MCP 传输类型")
    if transport == "stdio":
        configured = json.loads(
            EnvVarLoader.get_str("QWENPAW_MCP_ALLOWED_COMMANDS", "[]")
        )
        command = [
            str(endpoint.get("command") or ""),
            *endpoint.get("args", []),
        ]
        if not isinstance(configured, list) or command not in [
            shlex.split(value)
            for value in configured
            if isinstance(value, str)
        ]:
            raise PermissionError("生产环境拒绝未声明的 MCP 子进程")
        return
    configured = json.loads(EnvVarLoader.get_str("QWENPAW_MCP_ALLOWED_URLS", "[]"))
    if not isinstance(configured, list) or not all(
        isinstance(u, str) for u in configured
    ):
        raise ValueError("MCP URL allowlist must be a JSON string array")
    allowed = {endpoint_key(url) for url in configured}
    if endpoint_key(str(endpoint.get("url") or "")) not in allowed:
        raise PermissionError("生产环境拒绝未批准的 MCP 服务端点")
