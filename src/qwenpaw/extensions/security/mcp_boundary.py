# -*- coding: utf-8 -*-
"""Reject undeclared MCP endpoints before resolving or exposing credentials."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any
from urllib.parse import urlsplit

from qwenpaw.constant import EnvVarLoader
from .execution_policy import enabled


_REMOTE_TRANSPORTS = {"sse", "streamable_http"}
_PATH = re.compile(r"/[a-zA-Z0-9._~/-]*\Z")


def _endpoint_key(transport: str, url: str, *, request: bool = False) -> tuple:
    if transport not in _REMOTE_TRANSPORTS or not isinstance(url, str):
        raise PermissionError("MCP 端点类型不受支持")
    if any(character.isspace() for character in url) or "\\" in url:
        raise PermissionError("MCP 端点格式无效")
    try:
        parts = urlsplit(url)
        path = parts.path or "/"
        port = parts.port
        if (
            parts.scheme not in {"https", "http"} or not parts.hostname
            or parts.hostname.endswith(".") or "%" in parts.hostname
            or parts.username is not None or parts.password is not None
            or port == 0 or "#" in url or ("?" in url and not request)
            or not _PATH.fullmatch(path) or "//" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            raise ValueError
    except ValueError as error:
        raise PermissionError("MCP 端点配置或请求路径无效") from error
    return transport, parts.scheme, parts.hostname, port or (443 if parts.scheme == "https" else 80), path


def declared_endpoints() -> set[tuple] | None:
    """An explicit empty list denies all remote endpoints when guards are on."""
    raw = EnvVarLoader.get_str("QWENPAW_MCP_ALLOWED_ENDPOINTS", "").strip()
    if not raw:
        return None
    try:
        entries = json.loads(raw)
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or set(entry) != {"transport", "url"}
            or not isinstance(entry["transport"], str) for entry in entries
        ):
            raise ValueError
        return {_endpoint_key(entry["transport"], entry["url"]) for entry in entries}
    except (ValueError, PermissionError) as error:
        raise PermissionError("MCP 精确白名单配置无效") from error


def validate_remote_request(transport: str, url: str) -> None:
    """Also check each HTTP request; same-origin changes can still be unsafe."""
    allowed = declared_endpoints()
    if allowed is not None and _endpoint_key(transport, url, request=True) not in allowed:
        raise PermissionError("生产环境拒绝访问未登记的 MCP 端点")


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
    url = str(endpoint.get("url") or "")
    allowed_endpoints = declared_endpoints()
    if allowed_endpoints is not None:
        if _endpoint_key(transport, url) not in allowed_endpoints:
            raise PermissionError("生产环境拒绝访问未登记的 MCP 端点")
        return
    target = urlsplit(url)
    allowed = {
        "localhost",
        "127.0.0.1",
        "::1",
        *(
            value.strip()
            for value in EnvVarLoader.get_str(
                "QWENPAW_MCP_ALLOWED_HOSTS", ""
            ).split(",")
            if value.strip()
        ),
    }
    if (
        target.scheme not in {"http", "https"}
        or target.username is not None
        or target.password is not None
        or not target.hostname
        or not (
            target.hostname in allowed
            or target.hostname.endswith(".svc.cluster.local")
            or target.hostname.endswith(".svc")
        )
    ):
        raise PermissionError("生产环境拒绝未批准的 MCP 服务端点")
