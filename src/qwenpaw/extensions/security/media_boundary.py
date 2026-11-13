# -*- coding: utf-8 -*-
"""Validate attachment sources before permissive media-processing fallbacks."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from qwenpaw.constant import EnvVarLoader
from .execution_policy import check_path, enabled


def validate_sources(messages: list[Any]) -> None:
    if not enabled():
        return
    allowed = {
        value.strip()
        for value in EnvVarLoader.get_str(
            "QWENPAW_ALLOWED_MEDIA_HOSTS", ""
        ).split(",")
        if value.strip()
    }
    for message in messages:
        for block in getattr(message, "content", []) or []:
            source = (
                block.get("source")
                if isinstance(block, dict)
                else getattr(block, "source", None)
            )
            url = (
                source.get("url")
                if isinstance(source, dict)
                else getattr(source, "url", None)
            )
            if url is None or not url:
                continue
            url = str(url)
            target = urlsplit(url)
            if target.scheme == "file":
                if target.netloc not in {"", "localhost"}:
                    raise PermissionError("不允许远程文件系统附件")
                check_path(unquote(target.path))
            elif target.scheme in {"http", "https"}:
                if (
                    target.hostname not in allowed
                    or target.username is not None
                    or target.password is not None
                ):
                    raise PermissionError("远程附件来源未在生产白名单中")
            elif target.scheme not in {"", "data"}:
                raise PermissionError("不支持的附件来源协议")
            elif not target.scheme:
                check_path(url)
