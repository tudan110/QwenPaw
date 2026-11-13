# -*- coding: utf-8 -*-
"""Fault policy is system context; the persisted user input remains intact."""

from types import SimpleNamespace
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from agentscope.agent import Agent
from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatModelBase
from agentscope.tool import Toolkit

from qwenpaw.extensions.runtime.manual_fault_guidance import (
    MANUAL_FAULT_GUIDANCE_INSTRUCTIONS,
    ManualFaultGuidanceHook,
)
from qwenpaw.runtime.hooks import HookContext
from qwenpaw.runtime.runtime import Runtime


class ExistingPromptMiddleware(MiddlewareBase):
    async def on_system_prompt(self, agent, current_prompt):
        return current_prompt + "\nexisting-prompt-middleware"


def context(channel="console", enabled=True):
    user = Msg(
        name="user", role="user", content=[TextBlock(text="帮我定位和解决")]
    )
    ctx = HookContext(
        request=SimpleNamespace(
            channel=channel,
            request_context={"portal_manual_fault_guidance": enabled},
        ),
        session_id="session",
        agent_id="fault",
        root_session_id="session",
        root_agent_id="gateway",
        workspace_dir=None,
        workspace=None,
        app_services=None,
        input_msgs=[user],
    )
    ctx.agent = Agent(
        name="fault",
        system_prompt="base-system-prompt",
        model=MagicMock(spec=ChatModelBase),
        toolkit=Toolkit(tools=[]),
        middlewares=[ExistingPromptMiddleware()],
    )
    return ctx


async def test_policy_is_injected_as_system_not_appended_to_user():
    ctx = context()
    original = ctx.input_msgs[0]
    await ManualFaultGuidanceHook().run(ctx)
    await ManualFaultGuidanceHook().run(ctx)
    Runtime._apply_context_injections(ctx)
    assert ctx.input_msgs == [original]
    assert ctx.context_injections == []
    assert original.get_text_content() == "帮我定位和解决"
    assert ctx.request.request_context == {
        "portal_manual_fault_guidance": True
    }
    # Exercise the installed SDK's real input validation and preparation,
    # rather than only asserting an intermediate runtime representation.
    await ctx.agent._handle_incoming_messages(ctx.input_msgs)
    model_input = await ctx.agent._prepare_model_input()
    messages = model_input["messages"]
    assert messages[0].role == "system"
    system = messages[0].get_text_content()
    assert system.startswith("base-system-prompt")
    assert system.index("existing-prompt-middleware") < system.index(
        "[CMDB 人工处置指南约束]"
    )
    assert system.count(MANUAL_FAULT_GUIDANCE_INSTRUCTIONS) == 1
    assert all(msg.role != "system" for msg in ctx.agent.state.context)
    assert ctx.agent.state.context[-1].get_text_content() == "帮我定位和解决"
    again = await ctx.agent._prepare_model_input()
    assert again["messages"][0].get_text_content() == system
    other = context(enabled=False)
    await ManualFaultGuidanceHook().run(other)
    await other.agent._handle_incoming_messages(other.input_msgs)
    assert (
        MANUAL_FAULT_GUIDANCE_INSTRUCTIONS
        not in (await other.agent._prepare_model_input())["messages"][
            0
        ].get_text_content()
    )


@pytest.mark.parametrize(
    ("channel", "enabled"),
    [("console", False), ("console", "true"), ("telegram", True)],
)
async def test_policy_is_scoped_to_flagged_console_requests(channel, enabled):
    ctx = context(channel, enabled)
    await ManualFaultGuidanceHook().run(ctx)
    assert ctx.context_injections == []
    assert len(ctx.input_msgs) == 1


async def test_unsupported_agent_api_does_not_silently_drop_policy():
    ctx = context()
    ctx.agent = SimpleNamespace()
    with pytest.raises(RuntimeError, match="middleware is unavailable"):
        await ManualFaultGuidanceHook().run(ctx)


def test_backend_policy_preserves_the_legacy_frontend_requirements():
    root = Path(__file__).resolve().parents[4]
    text = (root / "portal/src/fault-scenario/manualGuidance.ts").read_text()
    instructions = text.split(
        "export const MANUAL_FAULT_GUIDANCE_INSTRUCTIONS = [", 1
    )[1].split('].join("\\n")', 1)[0]
    strings = [
        json.loads(value)
        for value in re.findall(r'"(?:[^"\\]|\\.)*"', instructions)
    ]
    expected = "\n".join(["[CMDB 人工处置指南约束]", *strings])
    assert MANUAL_FAULT_GUIDANCE_INSTRUCTIONS == expected
