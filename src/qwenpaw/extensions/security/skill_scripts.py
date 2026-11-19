"""Reviewed argument contracts for bundled business skill entrypoints.

Integrity is checked by execution_policy before these contracts are used.
The boolean result means a real administrator approval is mandatory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable

# The skill directory and relative entrypoint both form the execution contract.
SCRIPT_SKILLS = {
    "kb_search.py": "knowledge-search",
    "kb_query.py": "knowledge-base",
    "find_page.py": "page-navigator",
    "private_line_business_monitor.py": "private-line-business-monitor",
    "web_monitor.py": "web-availability-monitor",
    "score_root_cause.py": "alarm-analyst",
    "send_analysis_report.py": "alarm-analyst",
    "query_alarm_class_count.py": "real-alarm",
    "find_op.py": "page-operator",
    "scan_catalog.py": "page-operator",
    "emit_action.py": "page-operator",
    "emit_operate.py": "page-operator",
    "fde_tools.py": "fde-onboarding",
    "resource_import_bridge.py": "zgops-cmdb-import",
}

_MAX_JSON_BYTES = 256 * 1024
_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
_SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_WEB_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")


def check_web_identifiers(params: dict) -> None:
    """IDs are opaque path segments, never URL paths or query strings."""
    for key in (
        "--monitor-id",
        "--run-id",
        "monitor_id",
        "run_id",
        "monitorId",
        "runId",
    ):
        if key in params and params[key] is not None:
            if not _WEB_ID.fullmatch(str(params[key])):
                raise PermissionError("Web 监测 ID 格式不合法")


def workspace_path(
    value: str,
    directory: Path,
    workspace: Path,
    check_path: Callable[[str], None],
) -> Path:
    """Reject links and escapes, including non-existent output paths."""
    if not isinstance(value, str) or not value:
        raise PermissionError("技能文件路径必须是非空字符串")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = directory / candidate
    workspace = workspace.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace):
        raise PermissionError("技能输入输出只能位于当前工作区")
    for item in (candidate, *candidate.parents):
        if item == workspace:
            break
        if item.is_symlink():
            raise PermissionError("技能输入输出不能使用符号链接")
    check_path(str(resolved))
    if resolved.name.startswith(".env."):
        raise PermissionError("技能不能访问环境凭据文件")
    return resolved


def _tree(path: Path, check_path: Callable[[str], None]) -> None:
    # FDE selfcheck/show and source scans may recursively read children.
    total = 0
    for index, item in enumerate(path.rglob("*")):
        if index >= 2000:
            raise PermissionError("技能目录超过 2000 项限制")
        if item.is_symlink():
            raise PermissionError("技能目录不能含符号链接")
        check_path(str(item))
        if item.name.startswith(".env.") and item.name != ".env.example":
            raise PermissionError("技能目录包含环境凭据文件")
        if item.is_file() and item.stat().st_size > 10 * 1024 * 1024:
            raise PermissionError("技能目录文件过大")
        if item.is_file():
            total += item.stat().st_size
            if total > 50 * 1024 * 1024:
                raise PermissionError("技能目录文件合计超过 50 MiB")


def _parse(
    args: list[str],
    values: str = "",
    switches: str = "",
    positional: int = 0,
    repeat: str = "",
) -> tuple[list[str], dict[str, str]]:
    allowed = set(values.split())
    toggles = set(switches.split()) | {"--help", "-h"}
    repeated = set(repeat.split())
    items: list[str] = []
    options: dict[str, str] = {}
    index = 0
    while index < len(args):
        value = args[index]
        flag, sep, inline = value.partition("=")
        if value.startswith("-"):
            if flag not in allowed | toggles:
                raise PermissionError(f"技能参数未获准：{flag}")
            if flag in options and flag not in repeated:
                raise PermissionError(f"技能参数不能重复：{flag}")
            if flag in toggles:
                if sep:
                    raise PermissionError(f"布尔参数不能带值：{flag}")
                options[flag] = "true"
            else:
                if not sep:
                    index += 1
                    if index >= len(args) or args[index].startswith("--"):
                        raise PermissionError(f"技能参数缺少值：{flag}")
                    inline = args[index]
                options[flag] = inline
        else:
            items.append(value)
        index += 1
    if len(items) != positional and not ({"--help", "-h"} & options.keys()):
        raise PermissionError("技能位置参数数量不匹配")
    return items, options


def _json_file(path: Path) -> dict:
    if path.suffix.lower() != ".json" or path.stat().st_size > _MAX_JSON_BYTES:
        raise PermissionError("上下文必须是 256 KiB 以内的 JSON 文件")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PermissionError("上下文必须是 JSON 对象")
    return payload


def check_arguments(
    script: Path,
    args: list[str],
    directory: Path,
    workspace: Path,
    check_path: Callable[[str], None],
) -> bool:
    """Validate exact flags/subcommands without importing untrusted code."""
    name = script.name
    if script.parent.name != "scripts" or (
        script.parent.parent.name != SCRIPT_SKILLS[name]
    ):
        raise PermissionError("技能入口与受管技能目录不匹配")
    if sum(map(len, args)) > 65536:
        raise PermissionError("技能参数超过长度限制")

    def local(value: str) -> Path:
        return workspace_path(value, directory, workspace, check_path)

    if name in {"kb_search.py", "kb_query.py", "find_page.py", "find_op.py"}:
        query_flags = "--output"
        if name in {"find_page.py", "find_op.py"}:
            query_flags += " --top-k"
        _parse(
            args, query_flags, "--refresh" if name == "find_page.py" else "", 1
        )
        return False
    if name == "score_root_cause.py":
        _parse(
            args,
            "--claim --object-match --mechanism --time-match " "--independent",
            "--key-conflict",
        )
        return False
    if name == "query_alarm_class_count.py":
        _parse(
            args,
            "--start_time --startTime --end_time --endTime "
            "--alarm_class --alarmClass --alarm_status --alarmstatus "
            "--ne_alias --neAlias --resource_type --resource --output",
        )
        return False
    if name == "send_analysis_report.py":
        _parse(
            args,
            "--alarm-id --alarm-title --visible-content --device-name "
            "--manage-ip --asset-id --level --status --event-time "
            "--analysis-summary --root-cause --emergency-plan --suggestion "
            "--suggestions-json --abnormal-metrics-json --metric-type "
            "--chat-id --res-id --output",
            repeat="--suggestion",
        )
        return True
    if name == "emit_action.py":
        # Only the integrity-checked catalog is used. Cards still require
        # confirmation in the UI, and producing them requires approval too.
        _parse(
            args,
            "--params --set --output",
            "--no-resolve-route",
            1,
            repeat="--set",
        )
        return True
    if name == "emit_operate.py":
        _parse(
            args,
            "--navigate --page --fill --click --row-index --row-match "
            "--row-click --open --accept --risk --title --output",
            "--upload",
            repeat="--fill",
        )
        return True
    if name == "scan_catalog.py":
        _, opts = _parse(args, "--src --out --limit")
        if "--src" not in opts:
            raise PermissionError("目录扫描必须明确指定工作区内 --src")
        _tree(local(opts["--src"]), check_path)
        if "--out" in opts:
            output = local(opts["--out"])
            if output.suffix != ".json" or not output.is_relative_to(
                workspace.resolve() / "artifacts"
            ):
                raise PermissionError("目录扫描输出仅允许 artifacts 下 JSON")
            if output.exists():
                raise PermissionError("目录扫描不能覆盖已有文件")
        return "--out" in opts

    if not args or args[0].startswith("-"):
        if args in (["--help"], ["-h"]):
            return False
        raise PermissionError("技能需要明确子命令")
    action, rest = args[0], args[1:]
    if name == "private_line_business_monitor.py":
        flags = {
            "summary": "",
            "list-circuits": "--keyword --status --type --customer --limit",
            "detail": "--code --keyword",
            "cutover": "--code --notice-code --keyword",
            "rank": "--metric --limit",
            "ask": "--question",
        }
        if action not in flags:
            raise PermissionError("未知专线查询子命令")
        _parse(rest, flags[action] + " --output")
        return False
    if name == "web_monitor.py":
        if action == "delete-runs":
            # argparse's nargs="+" needs a bounded, explicitly delimited
            # list. Normalize it before the ordinary exact-flag parser.
            normalized = []
            ids: list[str] = []
            index = 0
            while index < len(rest):
                if rest[index] == "--run-ids":
                    if ids:
                        raise PermissionError("批量运行 ID 参数不能重复")
                    index += 1
                    while index < len(rest) and not rest[index].startswith(
                        "-"
                    ):
                        ids.append(rest[index])
                        index += 1
                    if not ids or len(ids) > 100:
                        raise PermissionError(
                            "每次删除需要 1 至 100 个运行 ID"
                        )
                    continue
                normalized.append(rest[index])
                index += 1
            _parse(normalized, "--output")
            if not ids:
                raise PermissionError("批量删除需要 --run-ids")
            for value in ids:
                check_web_identifiers({"run_id": value})
            return True
        flags = {
            "health": "",
            "dashboard": "",
            "list-monitors": "--keyword --status --limit",
            "detail": "--monitor-id --monitor-name",
            "runs": "--monitor-id --monitor-name --status --limit",
            "run": "--run-id",
            "create": "--payload-file --payload-json",
            "update": (
                "--monitor-id --monitor-name --payload-file --payload-json"
            ),
            "publish": "--monitor-id --monitor-name",
            "trigger": (
                "--monitor-id --monitor-name --definition-file "
                "--definition-json --wait-seconds --poll-interval"
            ),
            "delete-monitor": "--monitor-id --monitor-name",
            "delete-run": "--run-id",
        }
        if action not in flags:
            raise PermissionError(
                "Web 子命令未获准；选择器探测需单独配置安全连接器"
            )
        _, opts = _parse(
            rest,
            flags[action] + " --output",
            "--publish" if action in {"create", "update"} else "",
        )
        check_web_identifiers(opts)
        for flag in ("--payload-file", "--definition-file"):
            if flag in opts:
                _json_file(local(opts[flag]))
        return action not in {
            "health",
            "dashboard",
            "list-monitors",
            "detail",
            "runs",
            "run",
        }
    if name == "resource_import_bridge.py":
        if action not in {
            "start",
            "metadata",
            "preview",
            "import",
            "topology-prompt",
        }:
            raise PermissionError("未知资源导入子命令")
        _, opts = _parse(rest, "--context-file")
        context = (
            _json_file(local(opts["--context-file"]))
            if "--context-file" in opts
            else {}
        )
        if context.get("agentId") not in (None, "", workspace.name):
            raise PermissionError("资源导入不能更换当前智能体身份")
        if context.get("progressFile"):
            progress = local(context["progressFile"])
            if not progress.is_relative_to(workspace.resolve() / "artifacts"):
                raise PermissionError("导入进度输出只能位于 artifacts")
        files = context.get("files") or []
        if not isinstance(files, list) or len(files) > 20:
            raise PermissionError("导入最多允许 20 个文件")
        total = 0
        for item in files:
            if not isinstance(item, dict) or not isinstance(
                item.get("path"), str
            ):
                raise PermissionError("导入文件缺少有效路径")
            path = local(item["path"])
            if path.suffix.lower() not in {
                ".xlsx",
                ".xls",
                ".csv",
                ".tsv",
                ".json",
                ".txt",
                ".md",
                ".docx",
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
            }:
                raise PermissionError("导入文件类型未获准")
            total += path.stat().st_size
        if total > 50 * 1024 * 1024:
            raise PermissionError("导入文件合计超过 50 MiB")
        return action == "import"
    if name == "fde_tools.py":
        if script.parents[3] != workspace.resolve():
            raise PermissionError("FDE 命令只能在其所属工作区执行")
        flags = {
            "list-agents": "",
            "list-staged": "--staged-dir",
            "show-staged": "--name --staged-dir --max-bytes",
            "selfcheck": "--skill-dir",
            "scaffold": "--name --target-workspace --brief-file --out-dir",
            "discard": "--name --staged-dir",
            "create-agent": "--id --name --description --provider --model",
        }
        if action not in flags:
            raise PermissionError(
                "该 FDE 动作需要隔离执行器；不能在服务进程旁运行生成代码"
            )
        _, opts = _parse(
            rest,
            flags[action],
            "--json --yes" if action == "discard" else "--json",
        )
        required = {
            "scaffold": {"--name", "--target-workspace"},
            "selfcheck": {"--skill-dir"},
            "show-staged": {"--name"},
            "discard": {"--name"},
            "create-agent": {"--id"},
        }.get(action, set())
        if not required.issubset(opts):
            raise PermissionError("FDE 动作缺少必填参数")
        for flag in ("--name", "--target-workspace", "--id"):
            if flag in opts and not (
                flag == "--name" and action == "create-agent"
            ):
                if not _SAFE_NAME.fullmatch(opts[flag]):
                    raise PermissionError("技能或智能体标识格式不合法")
        if action in {"scaffold", "show-staged", "discard"} and (
            not _SKILL_NAME.fullmatch(opts["--name"])
        ):
            # The FDE executor normalizes underscores/repeated hyphens.
            # Reject aliases so approval snapshots match its actual target.
            raise PermissionError("技能名称必须使用小写字母数字和单个连字符")
        # The CLI's default is relative to its owning workspace, not cwd
        # (the documented invocation usually uses cwd=the skill directory).
        staged = local(str(workspace.resolve() / "staged"))
        override = os.environ.get("QWENPAW_FDE_STAGED_DIR")
        if override and local(override) != staged:
            raise PermissionError("FDE staged 配置越过当前工作区")
        for flag in ("--skill-dir", "--staged-dir", "--out-dir"):
            if flag in opts:
                target = local(opts[flag])
                if not target.is_relative_to(staged):
                    raise PermissionError(
                        "FDE 文件操作仅允许当前工作区 staged"
                    )
                _tree(target, check_path)
        if "--staged-dir" not in opts:
            _tree(staged, check_path)
        if "--brief-file" in opts:
            _json_file(local(opts["--brief-file"]))
        if action == "discard" and "--yes" not in opts:
            raise PermissionError(
                "删除 staged 技能需要 --yes 并通过管理员审批"
            )
        return action in {"scaffold", "discard", "create-agent"}
    raise PermissionError("技能尚未声明执行契约")


def approval_files(command: str, directory: Path) -> dict[str, str]:
    """Bind approval to file content, not only mutable filenames."""
    import shlex

    args = shlex.split(command)
    result = {}
    for index, arg in enumerate(args):
        flag, sep, value = arg.partition("=")
        if flag not in {
            "--context-file",
            "--payload-file",
            "--definition-file",
            "--brief-file",
            "--file",
        }:
            continue
        value = value if sep else args[index + 1]
        path = (directory / Path(value).expanduser()).resolve()
        result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        if flag == "--context-file":
            payload = _json_file(path)
            for item in payload.get("files") or []:
                attachment = (
                    directory / Path(item["path"]).expanduser()
                ).resolve()
                result[str(attachment)] = hashlib.sha256(
                    attachment.read_bytes()
                ).hexdigest()
    if (
        len(args) > 2
        and Path(args[1]).name == "fde_tools.py"
        and args[2] == "discard"
    ):
        script = (directory / Path(args[1]).expanduser()).resolve()
        _, options = _parse(args[3:], "--name --staged-dir", "--yes --json")
        staged = script.parents[3] / "staged"
        if "--staged-dir" in options:
            staged = (
                directory / Path(options["--staged-dir"]).expanduser()
            ).resolve()
        target = staged / options["--name"]
        for item in (target, *sorted(target.rglob("*"))):
            result[str(item)] = (
                hashlib.sha256(item.read_bytes()).hexdigest()
                if item.is_file()
                else "directory" if item.is_dir() else "missing"
            )
    return result
