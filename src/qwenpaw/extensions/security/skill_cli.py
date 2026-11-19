"""Fixed CLI contracts for bundled scheduling and messaging skills.

These commands retain the CLI's request credentials and server authorization.
The boolean result requests administrator approval; GETs also require it
because the corresponding APIs are scoped by agent, not by chat owner.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .skill_scripts import _json_file, _parse, workspace_path

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CRON_VALUES = (
    "--file --type --schedule-type --name --cron --run-at "
    "--repeat-every-days --repeat-end-type --repeat-until --repeat-count "
    "--channel --target-user --target-session --text --timezone --mode "
    "--timeout"
)
_CRON_SWITCHES = (
    "--enabled --no-enabled --save-result-to-inbox "
    "--no-save-result-to-inbox --share-session --no-share-session"
)


def _required(options: dict, *names: str) -> None:
    for name in names:
        value = options.get(name)
        if not isinstance(value, str) or not value.strip():
            raise PermissionError(f"技能 CLI 缺少有效参数：{name}")


def _object(value: object, allowed: str) -> dict:
    if not isinstance(value, dict) or set(value) - set(allowed.split()):
        raise PermissionError("技能 CLI JSON 包含未获准字段")
    return value


def _cron_payload(payload: dict, job_id: str | None) -> None:
    _object(
        payload,
        "id name enabled schedule task_type text request dispatch runtime "
        "save_result_to_inbox meta",
    )
    if payload.get("id") not in (None, "", job_id):
        raise PermissionError("任务 JSON 不能更换任务身份")
    _required(payload, "name")
    _object(
        payload.get("schedule"),
        "type cron run_at timezone repeat_every_days repeat_end_type "
        "repeat_until repeat_count",
    )
    dispatch = _object(
        payload.get("dispatch"), "type channel target mode meta"
    )
    _required(dispatch, "channel")
    target = _object(dispatch.get("target"), "user_id session_id")
    _required(target, "user_id", "session_id")
    _object(
        payload.get("runtime", {}),
        "max_concurrency timeout_seconds misfire_grace_seconds share_session",
    )
    if payload.get("task_type", "agent") == "text":
        _required(payload, "text")
        if payload.get("request") is not None:
            raise PermissionError("固定消息任务不能附加 agent 请求")
    else:
        request = _object(payload.get("request"), "input session_id user_id")
        for key in ("session_id", "user_id"):
            if request.get(key) not in (None, target[key]):
                raise PermissionError("任务请求必须使用明确的分发目标")
        messages = request.get("input")
        if not isinstance(messages, list) or not messages:
            raise PermissionError("任务请求必须包含用户文本消息")
        for message in messages:
            _object(message, "role type content")
            if message.get("role") != "user":
                raise PermissionError("任务请求只允许用户消息")
            content = message.get("content")
            if not isinstance(content, list) or not content:
                raise PermissionError("任务请求缺少文本内容")
            for block in content:
                _object(block, "type text")
                if block.get("type") != "text":
                    raise PermissionError("任务请求只允许文本内容")
                _required(block, "text")


def check_cli_arguments(
    args: list[str],
    directory: Path,
    workspace: Path,
    check_path: Callable[[str], None],
) -> bool:
    """Check tokens after ``qwenpaw``; never allow global/URL overrides."""
    if sum(map(len, args)) > 65536 or len(args) < 2:
        raise PermissionError("技能 CLI 需要明确子命令且参数不能超长")
    group, action, *rest = args
    actions = {
        "cron": {
            "list",
            "get",
            "state",
            "create",
            "update",
            "delete",
            "pause",
            "resume",
            "run",
        },
        "chats": {"list", "get", "create", "update", "delete"},
        "channels": {"send"},
    }
    if group not in actions or action not in actions[group]:
        raise PermissionError("技能 CLI 子命令未获准")
    if rest in (["--help"], ["-h"]):
        return False
    if any(value in {"--help", "-h"} for value in rest):
        raise PermissionError("帮助参数不能与实际操作混用")
    values, switches, positional = "--agent-id", "", 0
    if group == "cron":
        positional = int(action not in {"list", "create"})
        if action in {"create", "update"}:
            values += " " + _CRON_VALUES
            switches = _CRON_SWITCHES
    elif group == "chats":
        positional = int(action in {"get", "update", "delete"})
        values += {
            "list": " --user-id --channel",
            "create": " --file --name --session-id --user-id --channel",
            "update": " --name",
        }.get(action, "")
    else:
        values += " --channel --target-user --target-session --text"
    identifiers, options = _parse(rest, values, switches, positional)
    if options.get("--agent-id") != workspace.resolve().name:
        raise PermissionError("技能 CLI 必须显式指定当前工作区 --agent-id")
    if any(not _ID.fullmatch(item) for item in identifiers):
        raise PermissionError("技能 CLI 资源 ID 必须是独立路径段")
    for flag in ("--enabled", "--share-session", "--save-result-to-inbox"):
        if flag in options and flag.replace("--", "--no-", 1) in options:
            raise PermissionError("技能 CLI 开关不能相互冲突")
    if "--file" in options:
        if set(options) != {"--agent-id", "--file"}:
            raise PermissionError("JSON 文件不能与内联参数混用")
        path = workspace_path(
            options["--file"], directory, workspace, check_path
        )
        payload = _json_file(path)
        if group == "cron":
            _cron_payload(payload, identifiers[0] if identifiers else None)
        else:
            _object(payload, "name session_id user_id channel meta")
            _required(payload, "session_id", "user_id")
    elif group == "channels":
        _required(
            options, "--channel", "--target-user", "--target-session", "--text"
        )
    elif group == "chats" and action == "create":
        _required(options, "--session-id", "--user-id")
    elif group == "chats" and action == "update":
        _required(options, "--name")
    elif group == "cron" and action == "create":
        _required(
            options,
            "--type",
            "--name",
            "--channel",
            "--target-user",
            "--target-session",
            "--text",
        )
        _required(
            options,
            (
                "--run-at"
                if options.get("--schedule-type") == "scheduled"
                else "--cron"
            ),
        )
    return True
