"""Read and summarize a single metric result in the current Scroll session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.constant import EnvVarLoader, WORKING_DIR
from qwenpaw.extensions.security.managed_integrity import inspect_skill

_METRIC_TOOL = "inspection__getMetricData"
_MAX_RESULT_BYTES = 8 * 1024 * 1024
_MAX_SUMMARY_CHARS = 24000
_ID = re.compile(r"[a-zA-Z0-9_.:-]{1,160}")


def _load_summarizer(workspace: Path):
    working = Path(WORKING_DIR).resolve()
    if not workspace.is_relative_to(working):
        raise ValueError("当前工作区没有受管告警分析技能")
    skill = workspace / "skills" / "alarm-analyst"
    skill_key = skill.relative_to(working).as_posix()
    script = skill / "scripts" / "summarize_metric_result.py"
    manifest_path = Path(
        EnvVarLoader.get_str("QWENPAW_SKILL_SEED_PATH", "/app/share/qwenpaw-seed")
    ) / "seed-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not inspect_skill(working, manifest, skill_key)["execution_ready"]:
        raise ValueError("告警分析技能未通过受管完整性校验")
    expected = manifest["managed_skills"][skill_key]["files"].get(
        script.relative_to(working).as_posix(),
    )
    source = script.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected:
        raise ValueError("指标摘要模块未通过受管完整性校验")
    namespace: dict = {"__name__": "alarm_metric_summary"}
    # Execute the verified bytes, so the loader cannot reopen a changed file.
    exec(compile(source, str(script), "exec"), namespace)
    return namespace["summarize_records"]


def _summarize(
    workspace: Path,
    db_name: str,
    session_id: str,
    agent_id: str,
    tool_call_id: str,
    res_id: str,
) -> str:
    if not _ID.fullmatch(tool_call_id) or not _ID.fullmatch(res_id):
        raise ValueError("工具调用 ID 或 CI ID 格式无效")
    workspace = workspace.resolve()
    db = (workspace / db_name).resolve()
    if not db.is_relative_to(workspace):
        raise ValueError("历史指标存储超出当前工作区")
    with closing(
        sqlite3.connect(db.as_uri() + "?mode=ro", uri=True),
    ) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT kind, name,
                      CASE WHEN length(CAST(content AS BLOB)) <= ?
                           THEN content END AS content
               FROM conversation_history
               WHERE session_id = ? AND agent_id = ? AND tool_call_id = ?
                 AND kind = 'tool_result' AND name = ?
               LIMIT 2""",
            (
                _MAX_RESULT_BYTES, session_id, agent_id, tool_call_id,
                _METRIC_TOOL,
            ),
        ).fetchall()
    if len(rows) != 1 or not rows[0]["content"]:
        raise ValueError("当前会话没有唯一且可读取的完整指标结果")
    summarize = _load_summarizer(workspace)
    summary = json.dumps(
        summarize([dict(rows[0])], res_id=res_id),
        ensure_ascii=False,
    )
    if len(summary) > _MAX_SUMMARY_CHARS:
        raise ValueError("历史指标摘要超过输出上限")
    return summary


def make_alarm_metric_history_tool(
    workspace: Path,
    db_name: str,
    session_id: str,
    agent_id: str,
):
    async def summarize_alarm_metric_history(
        tool_call_id: str,
        res_id: str,
    ) -> ToolChunk:
        """Summarize a stored getMetricData result from this alarm session.

        Args:
            tool_call_id: Actual inspection__getMetricData call ID.
            res_id: Verified CI ID from that metric call.
        """
        try:
            text = await asyncio.to_thread(
                _summarize, workspace, db_name, session_id, agent_id,
                tool_call_id, res_id,
            )
            state = ToolResultState.SUCCESS
        except json.JSONDecodeError:
            text = "历史指标摘要的受管配置不可用"
            state = ToolResultState.ERROR
        except ValueError as exc:
            text = str(exc)
            state = ToolResultState.ERROR
        except (OSError, sqlite3.Error, KeyError, TypeError):
            text = "历史指标结果或受管摘要模块不可读取"
            state = ToolResultState.ERROR
        return ToolChunk(content=[TextBlock(text=text)], state=state)

    return summarize_alarm_metric_history
