# -*- coding: utf-8 -*-
"""Production execution restrictions that approval_level cannot override."""

from __future__ import annotations

import hashlib
import json
import shlex
import sys
import unicodedata
from urllib.parse import unquote
from pathlib import Path
from typing import Any, NoReturn

from qwenpaw.constant import BACKUP_DIR, EnvVarLoader, SECRET_DIR, WORKING_DIR
from qwenpaw.config.context import get_current_workspace_dir
from qwenpaw.extensions.api.access_session import (
    CURRENT_IDENTITY,
    get_access_store,
    user_subject,
)
from qwenpaw.extensions.api import sso_settings_store
from qwenpaw.extensions.api.chat_isolation import chat_isolation_enabled
from qwenpaw.extensions.api.sso_backend import _validate_inoe_token
from qwenpaw.extensions.api.sso_auth import extract_user
from .business_reads import MCP_READ_TOOLS
from .managed_integrity import inspect_skill
from .skill_cli import check_cli_arguments
from .skill_scripts import (
    SCRIPT_SKILLS,
    approval_files,
    check_arguments,
    check_web_identifiers,
)

_READ_TOOLS = {
    "lookup_portal_cmdb_asset",
    "read_file",
    "list_agents",
    "chat_with_agent",
    "submit_to_agent",
    "check_agent_task",
    "get_current_time",
    "get_token_usage",
    "send_file_to_user",
    "view_image",
    "spawn_subagent",
}
_READ_SCRIPT_NAMES = {
    "query_knowledge.py",
    "get_alarms.py",
    "analyze_alarms.py",
    "analyze_alarm_context.py",
    "get_metric_definitions.py",
    "inspect_resource_metrics.py",
    "find_project.py",
    "n9e_log_query.py",
    "n9e_log_aggregate.py",
    "n9e_log_meta.py",
    "n9e_log_hazard.py",
    "n9e_log_cluster.py",
    "n9e_log_drift.py",
    "n9e_log_secscan.py",
    "n9e_log_secrules.py",
    "get_devices.py",
    "analyze_devices.py",
    "monitoring_overview.py",
    "resource_insight.py",
    "cmdb_read.py",
    "app_topology.py",
    "analyze_cmdb.py",
    "inoe_cmdb_stats.py",
    "order_workflow.py",
}

# Bounded artifact creation: text input only, fixed renderer and report root.
# This does not grant general filesystem writes or shell execution.
_ARTIFACT_TOOLS = {
    "export_report",
    "process_office_document",
    "write_skill_context",
}


def enabled() -> bool:
    return EnvVarLoader.get_str(
        "QWENPAW_PRODUCTION_GUARDS", "true"
    ).lower() not in {
        "false",
        "0",
        "off",
        "no",
    }


def check_path(path_value: str) -> None:
    if not enabled():
        return
    value = path_value
    for _ in range(8):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    else:
        raise PermissionError("不允许多重编码的文件路径")
    candidate = Path(unicodedata.normalize("NFC", value)).expanduser()
    path = (
        Path(get_current_workspace_dir() or WORKING_DIR) / candidate
    ).resolve()
    if chat_isolation_enabled() and (
        any(part.casefold() in {"sessions", "chat_traces"} for part in path.parts)
        or path.name.casefold().startswith("chats.json")
    ):
        raise PermissionError("会话数据只能通过已授权的会话接口访问")
    secret = Path(SECRET_DIR).resolve()
    if path == secret or secret in path.parents:
        raise PermissionError("禁止工具读取或修改秘密目录")
    backup = Path(BACKUP_DIR).resolve()
    if path == backup or backup in path.parents:
        raise PermissionError("禁止工具访问备份及签名密钥目录")
    if path.name in {
        ".master_key",
        ".signing_key",
        ".netrc",
        ".git-credentials",
    }:
        raise PermissionError("禁止工具访问签名或主密钥文件")
    database_name = path.name
    for suffix in ("-wal", "-shm", "-journal"):
        database_name = database_name.removesuffix(suffix)
    if database_name in {
        "settings.db",
        "sso_access_sessions.db",
        "auth.json",
        "providers.json",
        "envs.json",
    }:
        raise PermissionError("秘密配置只能通过授权管理接口访问")
    if (
        path.name == "agent.json"
        or path == Path(WORKING_DIR).resolve() / "config.json"
    ):
        raise PermissionError("完整运行配置只能通过授权管理接口访问")
    if path.name == ".env" or path.suffix in {".pem", ".key", ".env"}:
        raise PermissionError("禁止工具访问凭据文件")
    if database_name in {
        "audit.db",
        "audit.log",
        "audit.sqlite",
        "governance_audit.db",
    }:
        raise PermissionError("禁止工具直接访问审计存储")
    if path.parts[:2] in {("/", "proc"), ("/", "sys"), ("/", "dev")}:
        raise PermissionError("禁止工具访问进程、系统或设备文件")
    if any(
        part
        in {
            ".ssh",
            ".aws",
            ".kube",
            ".gnupg",
            ".docker",
            "backups",
            ".qwenpaw-managed-sync",
        }
        for part in path.parts
    ) or path.name in {".netrc", ".git-credentials"}:
        raise PermissionError("禁止工具访问系统凭据或备份目录")


def _deny_script(code: str, path: Path) -> NoReturn:
    raise PermissionError(
        f"SKILL_INTEGRITY_BLOCKED: {code}; file={path.name}; "
        "技能完整性校验失败。停止本轮该技能的执行尝试，"
        "请运维检查受管种子；改命令或更换身份不能修复。"
    )


def check_search_path(path_value: str) -> None:
    """Confine recursive searches to non-sensitive workspace entries."""
    if not enabled():
        return
    configured = Path(get_current_workspace_dir() or WORKING_DIR).absolute()
    workspace = configured.resolve()
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    elif candidate.is_relative_to(configured):
        # Normalize aliases above the trusted workspace (e.g. macOS /var),
        # while retaining links inside it for the explicit check below.
        candidate = workspace / candidate.relative_to(configured)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise PermissionError("搜索只能访问当前工作区")
    if resolved.name.startswith(".env."):
        raise PermissionError("搜索不能访问环境凭据文件")
    # Do not follow even an in-workspace link: its target may change between
    # discovery and reading, and glob can explicitly traverse linked folders.
    for entry in (candidate, *candidate.parents):
        if entry == workspace:
            break
        if entry.is_symlink():
            raise PermissionError("搜索不能访问符号链接")
    check_path(str(candidate))


def check_search(name: str, params: dict[str, Any]) -> None:
    if not enabled():
        return
    check_search_path(params.get("path") or ".")
    if name == "glob_search":
        pattern = Path(params.get("pattern") or "")
        if pattern.is_absolute() or ".." in pattern.parts:
            raise PermissionError("搜索模式不能越过当前目录")


def _approved_script(path: Path) -> bool:
    check_path(str(path))
    if not path.is_file():
        _deny_script("SCRIPT_MISSING", path)
    if path.suffix != ".py":
        _deny_script("SCRIPT_NOT_ALLOWED", path)
    hashes = json.loads(
        EnvVarLoader.get_str("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}")
    )
    if not isinstance(hashes, dict):
        raise ValueError("Script hash allowlist must be a JSON object")
    expected = hashes.get(str(path))
    if expected is None:
        seed = Path(
            EnvVarLoader.get_str(
                "QWENPAW_SKILL_SEED_PATH", "/app/share/qwenpaw-seed"
            )
        )
        manifest_path = seed / "seed-manifest.json"
        if not manifest_path.is_file():
            _deny_script("SEED_MANIFEST_MISSING", path)
        if path.name not in _READ_SCRIPT_NAMES | SCRIPT_SKILLS.keys():
            _deny_script("SCRIPT_NOT_ALLOWED", path)
        try:
            relative = str(path.relative_to(Path(WORKING_DIR).resolve()))
        except ValueError:
            _deny_script("SCRIPT_OUTSIDE_WORKING_DIR", path)
        manifest = json.loads(manifest_path.read_text())
        expected = (
            manifest.get("managed_files", {}).get(relative, {}).get("sha256")
        )
        if expected is None:
            _deny_script("SCRIPT_NOT_DECLARED", path)
        parts = Path(relative).parts
        if "skills" not in parts:
            return False
        skill_index = parts.index("skills")
        skill_relative = Path(*parts[: skill_index + 2])
        inspection = inspect_skill(
            Path(WORKING_DIR), manifest, str(skill_relative)
        )
        if not inspection["execution_ready"]:
            reasons = sorted({item["code"] for item in inspection["blockers"]})
            raise PermissionError(
                f"SKILL_INTEGRITY_BLOCKED: {', '.join(reasons)}; "
                f"skill={skill_relative}; "
                "技能完整性校验失败。停止本轮该技能的执行尝试；"
                "改命令、管道或更换身份不能修复，请运维预览隔离清单。"
            )
        if path.name == "kb_search.py":
            dependency = inspect_skill(
                Path(WORKING_DIR),
                manifest,
                "workspaces/knowledge/skills/knowledge-base",
            )
            if not dependency["execution_ready"]:
                _deny_script("KNOWLEDGE_DEPENDENCY_NOT_TRUSTED", path)
    if path.name == "inspect_resource_metrics.py":
        if len(path.parents) < 5:
            return False
        # This entry imports helpers from two other managed skills. Their
        # dependency trees must be checked too, not just the top-level file.
        metric_helpers = (
            path.parents[4]
            / "fault/skills/alarm-analyst/scripts/get_metric_definitions.py"
        )
        cmdb_helpers = path.parents[2] / "zgops-cmdb/scripts/cmdb_read.py"
        if not _approved_script(metric_helpers) or not _approved_script(
            cmdb_helpers
        ):
            return False
    if (
        not isinstance(expected, str)
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected
    ):
        _deny_script("SCRIPT_HASH_MISMATCH", path)
    return True


def check_shell(command: str, cwd: Any = None) -> bool:
    """Return True for actions requiring administrator approval."""
    if sys.platform == "win32" and any(char in command for char in ";|&<>%^!"):
        raise PermissionError("Windows 生产命令不允许 shell 元字符")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    if any(char in command for char in ("`", "$", "\n", "\r")) or any(
        token and all(char in ";|&<>()" for char in token) for token in lexer
    ):
        raise PermissionError("生产环境禁止 shell 拼接、管道、重定向或展开")
    args = shlex.split(command)
    if not args:
        raise PermissionError("空命令不可执行")
    forbidden_flags = {
        "--api_base_url",
        "--api-base-url",
        "--base_url",
        "--base-url",
        "--url",
        "--endpoint",
        "--host",
        "--proxy",
        "--n9e-url",
        "--config",
        "--config-file",
        "--env-file",
        "--token",
        "--execute",
        "--apply",
        "--delete",
        "--remove",
        "--kill",
    }
    for value in args[1:]:
        flag = value.split("=", 1)[0]
        if flag.startswith("-") and not flag.startswith("--") and flag != "-h":
            raise PermissionError("生产脚本仅允许明确的长参数")
        if (
            flag.startswith("--")
            and flag != "--"
            and any(blocked.startswith(flag) for blocked in forbidden_flags)
        ):
            raise PermissionError("禁止连接/高危参数及其缩写")
    if Path(args[0]).name in {"qwenpaw", "copaw"}:
        executable = Path(args[0])
        if args[0] != executable.name and (
            not executable.is_absolute()
            or executable.resolve()
            != (Path(sys.executable).parent / executable.name).resolve()
        ):
            raise PermissionError("协同 CLI 必须来自当前受信任的安装目录")
        if args[1:3] in (["agents", "list"], ["agents", "chat"]):
            return False
        workspace = Path(get_current_workspace_dir() or WORKING_DIR).resolve()
        directory = Path(cwd or workspace).resolve()
        try:
            return check_cli_arguments(
                args[1:], directory, workspace, check_path
            )
        except OSError as exc:
            raise PermissionError("技能 CLI 输入文件不存在或无法访问") from exc
    if len(args) < 2 or Path(args[0]).name not in {
        "python",
        "python3",
        "python3.11",
        "python3.12",
        "python3.13",
    }:
        raise PermissionError("生产环境仅允许经哈希校验的固定 Python 脚本")
    if args[0] != Path(args[0]).name and (
        not Path(args[0]).is_absolute()
        or Path(args[0]).resolve() != Path(sys.executable).resolve()
    ):
        raise PermissionError("脚本必须使用当前受信任的 Python 解释器")
    directory = Path(
        cwd or get_current_workspace_dir() or WORKING_DIR
    ).resolve()
    path = (directory / args[1]).resolve()
    if not _approved_script(path):
        raise PermissionError("脚本未在生产白名单中或完整性校验失败")
    if path.name in SCRIPT_SKILLS:
        workspace = Path(get_current_workspace_dir() or WORKING_DIR).resolve()
        # Structured contracts reject abbreviations/unknown flags rather
        # than inheriting argparse's permissive prefix matching.
        try:
            return check_arguments(
                path,
                args[2:],
                directory,
                workspace,
                check_path,
            )
        except PermissionError:
            raise
        except OSError as exc:
            raise PermissionError("技能输入文件不存在或无法访问") from exc
    if (
        path.name == "inspect_resource_metrics.py"
        and "--no-notify" not in args[2:]
    ):
        raise PermissionError("普通巡检查询必须显式禁用通知推送")
    if path.name == "order_workflow.py" and (
        len(args) < 3
        or args[2] not in {"stats", "todo-list", "finished-list", "detail"}
    ):
        raise PermissionError("工单脚本仅允许明确的只读子命令")
    if path.name == "cmdb_read.py" and (
        len(args) < 3
        or args[2]
        not in {
            "fetch",
            "list-models",
            "model-attributes",
            "model-relations",
            "find-project",
            "app-topology",
            "analyze",
            "inoe-stat",
        }
    ):
        raise PermissionError("CMDB 脚本仅允许明确的只读子命令")
    for index, value in enumerate(args[2:], start=2):
        if value.split("=", 1)[0] in {
            "--rules-file",
            "--file",
            "--input-file",
        }:
            file_value = (
                value.split("=", 1)[1]
                if "=" in value
                else (args[index + 1] if index + 1 < len(args) else "")
            )
            check_path(str(directory / file_value))
    return False


def approval_binding(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Freeze indirect JSON inputs along with the displayed command."""
    from copy import deepcopy

    binding = {"params": deepcopy(params)}
    if name == "execute_shell_command":
        directory = Path(
            params.get("cwd") or get_current_workspace_dir() or WORKING_DIR
        ).resolve()
        binding["files"] = approval_files(
            str(params.get("command", "")),
            directory,
        )
    return binding


async def check_tool(name: str, params: dict[str, Any]) -> bool:
    """Return whether this call needs mandatory administrator approval."""
    if not enabled():
        return False
    if name in {"grep_search", "glob_search"}:
        check_search(name, params)
        return False
    if name.startswith("web-check-app__"):
        check_web_identifiers(params)
    for key in ("file_path", "path", "filename"):
        value = params.get(key)
        if not isinstance(value, str):
            continue
        check_path(value)
    shell_write = False
    if name == "execute_shell_command":
        shell_write = check_shell(
            str(params.get("command", "")), params.get("cwd")
        )
        if not shell_write:
            return False
    configured_reads = {
        value.strip()
        for value in EnvVarLoader.get_str(
            "QWENPAW_READONLY_TOOL_NAMES", ""
        ).split(",")
        if value.strip()
    }
    mutating = any(
        word in name.lower()
        for word in (
            "delete",
            "remove",
            "insert",
            "update",
            "create",
            "write",
            "execute",
            "kill",
            "restart",
            "install",
            "truncate",
            "dispatch",
        )
    )
    if not shell_write and (
        name in _READ_TOOLS
        or name in _ARTIFACT_TOOLS
        or name in MCP_READ_TOOLS
        or (name in configured_reads and not mutating)
    ):
        return False
    identity = CURRENT_IDENTITY.get()
    if identity is None or not identity.is_admin:
        raise PermissionError("高危或未分类工具仅允许可信 AI 管理员调用")
    if identity.access_token:
        get_access_store().resolve(identity.access_token)
    user = await _validate_inoe_token(
        sso_settings_store.get_userinfo_url(), identity.inoe_token
    )
    if user_subject(extract_user(user)) != user_subject(identity.user):
        # getInfo uses userName; stable userId is what matters here.
        raise PermissionError("执行前认证身份不一致")
    return True
