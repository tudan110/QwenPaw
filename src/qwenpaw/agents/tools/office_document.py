"""Structured Office processing for production deployments."""

import asyncio
import json

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...runtime.tool_registry import tool_descriptor


@tool_descriptor(
    requires_sandbox=("file_read", "file_write"), async_execution=True
)
async def process_office_document(
    operation: str,
    file_path: str = "",
    rows: list[list] | None = None,
    updates: list[dict] | None = None,
    replacements: list[dict] | None = None,
    content: str = "",
) -> ToolChunk:
    """Read or create safe Office artifacts without Python/shell scripts.

    Input files must be inside the active workspace. Writes always create a
    new file under artifacts/office; pass its returned file_path to
    send_file_to_user. Macros and external links are rejected. Inspection
    returns existing formulas as text without calculating them; creation and
    editing accept plain values only. Source documents are never modified.

    Args:
        operation: inspect (docx/xlsx/pptx), create_xlsx, create_docx,
            edit_xlsx, replace_text (docx/pptx), or export_pdf. PDF export
            rearranges extracted text and does not preserve original layout.
        file_path: Existing workspace file, required except for create_*.
        rows: Rows of plain cell values for create_xlsx.
        updates: For edit_xlsx, objects with sheet, cell (e.g. A1), value.
        replacements: For replace_text, objects with find and replace.
            Matches within individual text fragments, preserving other XML.
        content: Markdown/plain text for create_docx. For downloadable
            reports, prefer export_report which defaults to PDF.
    """
    from ...config.context import get_current_workspace_dir
    from ...constant import WORKING_DIR
    from ...extensions.office_documents import process_document

    try:
        result = await asyncio.to_thread(
            process_document,
            get_current_workspace_dir() or WORKING_DIR,
            operation,
            file_path,
            rows=rows,
            updates=updates,
            replacements=replacements,
            content=content,
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    text=json.dumps(result, ensure_ascii=False, default=str)
                )
            ],
        )
    except Exception as exc:  # A malformed package must produce a tool error.
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(text=f"Office 文件处理失败：{exc}")],
        )
