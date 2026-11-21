"""Count-only work-order export preflight on the existing authorized Driver."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from fastapi import HTTPException
from pydantic import ValidationError

from ...extensions.api import alarm_export
from ...extensions.security.call_admission import PolicyUnavailable, require_agent_tool
from ..capabilities import DriverInvocation, DriverInvocationResult

logger = logging.getLogger(__name__)
WORK_ORDER_EXPORT_TOOL = "check_work_order_export"
_QUERY_FIELDS = {"classify", "startTime", "endTime"}
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_UNKNOWN = "未导出文件：无法核实此范围的工单总数，不能判断是否超限。"


def _object(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def upstream_work_order_total(value: Any) -> int | None:
    """Accept an explicit total from a successful, structured list response."""
    if getattr(value, "isError", False):
        return None
    if hasattr(value, "isError"):
        payload = _object(getattr(value, "structuredContent", None))
        if not payload:
            content = getattr(value, "content", None)
            if not content or len(content) != 1:
                return None
            payload = _object(getattr(content[0], "text", None))
    else:
        payload = _object(value)
    if set(payload) == {"result"}:
        payload = _object(payload["result"])
    if payload.get("ok") is False or payload.get("success") is False:
        return None
    if "code" in payload and str(payload["code"]) != "200":
        return None
    data = payload.get("data")
    page = data if isinstance(data, dict) else payload
    totals = [
        page[key] for key in ("total_count", "total", "totalCount") if key in page
    ]
    parsed: set[int] = set()
    for total in totals:
        # Do not infer a total from rows, fuzzy text, booleans or floats.
        if type(total) is int and 0 <= total <= 2**63 - 1:
            parsed.add(total)
        elif (
            isinstance(total, str) and total.isascii()
            and total.isdecimal() and len(total) <= 18
        ):
            parsed.add(int(total))
        else:
            return None
    if len(parsed) != 1:
        return None
    count = parsed.pop()
    for key in ("rows", "data", "items", "records", "list"):
        rows = page.get(key)
        if isinstance(rows, list) and len(rows) > count:
            return None
    return count


def _first_page(filters: dict) -> dict:
    if (
        filters.keys() - _QUERY_FIELDS
        or type(filters.get("classify")) is not int
        or filters["classify"] not in {1, 5}
    ):
        raise ValueError
    params = {"classify": filters["classify"], "page": 1, "per_page": 1}
    for key in ("startTime", "endTime"):
        if key in filters:
            text = filters[key]
            if (
                not isinstance(text, str)
                or len(text) != 19
                or datetime.strptime(text, _TIME_FORMAT).strftime(_TIME_FORMAT) != text
            ):
                raise ValueError
            params[key] = text
    if (
        "startTime" in params and "endTime" in params
        and params["startTime"] > params["endTime"]
    ):
        raise ValueError
    return params


async def preflight(
    invoker: Callable[[DriverInvocation], Awaitable[DriverInvocationResult]],
    capability_id: str,
    context: dict[str, str],
    filters: dict,
) -> tuple[ToolResultState, TextBlock]:
    """Bind the count to the real query scope and return no original records."""

    state, text = ToolResultState.ERROR, _UNKNOWN
    try:
        params = _first_page(filters)
    except ValueError:
        return state, TextBlock(text="未导出文件：当前仅能核验待办、已办及其时间范围。请确认筛选条件。")
    try:
        require_agent_tool(WORK_ORDER_EXPORT_TOOL)
        limit = await asyncio.to_thread(alarm_export.work_order_limit)
    except PermissionError:
        return ToolResultState.DENIED, TextBlock(text="当前权限不允许核验工单导出，未导出文件。")
    except HTTPException as exc:
        return ToolResultState.DENIED, TextBlock(text=f"{exc.detail}，未导出文件。")
    except (sqlite3.Error, OSError, PolicyUnavailable, ValidationError):
        return state, TextBlock(text="无法读取当前导出管控上限，未导出文件。")

    text = f"{_UNKNOWN} 当前单次最多导出 {limit} 条。"
    try:
        result = await invoker(DriverInvocation(capability_id, params, context))
        if not result.ok:
            if result.error_type in {
                "permission_denied", "driver_policy_denied", "driver_policy_approval_required",
            }:
                return ToolResultState.DENIED, TextBlock(text="当前未获授权查询此工单范围，无法核验导出，未导出文件。")
            return state, TextBlock(text=text)
        count = upstream_work_order_total(result.value)
        if count is not None:
            limit, blocked = await asyncio.to_thread(alarm_export.check_work_order_limit, count)
            label = "已办工单" if params["classify"] == 5 else "待办工单"
            summary = f"当前范围匹配 {count} 条{label}，单次最多导出 {limit} 条。"
            if blocked:
                state = ToolResultState.DENIED
                text = f"已触发导出管控上限：{summary} 本次未导出。"
            elif count == 0:
                state = ToolResultState.SUCCESS
                text = f"{summary} 当前范围没有可导出的工单，未生成文件。"
            else:
                state = ToolResultState.SUCCESS
                text = f"{summary} 本次未超限，但智观AI暂不支持工单文件下载，未生成文件。"
    except (sqlite3.Error, OSError, ValidationError, HTTPException):
        # Includes transport/storage failures; never substitute a guessed total.
        logger.warning("Work-order export preflight could not be verified")
        text = "无法完成工单导出核验，未导出文件。"
    return state, TextBlock(text=text)
