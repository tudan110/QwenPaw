# -*- coding: utf-8 -*-
"""Narrow, audited-by-caller changes to the destructive-operation guard."""

from __future__ import annotations

from pathlib import Path

from . import utils
from .config import Config
from .policy_file import (
    CONFIG_LOCK, PolicyConflict, STALE_POLICY, read_object, replace_object,
)
from ..extensions.api.delete_block_middleware import delete_ops_env_override

DeleteProtectionConflict = PolicyConflict
ENVIRONMENT_LOCK = "部署环境变量 QWENPAW_DELETE_OPS_DISABLED 覆盖此策略，页面只读。"


def _read_policy_file(path: Path) -> tuple[bytes | None, dict, bool]:
    """Read without the normal loader's recovery or migration side effects."""
    original, data = read_object(path)
    security = data.get("security", {})
    if not isinstance(security, dict) or (
        "delete_ops_disabled" in security
        and type(security["delete_ops_disabled"]) is not bool
    ):
        raise DeleteProtectionConflict(CONFIG_LOCK)
    config = Config.model_validate(utils._normalize_working_dir_bound_paths(data))
    return original, data, config.security.delete_ops_disabled


def delete_protection_editing_lock(blocked: bool, source: str) -> str | None:
    """Explain why the current effective policy cannot be configured online."""
    if source == "environment":
        return ENVIRONMENT_LOCK
    if source != "config_or_default":
        return CONFIG_LOCK
    try:
        _, _, configured = _read_policy_file(utils.get_config_path())
    except (DeleteProtectionConflict, OSError, ValueError):
        return CONFIG_LOCK
    return None if configured == blocked else STALE_POLICY


def configure_delete_protection(*, blocked: bool, expected_blocked: bool) -> bool:
    """Persist only the delete guard setting, preserving unrelated keys."""
    def recheck() -> None:
        if delete_ops_env_override() is not None:
            raise DeleteProtectionConflict(ENVIRONMENT_LOCK)

    with utils._config_lock:
        recheck()
        path = utils.get_config_path().resolve()
        original, data, current = _read_policy_file(path)
        if current != expected_blocked:
            raise DeleteProtectionConflict(STALE_POLICY)
        if current == blocked:
            return False
        data.setdefault("security", {})["delete_ops_disabled"] = blocked
        replace_object(path, original, data, recheck)
        # Force re-read even if the filesystem mtime has coarse resolution.
        utils._config_cache = None
        utils._config_mtime = None
        return True
