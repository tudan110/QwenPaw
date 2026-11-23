# -*- coding: utf-8 -*-
"""Allowlisted online configuration, backed by the actual policy readers."""
from __future__ import annotations

from typing import Literal

from ..constant import EnvVarLoader
from . import utils
from .config import Config
from .policy_file import CONFIG_LOCK, STALE_POLICY, PolicyConflict, read_object, replace_object
from .runtime_boundary_policy import (
    FLAG_ENV, RuntimeBoundaryPolicy, flag_enabled, invalidate_runtime_policy,
    load_runtime_policy, policy_path,
)

Key = Literal[
    "tool_guard", "skill_scan", "domain_guard", "output_masking",
    "chat_isolation", "text_guard", "controlled_documents", "controlled_workspace_files", "mcp_remote",
]
CONFIG_FIELDS = {
    "tool_guard": ("tool_guard", "enabled"),
    "skill_scan": ("skill_scanner", "mode"),
    "domain_guard": ("domain_guard", "mode"),
    "output_masking": ("output_guard", "mode"),
}
KEYS = (*CONFIG_FIELDS, *FLAG_ENV, "mcp_remote")
MODES = ("block", "warn", "off")
ENV = {
    "tool_guard": (("QWENPAW_TOOL_GUARD_ENABLED", None),),
    "skill_scan": (("QWENPAW_SKILL_SCAN_MODE", MODES),),
    "domain_guard": (("QWENPAW_DOMAIN_GUARD_MODE", MODES),),
    "output_masking": (
        ("QWENPAW_OUTPUT_GUARD_ENABLED", ("true", "1", "yes", "on", "false", "0", "no", "off")),
        ("QWENPAW_OUTPUT_GUARD_MODE", ("mask", "off")),
    ),
    "mcp_remote": (("QWENPAW_MCP_ALLOWED_ENDPOINTS", None),),
    **{key: ((name, None),) for key, name in FLAG_ENV.items()},
}


def _environment_lock(key: Key) -> str | None:
    for env, values in ENV[key]:
        raw = EnvVarLoader.get_str(env)
        if (values is None and (raw if key != "mcp_remote" else raw.strip())) or (
            values is not None and raw.strip().lower() in values
        ):
            return f"部署环境变量 {env} 覆盖此策略，页面只读。"
    return None


def _active_value(key: Key):
    if key == "tool_guard":
        from ..security.tool_guard.engine import get_guard_engine

        return get_guard_engine().enabled
    if key == "skill_scan":
        from ..security.skill_scanner import _get_scan_mode

        return _get_scan_mode()
    if key == "domain_guard":
        from ..extensions.api.domain_guard import load_config

        return load_config().mode
    if key == "output_masking":
        from ..extensions.security.output_guard import load_config

        return load_config().active
    if key == "mcp_remote":
        if _environment_lock(key):
            return None  # Do not disclose deployed endpoints in the editor.
        from ..extensions.security.mcp_boundary import _endpoint_key

        entries = load_runtime_policy().mcp_remote
        if entries is not None:
            for entry in entries:
                _endpoint_key(entry.transport, entry.url)
            return [entry.model_dump() for entry in entries]
        return None
    return flag_enabled(key)


def _read_config(path):
    original, data = read_object(path)
    return original, data, Config.model_validate(utils._normalize_working_dir_bound_paths(data))


def _stored_value(key: Key, model):
    if key == "output_masking":
        output = model.security.output_guard
        return output.enabled and output.mode == "mask"
    if key in CONFIG_FIELDS:
        section, field = CONFIG_FIELDS[key]
        return getattr(getattr(model.security, section), field)
    return model.model_dump()[key]


def _runtime_lock(key: Key, current) -> str | None:
    from ..extensions.security.execution_policy import enabled

    if key == "chat_isolation" and current is True:
        return "已启用主体隔离；关闭可能暴露历史会话，因此不允许在线关闭。"
    if key == "controlled_workspace_files" and not enabled():
        return "生产执行守卫未启用，当前实例沿用原生文件工具策略。"
    if key == "mcp_remote" and not enabled():
        return "生产执行守卫未启用，不能在线配置端点策略。"
    return None


def controls_snapshot() -> dict:
    try:
        config = _read_config(utils.get_config_path())[2]
    except (OSError, ValueError, PolicyConflict):
        config = None
    try:
        runtime = load_runtime_policy()
    except (OSError, ValueError, PolicyConflict):
        runtime = None
    results = {}
    for key in KEYS:
        model = config if key in CONFIG_FIELDS else runtime
        reason = _environment_lock(key)
        try:
            current = _active_value(key)
        except (OSError, ValueError, PolicyConflict):
            current = None
            reason = reason or CONFIG_LOCK
        reason = reason or (CONFIG_LOCK if model is None else None)
        if reason is None and _stored_value(key, model) != current:
            reason = STALE_POLICY
        results[key] = {
            "value": current, "locked_reason": reason or _runtime_lock(key, current),
        }
    return results


class InvalidChange(ValueError):
    """A deliberately user-facing validation message."""


def _validate_change(key: Key, value) -> None:
    from ..extensions.security.execution_policy import enabled
    from ..extensions.security.mcp_boundary import validate_online_endpoint

    if key in {"skill_scan", "domain_guard"}:
        if value not in MODES:
            raise InvalidChange("请选择有效的策略模式。")
    elif key == "mcp_remote":
        if not isinstance(value, list):
            raise InvalidChange("请选择精确端点列表；空列表表示拒绝全部远程端点。")
        try:
            keys = {validate_online_endpoint(entry["transport"], entry["url"]) for entry in value}
        except PermissionError as exc:
            raise InvalidChange(str(exc)) from exc
        if len(keys) != len(value):
            raise InvalidChange("名单中存在重复的 MCP 端点。")
    elif type(value) is not bool:
        raise InvalidChange("请选择开启或关闭。")
    if key == "chat_isolation" and value is not True:
        raise InvalidChange("不允许在线关闭会话主体隔离。")
    if key == "text_guard" and value is True and (not enabled() or not flag_enabled("chat_isolation")):
        raise PolicyConflict("开启文本检查前，须先开启会话主体隔离及生产执行守卫。")
    if key == "controlled_documents" and value is True and not enabled():
        raise PolicyConflict("开启受控资料前，须先开启生产执行守卫。")
    if key == "controlled_workspace_files" and value is True and not enabled():
        raise PolicyConflict("设置对话文件限制前，须先开启生产执行守卫。")


def configure(key: Key, value, expected) -> bool:
    """Check dependencies and the prior policy, then change only the selected fields."""
    def recheck() -> None:
        reason = _environment_lock(key) or _runtime_lock(key, expected)
        if reason:
            raise PolicyConflict(reason)

    # Dependency checks call live policy readers; do not hold the config cache lock.
    recheck()
    _validate_change(key, value)
    if _active_value(key) != expected:
        raise PolicyConflict(STALE_POLICY)
    with utils._config_lock:
        recheck()
        if key in CONFIG_FIELDS:
            path = utils.get_config_path().resolve()
            original, data, model = _read_config(path)
        else:
            path = policy_path().resolve()
            original, data = read_object(path)
            model = RuntimeBoundaryPolicy.model_validate(data)
        if _stored_value(key, model) != expected:
            raise PolicyConflict(STALE_POLICY)
        if value == expected:
            return False
        if key in CONFIG_FIELDS:
            section, field = CONFIG_FIELDS[key]
            target = data.setdefault("security", {}).setdefault(section, {})
            target[field] = value
            if key == "output_masking":
                target.update(enabled=value, mode="mask" if value else "off")
        else:
            _validate_change(key, value)  # Recheck dependencies of online flags and MCP.
            data[key] = value
        replace_object(path, original, data, recheck)
        if key in CONFIG_FIELDS:
            utils._config_cache = None
            utils._config_mtime = None
        else:
            invalidate_runtime_policy()
    return True


def confirmed(key: Key, wanted) -> bool:
    if _environment_lock(key) or _active_value(key) != wanted:
        return False
    _validate_change(key, wanted)
    if key == "mcp_remote":
        from ..extensions.security.execution_policy import enabled
        from ..extensions.security.mcp_boundary import declared_endpoints

        actual = declared_endpoints()
        return enabled() and actual is not None and len(actual) == len(wanted)
    return True
