# -*- coding: utf-8 -*-
"""Atomic, narrowly scoped updates to JSON policy files."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable


class PolicyConflict(Exception):
    """A concurrent update or invalid policy makes the change unsafe."""


CONFIG_LOCK = "当前运行配置无法安全编辑，请由运维核对。"
STALE_POLICY = "策略或运行配置已变更，请刷新后核对。"


def read_object(path: Path) -> tuple[bytes | None, dict]:
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        return None, {}
    data = json.loads(original)
    if not isinstance(data, dict):
        raise PolicyConflict(CONFIG_LOCK)
    return original, data


def replace_object(path: Path, original: bytes | None, data: dict, recheck: Callable[[], None]) -> None:
    """Publish a complete config; never overwrite an unexpectedly created file."""
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".security-policy-", delete=False,
        ) as output:
            temporary = output.name
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if original is not None:
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            if path.read_bytes() != original:
                raise PolicyConflict(STALE_POLICY)
        recheck()
        if original is None:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise PolicyConflict(STALE_POLICY) from exc
        else:
            os.replace(temporary, path)
            temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
