"""Portal model-only chat: no agent, tool callbacks, or business dispatch."""
from __future__ import annotations

from contextlib import aclosing
from uuid import uuid4

from agentscope.message import Msg, TextBlock

from ...extensions.security.output_guard import load_config, redact
from .stopped_turn import _load, _save
from .text_continuation import _sse
from .title_generator import _extract_text_from_response

_SYSTEM = (
    "你处在业务联网已关闭的纯文本对话模式。你没有工具，不能联网检索、调用业务接口、"
    "使用 MCP、读取知识库或执行操作。若用户要求做这些事，直接告知本轮未执行实时查询或操作，"
    "不要把已有聊天信息描述为新查询的结果。其他问题正常回答。"
)


async def stream_model_only(workspace, chat, turn_id: str, question: str):
    from ...agents.model_factory import create_model_and_formatter

    snapshot, state = await _load(workspace.session, chat)
    # Reuse conversational text only. Never pass tool call/result or media
    # blocks to the configured model, including when reopening a prior chat.
    context = []
    for message in state.context[-8:]:
        if message.role not in {"user", "assistant"} or message.metadata.get("qwenpaw_tag"):
            continue
        if text := message.get_text_content():
            context.append(Msg(name=message.role, role=message.role, content=[TextBlock(text=text[:1_500])]))
    incoming = Msg(id=turn_id, name="user", role="user", content=[TextBlock(text=question)])
    model, _ = create_model_and_formatter(agent_id=workspace.agent_id)
    event = {"object": "message", "id": uuid4().hex, "role": "assistant", "type": "message", "portal_model_only": True}
    yield _sse({**event, "status": "in_progress", "content": []})
    reply = await model([
        Msg(name="system", role="system", content=[TextBlock(text=_SYSTEM)]),
        *context, incoming,
    ])
    guard = load_config()
    raw = displayed = ""
    if hasattr(reply, "__aiter__"):
        async with aclosing(reply) as chunks:
            async for chunk in chunks:
                text = _extract_text_from_response(chunk)
                if not text:
                    continue
                raw = text
                current = redact(raw, cfg=guard, streaming_tail_guard=True)[0] if guard.active else raw
                if current and current != displayed:
                    yield _sse({"object": "content", "type": "text", "msg_id": event["id"],
                                "delta": False, "text": current, "portal_model_only": True})
                    displayed = current
    else:
        raw = _extract_text_from_response(reply)
    text = redact(raw, cfg=guard)[0] if guard.active else raw
    if not text.strip():
        yield _sse({"error": "本轮未生成可显示的文字。"})
        return
    state.context.extend((incoming, Msg(name="assistant", role="assistant", content=[TextBlock(text=text)],
                                        metadata={"portal_model_only": True})))
    await _save(workspace.session, chat, snapshot, state)
    yield _sse({**event, "status": "completed", "content": [{"type": "text", "text": text}]})
    yield _sse({"object": "response", "status": "completed"})
