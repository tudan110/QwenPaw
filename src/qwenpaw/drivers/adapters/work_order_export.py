"""Prepare work-order exports through the existing authorized Driver."""
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


def _page_payload(value: Any) -> dict:
    if getattr(value, "isError", False):
        return {}
    if hasattr(value, "isError"):
        payload = _object(getattr(value, "structuredContent", None))
        if not payload:
            content = getattr(value, "content", None)
            if not content or len(content) != 1:
                return {}
            payload = _object(getattr(content[0], "text", None))
    else:
        payload = _object(value)
    if set(payload) == {"result"}:
        payload = _object(payload["result"])
    if payload.get("ok") is False or payload.get("success") is False:
        return {}
    if "code" in payload and str(payload["code"]) != "200":
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def upstream_work_order_total(value: Any) -> int | None:
    """Accept an explicit total from a successful, structured list response."""
    page = _page_payload(value)
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


def _rows(page: dict) -> list[dict]:
    candidates = [page[key] for key in ("rows", "data", "items", "records", "list")
                  if isinstance(page.get(key), list)]
    if len(candidates) != 1 or not all(isinstance(row, dict) for row in candidates[0]):
        raise HTTPException(502, "工单服务未返回可核验的明细，未导出文件。")
    return candidates[0]


def _page_number(page: dict, *keys: str) -> int | None:
    for key in keys:
        value = page.get(key)
        if type(value) is int and 0 < value <= 10000:
            return value
        if isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < len(value) <= 5:
            return int(value) or None
    return None


async def _complete_rows(query, params: dict, first, count: int) -> list[dict]:
    """Allow only bounded server pagination with a stable total and unique row IDs."""
    first_page = _page_payload(first)
    rows = list(_rows(first_page))
    if _page_number(first_page, "page", "pageNum") not in {None, 1}:
        raise HTTPException(409, "工单查询页码不一致，未导出文件。")
    if len(rows) < count:
        size = _page_number(first_page, "per_page", "pageSize", "page_size")
        if size != len(rows) or not size or (count + size - 1) // size > 20:
            raise HTTPException(502, "工单服务未返回可核验的完整分页，未导出文件。")
        for number in range(2, (count + size - 1) // size + 1):
            page = await query({**params, "page": number, "per_page": size})
            payload = _page_payload(page)
            batch = _rows(payload)
            if (upstream_work_order_total(page) != count
                    or _page_number(payload, "page", "pageNum") != number
                    or _page_number(payload, "per_page", "pageSize", "page_size") not in {None, size}
                    or len(batch) != min(size, count - len(rows))):
                raise HTTPException(409, "工单范围或分页已变化，请重新发起导出。")
            rows.extend(batch)
    identities = set()
    for row in rows:
        identity = row.get("id") or row.get("workOrderId")
        if type(identity) not in {int, str} or not str(identity).strip() or str(identity) in identities:
            raise HTTPException(409, "工单明细缺少有效标识或出现重复，未导出文件。")
        identities.add(str(identity))
    return rows


async def preflight(
    invoker: Callable[[DriverInvocation], Awaitable[DriverInvocationResult]],
    capability_id: str,
    context: dict[str, str],
    filters: dict,
    *,
    page_size_cap: int | None = None,
) -> tuple[ToolResultState, TextBlock]:
    """Stage the verified snapshot without sending any original rows to the model."""
    from ...extensions.api.work_order_export import prepare, verify_actor_scope

    try:
        params = _first_page(filters)
    except ValueError:
        return ToolResultState.ERROR, TextBlock(text="当前仅支持按待办、已办及其时间范围导出。请确认筛选条件。")

    async def query(payload):
        result = await invoker(DriverInvocation(capability_id, payload, context))
        if not result.ok:
            if result.error_type in {"permission_denied", "driver_policy_denied", "driver_policy_approval_required"}:
                raise HTTPException(403, "当前未获授权查询此工单范围，未导出文件。")
            raise HTTPException(502, "暂时无法读取工单服务，未导出文件。")
        return result.value

    try:
        await asyncio.to_thread(require_agent_tool, WORK_ORDER_EXPORT_TOOL)
        scope_agent = verify_actor_scope(context)
        limit = await asyncio.to_thread(alarm_export.work_order_limit)
        # A single bounded request normally provides both the authoritative count
        # and all admissible rows, without two separate consent prompts.
        params["per_page"] = min(limit, page_size_cap or limit)
        first = await query(params)
        count = upstream_work_order_total(first)
        if count is None:
            return ToolResultState.ERROR, TextBlock(text=f"{_UNKNOWN} 当前单次最多导出 {limit} 条。")
        limit, blocked = await asyncio.to_thread(alarm_export.check_work_order_limit, count)
        label = "已办工单" if params["classify"] == 5 else "待办工单"
        summary = f"当前范围匹配 {count} 条{label}，单次最多导出 {limit} 条。"
        if blocked:
            return ToolResultState.DENIED, TextBlock(text=f"已触发导出管控上限：{summary} 本次未导出。")
        if not count:
            return ToolResultState.SUCCESS, TextBlock(text=f"{summary} 当前范围没有可导出的工单，未生成文件。")
        rows = await _complete_rows(query, params, first, count)
        handle, current_limit = await asyncio.to_thread(prepare, filters, rows, scope_agent)
        href = f"/api/portal/work-order-export/preview?intent={handle}"
        return ToolResultState.SUCCESS, TextBlock(text=(
            f"当前范围匹配 {count} 条{label}，单次最多导出 {current_limit} 条。"
            f"请在 5 分钟内点击 [确认导出工单]({href}) 下载 JSON 文件。"
        ))
    except PermissionError:
        return ToolResultState.DENIED, TextBlock(text="当前权限不允许导出工单，未导出文件。")
    except HTTPException as exc:
        state = ToolResultState.DENIED if exc.status_code in {401, 403, 422} else ToolResultState.ERROR
        return state, TextBlock(text=str(exc.detail))
    except (sqlite3.Error, OSError, PolicyUnavailable, ValidationError, ValueError):
        logger.warning("Work-order export could not be prepared")
        return ToolResultState.ERROR, TextBlock(text="无法准备本次工单导出，未导出文件，请稍后重试。")
