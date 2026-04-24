#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建人工处置工单。

使用方式:
    python scripts/create_manual_workorder.py \
      --chat-id 82bd7e8c-6940-414b-a59e-aede36f713ad \
      --res-id 3094 \
      --metric-type mysql \
      --alarm-id alarm-001 \
      --alarm-title "数据库锁异常" \
      --visible-content "数据库锁异常（db_mysql_001 10.43.150.186）" \
      --device-name db_mysql_001 \
      --manage-ip 10.43.150.186 \
      --asset-id db_mysql_001 \
      --level critical \
      --status active \
      --event-time "2026-04-20 15:00:00" \
      --analysis-summary "AI 已完成根因分析，自动创建人工处置工单" \
      --root-cause "疑似 MySQL 锁等待 / 长事务 / 死锁" \
      --suggestion "排查长事务" \
      --suggestion "检查阻塞链" \
      --suggestion "确认是否存在热点更新" \
      --output markdown
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_TICKET_PRIORITY = "P1"
DEFAULT_TICKET_CATEGORY = "database-lock"
DEFAULT_TICKET_SOURCE = "portal-fault-disposal-ai"
DEFAULT_EXTERNAL_SYSTEM = "manual-workorder"
ALLOWED_OUTPUTS = {"json", "markdown"}


def _load_skill_env() -> None:
    if not HAS_DOTENV:
        return

    skill_dir = Path(__file__).resolve().parents[1]
    skill_env_file = skill_dir / ".env"
    if skill_env_file.exists():
        load_dotenv(skill_env_file, override=True)


_load_skill_env()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_base_url(api_base_url: str | None) -> str:
    base_url = (api_base_url or os.getenv("INOE_API_BASE_URL") or "").strip()
    if not base_url:
        raise ValueError("未设置 INOE_API_BASE_URL，请检查 skills/alarm-analyst/.env")
    return base_url.rstrip("/")


def _get_token(token: str | None) -> str:
    normalized_token = _safe_str(token or os.getenv("INOE_API_TOKEN"))
    if not normalized_token:
        raise ValueError("未设置 INOE_API_TOKEN，请检查 skills/alarm-analyst/.env")
    return normalized_token


def _get_timeout(timeout_seconds: int | None) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    raw = _safe_str(os.getenv("ALARM_ANALYST_METRIC_TIMEOUT_SECONDS"))
    return int(raw) if raw else DEFAULT_TIMEOUT_SECONDS


def _build_serial_no() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
    suffix = f"{random.randint(0, 99999):05d}"
    return f"{timestamp}{suffix}"


def _normalize_suggestions(
    suggestions: list[str] | None = None,
    suggestions_json: str | None = None,
) -> list[str]:
    normalized = [_safe_str(item) for item in suggestions or [] if _safe_str(item)]
    if suggestions_json:
        try:
            parsed = json.loads(suggestions_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--suggestions-json 不是合法 JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("--suggestions-json 必须是字符串数组")
        normalized.extend(_safe_str(item) for item in parsed if _safe_str(item))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in normalized:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    if not deduped:
        raise ValueError("至少提供一条处置建议，请使用 --suggestion 或 --suggestions-json")
    return deduped


def _default_ticket_title(alarm_title: str) -> str:
    title = _safe_str(alarm_title) or "故障"
    return f"AI创建 · {title}人工处置"


def _normalize_ai_alarm_title(alarm_title: str) -> str:
    title = _safe_str(alarm_title) or "故障告警"
    title = re.sub(r"^\s*AI\s*创建\s*[·:：-]?\s*", "", title)
    title = re.sub(r"\s*[\(（]\s*AI\s*创建\s*[\)）]\s*$", "", title)
    title = title.strip() or "故障告警"
    return f"{title}（AI创建）"


def _require_alarm_id(alarm_id: str) -> str:
    normalized = _safe_str(alarm_id)
    if not normalized:
        raise ValueError("必须提供告警流水号，请通过 --alarm-id 传入并映射到 alarm.alarmId")
    return normalized


def build_workorder_payload(args: argparse.Namespace) -> dict[str, Any]:
    suggestions = _normalize_suggestions(args.suggestion, args.suggestions_json)
    alarm_id = _require_alarm_id(args.alarm_id)
    alarm_title = _normalize_ai_alarm_title(_safe_str(args.alarm_title))
    analysis_summary = _safe_str(args.analysis_summary) or "AI 已完成根因分析，自动创建人工处置工单"

    return {
        "chatId": _safe_str(args.chat_id),
        "resId": _safe_str(args.res_id),
        "metricType": _safe_str(args.metric_type) or "mysql",
        "alarm": {
            "alarmId": alarm_id,
            "title": alarm_title,
            "visibleContent": _safe_str(args.visible_content),
            "deviceName": _safe_str(args.device_name),
            "manageIp": _safe_str(args.manage_ip),
            "assetId": _safe_str(args.asset_id),
            "level": _safe_str(args.level),
            "status": _safe_str(args.status),
            "eventTime": _safe_str(args.event_time),
        },
        "analysis": {
            "summary": analysis_summary,
            "rootCause": _safe_str(args.root_cause),
            "suggestions": suggestions,
        },
        "ticket": {
            "title": _safe_str(args.ticket_title) or _default_ticket_title(alarm_title),
            "priority": _safe_str(args.ticket_priority) or DEFAULT_TICKET_PRIORITY,
            "category": _safe_str(args.ticket_category) or DEFAULT_TICKET_CATEGORY,
            "source": _safe_str(args.ticket_source) or DEFAULT_TICKET_SOURCE,
            "externalSystem": _safe_str(args.ticket_external_system) or DEFAULT_EXTERNAL_SYSTEM,
        },
    }


def _should_fallback_to_curl(error: Exception) -> bool:
    return isinstance(error, (requests.RequestException, OSError))


def _curl_post_json(
    *,
    url: str,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as body_file:
        body_file.write(json.dumps(json_payload, ensure_ascii=False).encode("utf-8"))
        body_path = body_file.name

    try:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            str(timeout_seconds),
            url,
            "--header",
            f"Content-Type: {headers['Content-Type']}",
            "--header",
            f"SerialNo: {headers['SerialNo']}",
            "--header",
            f"Authorization: {headers['Authorization']}",
            "--data",
            f"@{body_path}",
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass

    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"工单接口返回了非 JSON 内容: {completed.stdout}") from exc


def create_manual_workorder(
    payload: dict[str, Any],
    *,
    api_base_url: str | None = None,
    token: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    base_url = _normalize_base_url(api_base_url)
    auth_token = _get_token(token)
    timeout = _get_timeout(timeout_seconds)
    url = f"{base_url}/flowable/workflow/workOrder/faultManualWorkorders"
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "SerialNo": _build_serial_no(),
        "Authorization": auth_token,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        if not _should_fallback_to_curl(exc):
            raise
        data = _curl_post_json(
            url=url,
            headers=headers,
            json_payload=payload,
            timeout_seconds=timeout,
        )

    if not isinstance(data, dict):
        raise RuntimeError(f"工单接口返回格式异常: {data!r}")
    code = data.get("code")
    if code != 200:
        raise RuntimeError(
            f"工单创建失败: code={code}, msg={data.get('msg') or 'unknown'}"
        )
    return data


def format_markdown_result(payload: dict[str, Any], response: dict[str, Any]) -> str:
    ticket = payload.get("ticket") or {}
    analysis = payload.get("analysis") or {}
    alarm = payload.get("alarm") or {}
    data = response.get("data") or {}
    suggestions = analysis.get("suggestions") or []

    lines = [
        "## AI 创建处置工单结果",
        f"- 工单标题：{ticket.get('title') or '-'}",
        f"- 工单来源：{ticket.get('source') or '-'}",
        f"- 告警流水号：`{alarm.get('alarmId') or ''}`",
        f"- 告警标题：{alarm.get('title') or '-'}",
        f"- 资源 ID（CI ID）：`{payload.get('resId') or ''}`",
        f"- 分析摘要：{analysis.get('summary') or '-'}",
        f"- 根因方向：{analysis.get('rootCause') or '-'}",
        f"- 处置建议：{'；'.join(str(item) for item in suggestions) if suggestions else '-'}",
        f"- procInsId：`{data.get('procInsId') or ''}`",
        f"- taskId：`{data.get('taskId') or ''}`",
        "- 当前状态：已自动调用 4.2 接口创建工单（AI 创建）",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建人工处置工单")
    parser.add_argument("--chat-id", required=True, help="当前故障会话 ID")
    parser.add_argument("--res-id", required=True, help="CMDB CI ID")
    parser.add_argument("--metric-type", default="mysql", help="资源类型，例如 mysql")
    parser.add_argument("--alarm-id", required=True, help="告警流水号，对应 alarm.alarmId")
    parser.add_argument("--alarm-title", required=True, help="告警标题")
    parser.add_argument("--visible-content", default="", help="告警可见摘要")
    parser.add_argument("--device-name", default="", help="设备名 / 资源名")
    parser.add_argument("--manage-ip", default="", help="管理 IP")
    parser.add_argument("--asset-id", default="", help="资产编号")
    parser.add_argument("--level", default="", help="告警级别")
    parser.add_argument("--status", default="active", help="告警状态")
    parser.add_argument("--event-time", default="", help="告警时间")
    parser.add_argument("--analysis-summary", default="", help="AI 分析摘要")
    parser.add_argument("--root-cause", default="", help="根因方向")
    parser.add_argument(
        "--suggestion",
        action="append",
        default=[],
        help="处置建议，可重复传入多次",
    )
    parser.add_argument(
        "--suggestions-json",
        default="",
        help='JSON 数组格式的处置建议，例如 ["排查长事务","检查阻塞链"]',
    )
    parser.add_argument("--ticket-title", default="", help="工单标题")
    parser.add_argument("--ticket-priority", default=DEFAULT_TICKET_PRIORITY, help="工单优先级")
    parser.add_argument("--ticket-category", default=DEFAULT_TICKET_CATEGORY, help="工单分类")
    parser.add_argument("--ticket-source", default=DEFAULT_TICKET_SOURCE, help="工单来源")
    parser.add_argument(
        "--ticket-external-system",
        default=DEFAULT_EXTERNAL_SYSTEM,
        help="外部工单系统标识",
    )
    parser.add_argument("--api-base-url", default="", help="工单接口基础地址")
    parser.add_argument("--token", default="", help="工单接口 Authorization")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="请求超时秒数")
    parser.add_argument("--output", choices=sorted(ALLOWED_OUTPUTS), default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = build_workorder_payload(args)
        response = create_manual_workorder(
            payload,
            api_base_url=args.api_base_url,
            token=args.token,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(
            json.dumps(
                {
                    "request": payload,
                    "response": response,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_markdown_result(payload, response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
