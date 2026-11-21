# -*- coding: utf-8 -*-
"""Access boundary for QwenPaw's embedded llama.cpp runtime."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

from ..constant import DEFAULT_LOCAL_PROVIDER_DIR

_runtime: tuple[int, str] | None = None


def protect_storage() -> None:
    """Verify a private service-owned root before downloading/loading files."""
    if os.name != "posix":
        raise RuntimeError(
            "当前系统尚未验证本地模型目录 ACL，已阻止受管本地运行/下载"
        )
    root = DEFAULT_LOCAL_PROVIDER_DIR
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError(
            "受管本地模型目录必须为服务账户自有目录，且不能是链接"
        )
    root.chmod(0o700)
    if stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise RuntimeError("无法将受管目录限制为服务账户独占访问")
    for name in ("models", "tmp", "bin", "logs"):
        directory = root / name
        if directory.is_symlink():
            raise RuntimeError("受管本地模型子目录不得是符号链接")


def protect_model_file(path: Path) -> None:
    root = DEFAULT_LOCAL_PROVIDER_DIR.resolve()
    if os.name != "posix":
        raise RuntimeError("当前系统尚未验证本地模型文件 ACL")
    try:
        info = path.stat()
    except OSError as exc:
        raise RuntimeError("无法验证受管模型文件权限") from exc
    if (
        not path.is_relative_to(root / "models")
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise RuntimeError(
            "拒绝加载不属于受管目录的模型文件、非普通文件或硬链接"
        )
    try:
        path.chmod(0o400)
        if stat.S_IMODE(path.stat().st_mode) != 0o400:
            raise RuntimeError("无法将受管模型文件设为服务账户只读")
    except OSError as exc:
        raise RuntimeError("无法限制模型文件为服务账户只读") from exc


def protected_evidence_or_model_path(path: Path) -> bool:
    name = (
        path.name.lower()
        .removesuffix("-wal")
        .removesuffix("-shm")
        .removesuffix("-journal")
    )
    return name in {"component-governance.db", "call-admission.db"} or path.is_relative_to(
        DEFAULT_LOCAL_PROVIDER_DIR.resolve()
    )


def set_runtime(port: int, key: str) -> None:
    global _runtime
    _runtime = (port, key)


def clear_runtime(port: int | None) -> None:
    global _runtime
    if _runtime is not None and _runtime[0] == port:
        _runtime = None


def runtime_key(base_url: str) -> str:
    active = _runtime
    if (
        active is not None
        and base_url.rstrip("/") == f"http://127.0.0.1:{active[0]}/v1"
    ):
        return active[1]
    raise ValueError("受管本地接口未通过回环鉴权检查或尚未启动")


def runtime_authenticated(port: int | None) -> bool:
    return _runtime is not None and _runtime[0] == port


def is_loopback_endpoint(url: str) -> bool:
    try:
        return urlsplit(url).hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
            "::",
        }
    except ValueError:
        return False
