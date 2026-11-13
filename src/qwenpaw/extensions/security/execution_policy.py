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
from typing import Any

from qwenpaw.constant import BACKUP_DIR, EnvVarLoader, SECRET_DIR, WORKING_DIR
from qwenpaw.config.context import get_current_workspace_dir
from qwenpaw.extensions.api.access_session import (
    CURRENT_IDENTITY,
    get_access_store,
    user_subject,
)
from qwenpaw.extensions.api import sso_settings_store
from qwenpaw.extensions.api.sso_backend import _validate_inoe_token
from qwenpaw.extensions.api.sso_auth import extract_user
from .business_reads import MCP_READ_TOOLS

_READ_TOOLS = {
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


def enabled() -> bool:
    return EnvVarLoader.get_str("QWENPAW_PRODUCTION_GUARDS", "true").lower() not in {
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
    path = (Path(get_current_workspace_dir() or WORKING_DIR) / candidate).resolve()
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
    if path.name == "agent.json" or path == Path(WORKING_DIR).resolve() / "config.json":
        raise PermissionError("完整运行配置只能通过授权管理接口访问")
    if path.name == ".env" or path.suffix in {".pem", ".key", ".env"}:
        raise PermissionError("禁止工具访问凭据文件")
    if path.name in {
        "audit.db",
        "audit.log",
        "audit.sqlite",
        "governance_audit.db",
    }:
        raise PermissionError("禁止工具直接访问审计存储")
    if path.parts[:2] in {("/", "proc"), ("/", "sys"), ("/", "dev")}:
        raise PermissionError("禁止工具访问进程、系统或设备文件")
    if any(
        part in {".ssh", ".aws", ".kube", ".gnupg", ".docker", "backups"}
        for part in path.parts
    ) or path.name in {".netrc", ".git-credentials"}:
        raise PermissionError("禁止工具访问系统凭据或备份目录")


def _approved_script(path: Path) -> bool:
    check_path(str(path))
    if not path.is_file() or path.suffix != ".py":
        return False
    hashes = json.loads(EnvVarLoader.get_str("QWENPAW_ALLOWED_SCRIPT_HASHES", "{}"))
    if not isinstance(hashes, dict):
        raise ValueError("Script hash allowlist must be a JSON object")
    expected = hashes.get(str(path))
    if expected is None:
        seed = Path(
            EnvVarLoader.get_str("QWENPAW_SKILL_SEED_PATH", "/app/share/qwenpaw-seed")
        )
        manifest_path = seed / "seed-manifest.json"
        if not manifest_path.is_file():
            return False
        if path.name not in _READ_SCRIPT_NAMES:
            return False
        try:
            relative = str(path.relative_to(Path(WORKING_DIR).resolve()))
        except ValueError:
            return False
        manifest = json.loads(manifest_path.read_text())
        expected = manifest.get("managed_files", {}).get(relative, {}).get("sha256")
        parts = Path(relative).parts
        if "skills" not in parts:
            return False
        skill_index = parts.index("skills")
        skill_relative = Path(*parts[: skill_index + 2])
        skill_files = (
            manifest.get("managed_skills", {})
            .get(str(skill_relative), {})
            .get("files", {})
        )
        if not skill_files:
            return False
        working = Path(WORKING_DIR).resolve()
        for name, checksum in skill_files.items():
            source = (working / name).resolve()
            if (
                not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest() != checksum
            ):
                return False
        for source in (working / skill_relative).rglob("*"):
            if source.is_file() and source.suffix in {".py", ".so", ".pth"}:
                if str(source.relative_to(working)) not in skill_files:
                    return False
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
        if not _approved_script(metric_helpers) or not _approved_script(cmdb_helpers):
            return False
    return bool(
        isinstance(expected, str)
        and hashlib.sha256(path.read_bytes()).hexdigest() == expected
    )


def check_shell(command: str, cwd: Any = None) -> None:
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
            return
        raise PermissionError("仅允许受控智能体协同 CLI")
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
    directory = Path(cwd or get_current_workspace_dir() or WORKING_DIR).resolve()
    path = (directory / args[1]).resolve()
    if not _approved_script(path):
        raise PermissionError("脚本未在生产白名单中或完整性校验失败")
    if path.name == "inspect_resource_metrics.py" and "--no-notify" not in args[2:]:
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
        if value.split("=", 1)[0] in {"--rules-file", "--file", "--input-file"}:
            file_value = (
                value.split("=", 1)[1]
                if "=" in value
                else (args[index + 1] if index + 1 < len(args) else "")
            )
            check_path(str(directory / file_value))


async def check_tool(name: str, params: dict[str, Any]) -> bool:
    """Return whether this call needs mandatory administrator approval."""
    if not enabled():
        return False
    for key in ("file_path", "path", "filename"):
        value = params.get(key)
        if not isinstance(value, str):
            continue
        check_path(value)
    if name == "execute_shell_command":
        check_shell(str(params.get("command", "")), params.get("cwd"))
        return False
    configured_reads = {
        value.strip()
        for value in EnvVarLoader.get_str("QWENPAW_READONLY_TOOL_NAMES", "").split(",")
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
    if (
        name in _READ_TOOLS
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
