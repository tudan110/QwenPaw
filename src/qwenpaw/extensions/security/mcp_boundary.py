# -*- coding: utf-8 -*-
"""Reject undeclared MCP endpoints before resolving or exposing credentials."""

from __future__ import annotations

import json
import shlex
from typing import Any
from urllib.parse import urlsplit

from qwenpaw.constant import EnvVarLoader
from .execution_policy import enabled


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
    target = urlsplit(str(endpoint.get("url") or ""))
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
