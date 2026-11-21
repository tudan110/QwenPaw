"""Prepare a Portal confirmation link for a structured alarm query."""
from urllib.parse import urlencode

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk
from pydantic import ValidationError

from ...runtime.tool_registry import tool_descriptor


@tool_descriptor(async_execution=True)
async def prepare_alarm_export(
    begin_time: str,
    end_time: str,
    is_clear: str,
    severity: str = "1,2,3,4",
    keyword: str = "",
    manage_ip: str = "",
    resource_type: str = "",
) -> ToolChunk:
    """Prepare a confirmation link, not a file, for exporting alarm rows.

    Use only when the user asks to export alarm details. Copy the exact
    scope of the completed query; never guess or omit a filter. If filters
    cannot be represented, explain that the exact export is unsupported.
    Return the Markdown link verbatim. Do not use any other export tool for
    these alarm rows or split requests to bypass the limit.

    Args:
        begin_time: Actual INOE beginTime, YYYY-MM-DD HH:MM:SS.
        end_time: Actual INOE endTime, YYYY-MM-DD HH:MM:SS.
        is_clear: Actual filter: 0 active or 1 cleared.
        severity: Comma-separated INOE severity values, e.g. 1,2.
        keyword: Exact queryKey if used.
        manage_ip: Exact neIp if used.
        resource_type: Exact alarmClassType if used.
    """
    from ...extensions.api.alarm_export import LiveSelection

    try:
        selection = LiveSelection(
            source="live", begin_time=begin_time, end_time=end_time, is_clear=is_clear,
            severity=severity, keyword=keyword, manage_ip=manage_ip, resource_type=resource_type,
        )
    except ValidationError:
        return ToolChunk(is_last=True, state=ToolResultState.ERROR, content=[
            TextBlock(text="未生成导出入口：需要已核实的时间范围和筛选条件。"),
        ])
    href = "/api/portal/alarm-export/preview?" + urlencode(selection.model_dump())
    return ToolChunk(is_last=True, state=ToolResultState.SUCCESS, content=[
        TextBlock(text=f"[预览并确认导出告警明细]({href})"),
    ])
