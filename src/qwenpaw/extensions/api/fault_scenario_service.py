import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .fault_scenario_models import FaultScenarioDetection


CMDB_KEYWORDS = ("cmdb",)
CMDB_WRITE_ACTION_KEYWORDS = ("新增", "插入")
DATABASE_FAULT_KEYWORDS = ("mysql", "死锁")
FAILURE_HINT_KEYWORDS = ("失败", "报错", "超时")
ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS = 180
RES_ID_RE = re.compile(r"资源 ID（CI ID）[:：]\s*([0-9]+)")
DATETIME_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})")
IP_RE = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)




def detect_fault_scenario(*, employee_id: str, content: str | None) -> FaultScenarioDetection:
    normalized = str(content or "").strip().lower()
    if employee_id != "fault":
        return FaultScenarioDetection(False, "", "")

    has_cmdb_keyword = _contains_any_keyword(normalized, CMDB_KEYWORDS)
    has_cmdb_write_action = _contains_any_keyword(normalized, CMDB_WRITE_ACTION_KEYWORDS)
    has_database_fault = _contains_any_keyword(normalized, DATABASE_FAULT_KEYWORDS)
    has_failure_hint = _contains_any_keyword(normalized, FAILURE_HINT_KEYWORDS)

    if not (
        (has_cmdb_keyword and has_cmdb_write_action and has_failure_hint)
        or (has_database_fault and (has_cmdb_keyword or has_cmdb_write_action))
    ):
        return FaultScenarioDetection(False, "", "")
    return FaultScenarioDetection(
        triggered=True,
        scene_code="cmdb_add_failed_mysql_deadlock",
        entry_summary="正在关联分析...",
    )


def parse_fault_scenario_output(stdout_text: str) -> dict:
    payload = json.loads(stdout_text)
    payload.setdefault("summary", "诊断已完成")
    payload.setdefault("rootCause", {})
    payload.setdefault("steps", [])
    payload.setdefault("logEntries", [])
    payload.setdefault("actions", [])
    return payload


def _fault_skill_root() -> Path:
    configured_root = os.getenv("QWENPAW_FAULT_SKILL_ROOT", "").strip()
    if configured_root:
        return Path(configured_root)
    return (
        Path(__file__).resolve().parents[4]
        / "deploy-all"
        / "qwenpaw"
        / "working"
        / "workspaces"
        / "fault"
        / "skills"
    )


def _alarm_analyst_skill_root() -> Path:
    return _fault_skill_root() / "alarm-analyst"


def _alarm_analyst_context_script() -> Path:
    return _alarm_analyst_skill_root() / "scripts" / "analyze_alarm_context.py"


def _parse_alarm_dispatch_context(content: str | None) -> dict[str, str]:
    text = str(content or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    res_id_match = RES_ID_RE.search(text)
    event_time_match = DATETIME_RE.search(text)
    manage_ip_match = IP_RE.search(text)

    title = ""
    device_name = ""
    if lines:
        headline = lines[0]
        if "（" in headline and "）" in headline:
            title = headline.split("（", 1)[0].strip()
            inner = headline.split("（", 1)[1].rsplit("）", 1)[0].strip()
            if inner:
                parts = inner.split()
                if parts:
                    device_name = parts[0].strip()
        elif "·" in headline:
            parts = [part.strip() for part in headline.split("·") if part.strip()]
            if parts:
                title = parts[0]
            if len(parts) > 1:
                device_name = parts[1]
        else:
            title = headline

    return {
        "res_id": res_id_match.group(1) if res_id_match else "",
        "event_time": event_time_match.group(1) if event_time_match else "",
        "manage_ip": manage_ip_match.group(0) if manage_ip_match else "",
        "alarm_title": title,
        "device_name": device_name,
    }


def _build_alarm_analyst_result(context: dict[str, Any], dispatch_context: dict[str, str]) -> dict[str, Any]:
    topology = context.get("topology") or {}
    recent = (context.get("relatedAlarms") or {}).get("recent") or {}
    previous = (context.get("relatedAlarms") or {}).get("previous") or {}
    comparison = (context.get("relatedAlarms") or {}).get("comparison") or {}
    metric_analysis = context.get("metricAnalysis") or {}
    root_resource = topology.get("rootResource") or {}
    findings = context.get("findings") or []

    summary = findings[0] if findings else "已完成告警拓扑、关联告警和指标的联合分析。"
    root_cause = {
        "type": str(metric_analysis.get("metricType") or root_resource.get("ciTypeAlias") or root_resource.get("ciType") or "待分析"),
        "object": str(root_resource.get("name") or dispatch_context.get("res_id") or "cmdb_resource"),
    }
    steps = [
        {"id": "root-resource", "status": "success"},
        {"id": "cmdb-topology", "status": "success"},
        {"id": "related-alarms-recent", "status": "success"},
        {"id": "related-alarms-compare", "status": "success"},
        {"id": "metric-analysis", "status": "success"},
        {"id": "decision-merge", "status": "success"},
    ]
    log_entries = [
        {
            "stage": "root-resource",
            "summary": f"根资源 `{dispatch_context.get('res_id') or '-'}` 已确认，资源类型 `{metric_analysis.get('metricType') or root_resource.get('ciType') or '-'}`。",
        },
        {
            "stage": "cmdb-topology",
            "summary": f"共识别 {topology.get('resourceCount', 0)} 个拓扑关联资源。",
        },
        {
            "stage": "related-alarms",
            "summary": f"当前窗口告警 {recent.get('total', 0)} 条，环比窗口告警 {previous.get('total', 0)} 条，差值 {comparison.get('deltaTotal', 0)} 条。",
        },
        {
            "stage": "metric-analysis",
            "summary": f"根资源关键指标数 {len(metric_analysis.get('metricDataResults') or [])} 个。",
        },
    ]
    return {
        "summary": summary,
        "rootCause": root_cause,
        "steps": steps,
        "logEntries": log_entries,
        "actions": [
            {
                "type": "alarm-analyst-context",
                "context": context,
            }
        ],
    }


def _run_alarm_analyst_context(payload: dict) -> dict:
    script_path = _alarm_analyst_context_script()
    if not script_path.exists():
        raise FileNotFoundError(f"alarm-analyst context script not found: {script_path}")

    dispatch_context = _parse_alarm_dispatch_context(payload.get("content"))
    res_id = dispatch_context.get("res_id", "")
    if not res_id:
        raise ValueError("missing resId in fault scenario content")

    command_args = [
        sys.executable,
        str(script_path),
        "--res-id",
        res_id,
        "--output",
        "json",
    ]
    if dispatch_context.get("alarm_title"):
        command_args.extend(["--alarm-title", dispatch_context["alarm_title"]])
    if dispatch_context.get("device_name"):
        command_args.extend(["--device-name", dispatch_context["device_name"]])
    if dispatch_context.get("manage_ip"):
        command_args.extend(["--manage-ip", dispatch_context["manage_ip"]])
    if dispatch_context.get("event_time"):
        command_args.extend(["--event-time", dispatch_context["event_time"]])

    completed = subprocess.run(
        command_args,
        cwd=str(_alarm_analyst_skill_root()),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=ALARM_ANALYST_SCRIPT_TIMEOUT_SECONDS,
        check=False,
    )
    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    if completed.returncode != 0 and not stdout_text:
        raise RuntimeError(stderr_text or "alarm-analyst context query failed")
    if not stdout_text:
        raise RuntimeError("alarm-analyst context query returned empty output")

    context = json.loads(stdout_text)
    if context.get("code") != 200:
        raise RuntimeError(str(context.get("msg") or "alarm-analyst context query failed"))
    return _build_alarm_analyst_result(context, dispatch_context)


def run_fault_scenario_diagnose(payload: dict) -> dict:
    session_id = str(payload.get("sessionId") or "").strip()
    if not session_id:
        raise ValueError("sessionId is required")

    detection = detect_fault_scenario(
        employee_id=str(payload.get("employeeId") or "fault"),
        content=payload.get("content"),
    )
    if not detection.triggered:
        raise ValueError("unsupported fault scenario")

    try:
        result = _run_alarm_analyst_context(payload)
    except ValueError:
        result = parse_fault_scenario_output(
            json.dumps(
                {
                    "summary": "已建立场景根因分析脚手架，但当前消息未包含可执行的资源 ID。",
                    "rootCause": {"type": "待分析", "object": "cmdb_device"},
                    "steps": [
                        {"id": "database-analysis", "status": "scaffolded"},
                        {"id": "decision-merge", "status": "scaffolded"},
                    ],
                    "logEntries": [
                        {
                            "stage": "database-analysis",
                            "summary": "未从当前消息中解析出资源 ID，暂时无法执行完整的 alarm-analyst 聚合链路。",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )

    return {
        "session": {
            "sessionId": session_id,
            "scene": detection.scene_code,
        },
        "result": result,
    }
