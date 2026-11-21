# -*- coding: utf-8 -*-
"""Live policy for boundaries that previously only had deployment defaults."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from ..constant import EnvVarLoader
from . import utils
from .policy_file import PolicyConflict, read_object

Flag = Literal["chat_isolation", "text_guard", "controlled_documents"]
FLAG_ENV: dict[Flag, str] = {
    "chat_isolation": "QWENPAW_TRUSTED_CHAT_ISOLATION",
    "text_guard": "QWENPAW_TRUSTED_CHAT_TEXT_GUARD",
    "controlled_documents": "QWENPAW_CONTROLLED_DOCUMENTS",
}
TRUE = {"true", "1", "yes", "on"}


class RemoteEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: Literal["sse", "streamable_http"]
    url: StrictStr = Field(min_length=1, max_length=1024)


class RuntimeBoundaryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_isolation: StrictBool = False
    text_guard: StrictBool = False
    controlled_documents: StrictBool = False
    mcp_remote: list[RemoteEndpoint] | None = Field(default=None, max_length=64)


def policy_path() -> Path:
    return utils.get_config_path().with_name("boundary-policy.json")


@lru_cache(maxsize=4)
def _load_policy(path: Path, _stamp: tuple[int, int, int, int]) -> RuntimeBoundaryPolicy:
    return RuntimeBoundaryPolicy.model_validate(read_object(path)[1])


def load_runtime_policy() -> RuntimeBoundaryPolicy:
    path = policy_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        return RuntimeBoundaryPolicy()
    return _load_policy(path, (st.st_mtime_ns, st.st_ctime_ns, st.st_ino, st.st_size))


def invalidate_runtime_policy() -> None:
    _load_policy.cache_clear()


def flag_override(key: Flag) -> bool | None:
    raw = EnvVarLoader.get_str(FLAG_ENV[key])
    if not raw:
        return None
    return raw.strip().lower() in TRUE


def flag_enabled(key: Flag) -> bool:
    override = flag_override(key)
    if override is not None:
        return override
    try:
        return getattr(load_runtime_policy(), key)
    except (OSError, ValueError, PolicyConflict):
        # Never expose unisolated chat on file failure.
        return key != "controlled_documents"
