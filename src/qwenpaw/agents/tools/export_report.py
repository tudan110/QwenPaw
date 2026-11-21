# -*- coding: utf-8 -*-
"""Export conversation text through the fixed document renderer."""

import asyncio
import logging
from urllib.parse import quote

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


@tool_descriptor(requires_sandbox=("file_write",), async_execution=True)
async def export_report(
    content: str,
    title: str = "报告",
    format: str = "pdf",
) -> ToolChunk:
    """Generate a downloadable PDF, Word or Markdown report.

    Use when the user explicitly requests a file/download/export. Pass the
    full report text directly; no temporary script or shell command is
    needed, including in production mode. PDF is the default. For Word use
    docx; use md only when Markdown is requested. Return the download link
    verbatim. Do not silently substitute a different format on failure.
    Do not use for bulk alarm detail export, even if the user requests a
    particular format. Use prepare_alarm_export and return its confirmation
    link; do not work around an export limit by embedding rows in a report.

    Args:
        content: Full report text, with basic Markdown headings/tables.
        title: Short report title, not a file path.
        format: Output format: pdf (default), docx (Word), or md.

    Returns:
        ToolChunk: Download link on success, otherwise an explicit error.
    """
    from ...app.agent_context import get_current_agent_id
    from ...extensions import runtime_data_paths
    from ...extensions.report_export import export_report as render_report

    try:
        agent_id = get_current_agent_id()
        path = await asyncio.to_thread(
            render_report,
            content,
            title,
            format,
            agent_id,
            runtime_data_paths.REPORTS_DATA_DIR,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        logger.warning("Report export failed: %s", exc)
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(text=f"报告导出失败：{exc}")],
        )

    href = (
        f"/api/portal/agents/{quote(agent_id, safe='')}/reports/"
        f"{quote(path.name, safe='')}"
    )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                text=f"[下载报告（{path.suffix[1:].upper()}）]({href})",
            ),
        ],
    )
