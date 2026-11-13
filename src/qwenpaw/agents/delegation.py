# -*- coding: utf-8 -*-
"""Track submitted peer tasks and collect results before ending a turn."""

from __future__ import annotations

import asyncio
import re
from typing import Any


def field(block: Any, key: str, default=None):
    return (
        block.get(key, default)
        if isinstance(block, dict)
        else getattr(block, key, default)
    )


def result_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return "\n".join(str(field(b, "text", "") or "") for b in output)
    return str(field(output, "text", "") or "")


def is_active_task_poll(name: str, output: Any) -> bool:
    return name == "check_agent_task" and bool(
        re.search(
            r"\[STATUS:\s*(?:running|pending|submitted)\s*\]",
            result_text(output),
        )
    )


def pending_agent_tasks(context: list) -> set[str]:
    calls = {}
    pending: set[str] = set()
    for msg in context:
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            kind = field(block, "type")
            cid = field(block, "id")
            if kind == "tool_call":
                calls[cid] = field(block, "name")
            elif kind == "tool_result":
                name = calls.get(cid) or field(block, "name")
                text = result_text(field(block, "output"))
                match = re.search(r"\[TASK_ID:\s*(task-[\w-]+)\s*\]", text)
                if not match:
                    continue
                task_id = match[1]
                if name == "submit_to_agent":
                    pending.add(task_id)
                elif (
                    name == "check_agent_task" and "[STATUS: finished]" in text
                ):
                    pending.discard(task_id)
    return pending


async def collect_agent_tasks(task_ids: set[str], timeout: float = 60) -> str:
    """Bounded, cancellable waiting; credentials flow through ContextVars."""
    from .tools.agent_management import (
        get_agent_chat_task_status,
        format_background_status_text,
    )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async def collect(task_id):
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return (
                    f"[TASK_ID: {task_id}]\n等待超时，本轮尚未取得最终结果。"
                )
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        get_agent_chat_task_status,
                        None,
                        task_id,
                        timeout=min(10, remaining),
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return (
                    f"[TASK_ID: {task_id}]\n等待超时，本轮尚未取得最终结果。"
                )
            except Exception:
                return f"[TASK_ID: {task_id}]\n任务状态读取失败，本轮未取得最终结果。"
            if result.get("status") not in {"running", "pending", "submitted"}:
                return format_background_status_text(task_id, result)
            await asyncio.sleep(min(2, max(0, deadline - loop.time())))

    results = await asyncio.gather(*(collect(t) for t in sorted(task_ids)))
    return (
        "<system-hint>结束本轮前已核对协同任务，以下为实际结果。请结合结果回答；"
        "未完成或读取失败的任务须明确说明，不得声称已完成或承诺会自动补充。\n"
        + "\n\n".join(r[:32000] for r in results)
        + "\n</system-hint>"
    )
