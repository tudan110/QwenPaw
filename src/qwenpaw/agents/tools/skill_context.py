"""Create bounded JSON inputs for bundled skills without general writes."""

import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import uuid

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...runtime.tool_registry import tool_descriptor

_MAX_BYTES = 256 * 1024


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON 不支持 {value}")


def _write_context(content: str, workspace: Path) -> dict:
    from ...extensions.security.execution_policy import (
        check_path,
        check_search_path,
    )

    if not isinstance(content, str):
        raise ValueError("content 必须是 JSON 字符串")
    if len(content.encode("utf-8")) > _MAX_BYTES:
        raise ValueError("JSON 内容不能超过 256 KiB")
    value = json.loads(content, parse_constant=_reject_constant)
    if not isinstance(value, (dict, list)):
        raise ValueError("JSON 顶层必须是对象或数组")
    payload = (
        json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(payload) > _MAX_BYTES:
        raise ValueError("序列化后的 JSON 不能超过 256 KiB")

    workspace = Path(workspace).expanduser().resolve(strict=True)
    output_dir = workspace / "artifacts" / "skill-context"
    path = output_dir / f"{uuid.uuid4().hex}.json"
    for candidate in (workspace, output_dir, path):
        check_search_path(str(candidate))
        check_path(str(candidate))

    # Directory-relative opens keep symlink replacements from redirecting a
    # checked path. No user-supplied path, file name or overwrite is accepted.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        parent_fd = os.open(workspace, directory_flags)
        stack.callback(os.close, parent_fd)
        for name in ("artifacts", "skill-context"):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            stack.callback(os.close, parent_fd)
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
        except BaseException:
            os.unlink(path.name, dir_fd=parent_fd)
            raise
    return {"file_path": str(path), "size_bytes": len(payload)}


@tool_descriptor(requires_sandbox=("file_write",), async_execution=True)
async def write_skill_context(content: str) -> ToolChunk:
    """Create a JSON input file for a bundled skill in the active workspace.

    Use instead of write_file or shell redirection when a skill needs a
    context/payload JSON file. This only prepares data; it does not approve
    or execute the skill's business action. Pass the returned file_path to
    the skill's documented input argument. Files are new UUID.json entries
    under artifacts/skill-context; paths and overwrites cannot be specified.

    Args:
        content: Valid JSON object or array as a string, at most 256 KiB
            both before and after serialization. Content is never executed.
    """
    from ...config.context import get_current_workspace_dir
    from ...constant import WORKING_DIR

    try:
        result = await asyncio.to_thread(
            _write_context,
            content,
            get_current_workspace_dir() or WORKING_DIR,
        )
    except (ValueError, OSError, RecursionError) as exc:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[TextBlock(text=f"技能上下文生成失败：{exc}")],
        )
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(text=json.dumps(result, ensure_ascii=False))],
    )
