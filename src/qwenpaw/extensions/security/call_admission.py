"""Persistent deployment-wide restrictions for Agent dispatch, never grants."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, NamedTuple

from ...constant import WORKING_DIR

logger = logging.getLogger(__name__)
DB_NAME = "call-admission.db"
CMDB_LOOKUP = "lookup_portal_cmdb_asset"
Risk = Literal["low", "medium", "high", "critical"]


class Target(NamedTuple):
    kind: str
    name: str
    service: str = ""


class PolicyUnavailable(RuntimeError):
    pass


class PolicyConflict(RuntimeError):
    pass


# Each row is also the immutable change record for that target. The latest
# revision is used at dispatch, across workers sharing the same working dir.
_SCHEMA = """CREATE TABLE IF NOT EXISTS revisions (
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    revision INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('inherit', 'deny')),
    risk TEXT NOT NULL CHECK(risk IN ('low', 'medium', 'high', 'critical')),
    reason TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(kind, name, service, revision)
)"""


# Separate metadata keeps the existing revisions table writable by older workers.
_BASELINE_SCHEMA = """CREATE TABLE IF NOT EXISTS baseline_risk_revisions (
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY(kind, name, service, revision)
)"""


def _path() -> Path:
    return WORKING_DIR / "governance" / DB_NAME


def _read_connection() -> sqlite3.Connection | None:
    path = _path()
    try:
        path.stat()
    except FileNotFoundError:
        # Upgrades are compatible before the first rule has ever been saved.
        return None
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def _latest(conn: sqlite3.Connection, target: Target) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM revisions WHERE kind=? AND name=? AND service=? "
        "ORDER BY revision DESC LIMIT 1", target,
    ).fetchone()


def read_rules() -> dict[Target, dict]:
    try:
        conn = _read_connection()
        if conn is None:
            return {}
        with closing(conn):
            conn.execute("BEGIN")
            has_metadata = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='baseline_risk_revisions'",
            ).fetchone()
            risk_source = (
                ", CASE WHEN b.revision IS NULL THEN 'manual' ELSE 'baseline' END AS risk_source"
                if has_metadata else ""
            )
            baseline_join = (
                " LEFT JOIN baseline_risk_revisions b USING (kind, name, service, revision)"
                if has_metadata else ""
            )
            rows = conn.execute(
                f"SELECT r.*{risk_source} FROM revisions r JOIN (SELECT kind, name, service, "
                "MAX(revision) AS revision FROM revisions GROUP BY kind, name, service) "
                f"USING (kind, name, service, revision){baseline_join}",
            )
            return {Target(r["kind"], r["name"], r["service"]): dict(r) for r in rows}
    except (OSError, sqlite3.Error) as exc:
        raise PolicyUnavailable from exc


def save_rule(
    target: Target, *, revision: int, decision: str, risk: Risk | None,
    reason: str, actor: str, baseline_risk: Risk = "high",
) -> dict:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=1)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_SCHEMA)
            prior = _latest(conn, target)
            if revision != (prior["revision"] if prior else 0):
                raise PolicyConflict
            baseline = False
            if risk is None:
                # An admission-only edit preserves an existing manual assessment.
                conn.execute(_BASELINE_SCHEMA)
                baseline = prior is None or conn.execute(
                    "SELECT 1 FROM baseline_risk_revisions WHERE kind=? AND name=? "
                    "AND service=? AND revision=?", (*target, revision),
                ).fetchone() is not None
                risk = baseline_risk if baseline else prior["risk"]
                if baseline:
                    conn.execute(
                        "INSERT INTO baseline_risk_revisions VALUES (?, ?, ?, ?)",
                        (*target, revision + 1),
                    )
            conn.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*target, revision + 1, decision, risk, reason, actor,
                 datetime.now(timezone.utc).isoformat()),
            )
            row = dict(_latest(conn, target))
            row["risk_source"] = "baseline" if baseline else "manual"
        logger.info(
            "[SECURITY_CONFIG] action=update_call_admission actor=%r target=%r "
            "previous=%s decision=%s risk=%s revision=%d",
            actor, target, prior["decision"] if prior else "inherit", decision, risk, revision + 1,
        )
        return row
    except (OSError, sqlite3.Error) as exc:
        raise PolicyUnavailable from exc


def blocked_by(target: Target, *, script_rules: bool = True) -> Target | None:
    """Check this layer only, before dispatch; MCP service denials dominate."""
    if target.kind == "mcp_tool":
        targets = (Target("mcp_service", target.service), target)
    elif target.kind == "script":
        shell = Target("tool", "execute_shell_command")
        targets = (shell, target) if script_rules else (shell,)
    else:
        targets = (target,)
    try:
        conn = _read_connection()
        if conn is None:
            return None
        with closing(conn):
            conn.execute("BEGIN")
            for key in targets:
                row = _latest(conn, key)
                if row and row["decision"] == "deny":
                    return key
    except (OSError, sqlite3.Error) as exc:
        raise PolicyUnavailable from exc
    return None


def require_not_blocked(target: Target) -> None:
    try:
        blocked = blocked_by(target)
    except PolicyUnavailable as exc:
        logger.error("Call admission policy unavailable: %s", type(exc.__cause__).__name__)
        raise PermissionError("调用准入策略不可读取，已停止本次调用") from exc
    if blocked:
        logger.info("[CALL_ADMISSION] decision=deny target=%r blocked_by=%r", target, blocked)
        raise PermissionError("调用已被系统调用准入策略禁止")


def require_agent_tool(name: str) -> None:
    # The dedicated fixed API and its Portal tool use one control, not two
    # conflicting rows for the same operation.
    require_not_blocked(Target("api" if name == CMDB_LOOKUP else "tool", name))


class Baseline(NamedTuple):
    risk: Risk
    boundary: str


_TOOL_BASELINES: dict[str, Baseline] = {
    "get_current_time": Baseline("low", "读取当前时间，不读取业务数据。"),
    "get_token_usage": Baseline("medium", "读取模型用量统计，可能暴露内部使用量或模型信息。"),
    "set_user_timezone": Baseline("medium", "写入当前用户的时区偏好。"),
    "list_agents": Baseline("medium", "读取可见智能体信息，不提交任务。"),
    "check_agent_task": Baseline("medium", "查询协同任务状态及结果，可能含业务信息。"),
    "read_file": Baseline("medium", "读取既有策略允许访问的文件，可能含内部数据。"),
    "grep_search": Baseline("medium", "按路径和搜索规则读取文本，可能含内部数据。"),
    "glob_search": Baseline("medium", "按路径和搜索规则枚举文件名。"),
    "ast_search": Baseline("medium", "在受限范围内检索源代码结构。"),
    "view_image": Baseline("medium", "读取图像，可能包含内部信息。"),
    "view_video": Baseline("medium", "读取视频，可能包含内部信息。"),
    "export_report": Baseline("medium", "启用生产保护时不能用通用报告导出数据，必须使用受控导出入口。"),
    "prepare_alarm_export": Baseline("medium", "核验告警明细导出范围；适用的导出管控仍有效。"),
    "check_work_order_export": Baseline("medium", "核验工单导出范围和单次上限，符合条件时返回本人确认下载入口。"),
    "process_office_document": Baseline("medium", "按文档工具约束处理文档及输出产物。"),
    "write_skill_context": Baseline("medium", "更新受限的技能上下文，不授予通用文件写入。"),
    "send_file_to_user": Baseline("high", "将文件发送给用户；适用的数据与导出限制仍有效。"),
    "chat_with_agent": Baseline("high", "把信息与任务委派给另一智能体。"),
    "submit_to_agent": Baseline("high", "向另一智能体提交异步任务。"),
    "spawn_subagent": Baseline("high", "启动协同任务并传递上下文；不授权下游工具。"),
    "delegate_external_agent": Baseline("high", "向外部智能体委派，可能传递内部上下文。"),
    "write_file": Baseline("high", "生产守卫开启时，仅可在当前工作区新建空 .txt 或 .md；开启工作区受控模式后需管理员审批。不覆盖已有文件。"),
    "edit_file": Baseline("high", "修改现有文件；受路径、沙箱及审批策略约束。"),
    "append_file": Baseline("high", "追加文件内容；受路径、沙箱及审批策略约束。"),
    "browser_use": Baseline("high", "浏览器交互可能读取数据或改变外部状态。"),
    "desktop_screenshot": Baseline("high", "捕获桌面图像，可能含敏感信息。"),
    "materialize_skill": Baseline("high", "创建技能文件；仍受技能扫描和写入边界约束。"),
    "execute_shell_command": Baseline("critical", "阻断整个 Shell 工具入口。生产守卫开启时，仅通过路径、哈希和参数校验的操作可继续；受控写操作须强制审批。"),
}
_CMDB_BASELINE = Baseline(
    "medium", "固定 GET，按完整资产名称查询；使用当前登录用户智观凭据，受上游数据授权限制。",
)
_MCP_SERVICE_BASELINE = Baseline(
    "high", "按服务标识阻断工具发现和新调用；不修改端点白名单，也不关闭已建立或后台维护的连接。",
)
_MCP_READ_BASELINE = Baseline(
    "medium", "生产策略中已分类的业务只读工具；仍受服务、用户及上游数据权限限制。",
)
_SCRIPT_BASELINE = Baseline(
    "high", "保守默认：受管脚本可能接触内部数据或执行受控写入。仅约束生产守卫校验通过的 Shell 脚本入口。",
)


def catalog() -> dict[Target, Baseline]:
    from .business_reads import MCP_READ_TOOLS
    from .execution_policy import known_tool_admissions, managed_script_entries

    entries = {Target("tool", name): row for name, row in _TOOL_BASELINES.items()}
    entries[Target("api", CMDB_LOOKUP)] = _CMDB_BASELINE
    for name in managed_script_entries():
        entries[Target("script", name)] = _SCRIPT_BASELINE
    for item in MCP_READ_TOOLS:
        service, _, name = item.partition("__")
        entries[Target("mcp_tool", name, service)] = _MCP_READ_BASELINE
        entries[Target("mcp_service", service)] = _MCP_SERVICE_BASELINE
    for name in known_tool_admissions().keys() - MCP_READ_TOOLS - {CMDB_LOOKUP}:
        if valid_identifier(name):
            entries.setdefault(Target("tool", name), Baseline(
                "high", "运维分类不等于风险评估；按内部业务数据或未知副作用保守定级。",
            ))
    return entries


def valid_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[\w./:@+-]{1,150}", value)) and "://" not in value


def describe(target: Target, rule: dict | None, baseline: Baseline | None) -> dict:
    rule = rule or {}
    if baseline is None:
        if target.kind == "mcp_service":
            baseline = _MCP_SERVICE_BASELINE
        elif target.kind == "mcp_tool":
            baseline = Baseline("high", "按服务标识和原始工具名匹配；不授予上游数据权限。")
        else:
            baseline = Baseline("high", "按工具原始标识匹配；工作区、审批及用户授权仍独立生效。")
    risk_source = rule.get("risk_source", "manual") if rule else "baseline"
    # Only expose bounded policy fields, never runtime arguments or credentials.
    return {
        "id": json.dumps(target, ensure_ascii=False),
        "kind": target.kind, "name": target.name, "service": target.service,
        "risk": rule["risk"] if risk_source == "manual" else baseline.risk,
        "default_risk": baseline.risk,
        "boundary": baseline.boundary, "risk_source": risk_source,
        "decision": rule.get("decision", "inherit"), "revision": rule.get("revision", 0),
        "reason": rule.get("reason"), "updated_at": rule.get("updated_at"),
    }
