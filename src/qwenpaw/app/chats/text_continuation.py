"""Continue a Portal text draft without invoking the agent or its tools."""
from __future__ import annotations

import json
from contextlib import aclosing

from agentscope.message import Msg, TextBlock

from ...extensions.security.output_guard import load_config, redact
from .title_generator import _extract_text_from_response

_SYSTEM = (
    "Continue the interrupted assistant draft in the user's language. "
    "The JSON contains the original question and the exact text already shown. "
    "Output only the missing continuation, starting exactly where the draft ends; "
    "do not repeat it or add a preamble. Only generate text. Do not claim to have "
    "run a tool, queried live data, or completed any business operation."
)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _continuation(text: str, draft: str) -> str:
    # Do not show the same passage twice if the provider echoes the prefix.
    if draft.startswith(text):
        return ""
    return text.removeprefix(draft)


async def stream_text_continuation(agent_id: str, question: str, draft: str):
    from ...agents.model_factory import create_model_and_formatter

    model, _ = create_model_and_formatter(agent_id=agent_id)
    guard = load_config()
    checkpoint = json.dumps({"question": question, "draft": draft}, ensure_ascii=False)
    response = await model([
        Msg(name="system", role="system", content=[TextBlock(text=_SYSTEM)]),
        Msg(name="user", role="user", content=[TextBlock(text=checkpoint)]),
    ])

    raw_text = ""
    displayed = ""
    if hasattr(response, "__aiter__"):
        async with aclosing(response) as chunks:
            async for chunk in chunks:
                value = _extract_text_from_response(chunk)
                if not value:
                    continue
                raw_text = _continuation(value, draft)
                # Chat providers emit cumulative text. Redact the full
                # snapshot so secrets split across tokens are handled.
                current = raw_text
                if guard.active and guard.mask_streaming:
                    current, _ = redact(current, cfg=guard, streaming_tail_guard=True)
                if current and current != displayed:
                    displayed = current
                    yield _sse({"object": "text_continuation", "text": current})
    else:
        raw_text = _continuation(_extract_text_from_response(response), draft)

    if guard.active:
        raw_text, _ = redact(raw_text, cfg=guard)
    if not raw_text.strip():
        yield _sse({"error": "本次未生成续写内容，请重试。"})
        return
    if raw_text != displayed:
        yield _sse({"object": "text_continuation", "text": raw_text})
    yield _sse({"object": "text_continuation", "status": "completed"})
