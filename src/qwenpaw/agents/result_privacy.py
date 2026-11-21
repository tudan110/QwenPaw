"""Tool result privacy before AgentScope emits deltas or stores results."""
from __future__ import annotations

import asyncio
from contextlib import aclosing

from agentscope.message import TextBlock, ToolResultState
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolChunk, ToolResponse

from ..extensions.api import text_privacy


def _terminal(call_id: str, text: str) -> ToolResponse:
    return ToolResponse(id=call_id, state=ToolResultState.DENIED, content=[TextBlock(text=text)])


def _delta(response: ToolResponse) -> ToolChunk:
    return ToolChunk(
        id=response.id, content=response.content, state=response.state,
        metadata=response.metadata, is_last=True,
    )


class ToolResultPrivacyMiddleware(MiddlewareBase):
    """When blocking is enabled, release only a checked, complete result."""

    async def on_acting(self, agent, input_kwargs, next_handler):
        del agent
        call_id = input_kwargs["tool_call"].id
        try:
            policy = await asyncio.to_thread(text_privacy.load_policy)
        except text_privacy.PrivacyUnavailable as exc:
            response = _terminal(call_id, str(exc))
            yield _delta(response)
            yield response
            return

        block = policy.query_results == "block"
        async with aclosing(next_handler(**input_kwargs)) as events:
            async for event in events:
                if not isinstance(event, ToolResponse):
                    # Never expose an unverified prefix that could be part of a
                    # longer pattern spanning tool deltas.
                    if not block:
                        yield event
                    continue
                if policy.query_results != "off":
                    try:
                        await text_privacy.check(
                            "query_results", event.model_dump(include={"content", "metadata"}),
                            policy=policy,
                        )
                    except text_privacy.PrivacyBlocked as exc:
                        event = _terminal(call_id, str(exc))
                    except (TypeError, ValueError):
                        if block:
                            event = _terminal(call_id, "无法核验业务查询与工具结果，已阻止返回。")
                if block:
                    yield _delta(event)
                yield event
