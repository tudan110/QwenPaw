# -*- coding: utf-8 -*-
"""Peer task polling, final collection, and cancellation regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents import delegation
from qwenpaw.agents.react_agent import QwenPawAgent
from agentscope.agent import Agent
from agentscope.message import Msg, TextBlock
from qwenpaw.loop.gates import StopHandlerResult
from qwenpaw.agents.tools import agent_management
from qwenpaw.loop.gates.doom_loop import DoomLoopGate


def exchange(name, text, cid="one"):
    return SimpleNamespace(
        role="assistant",
        metadata={},
        content=[
            {"type": "tool_call", "id": cid, "name": name},
            {
                "type": "tool_result",
                "id": cid,
                "name": name,
                "output": [{"type": "text", "text": text}],
            },
        ],
    )


def test_only_submitted_uncollected_tasks_are_pending():
    submitted = exchange("submit_to_agent", "[TASK_ID: task-one]", "a")
    running = exchange(
        "check_agent_task", "[TASK_ID: task-one]\n[STATUS: running]", "b"
    )
    done = exchange(
        "check_agent_task", "[TASK_ID: task-one]\n[STATUS: finished]", "c"
    )
    assert delegation.pending_agent_tasks([submitted, running]) == {"task-one"}
    assert delegation.pending_agent_tasks([submitted, running, done]) == set()
    assert (
        delegation.pending_agent_tasks(
            [exchange("read_file", "[TASK_ID: task-one]")]
        )
        == set()
    )


async def test_collect_waits_for_actual_final_report(monkeypatch):
    results = iter(
        [
            {"status": "running"},
            {
                "status": "finished",
                "result": {
                    "status": "completed",
                    "session_id": "peer",
                    "output": [
                        {
                            "content": [
                                {"type": "text", "text": "已完成的根因报告"}
                            ]
                        }
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(
        agent_management,
        "get_agent_chat_task_status",
        lambda *a, **k: next(results),
    )
    sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _: sleep(0))
    result = await delegation.collect_agent_tasks({"task-one"})
    assert "已完成的根因报告" in result
    assert "[STATUS: finished]" in result


async def test_collection_timeout_is_explicit():
    result = await delegation.collect_agent_tasks({"task-one"}, timeout=0)
    assert "本轮尚未取得最终结果" in result
    assert "不得声称已完成" in result


async def test_collection_can_be_cancelled(monkeypatch):
    started = asyncio.Event()

    async def wait(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio, "to_thread", wait)
    task = asyncio.create_task(delegation.collect_agent_tasks({"task-one"}))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_final_answer_gets_one_collection_pass_and_hidden_context(
    monkeypatch,
):
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent.state = SimpleNamespace(
        context=[exchange("submit_to_agent", "[TASK_ID: task-one]")]
    )

    async def collect(tasks):
        assert tasks == {"task-one"}
        return "真实报告"

    monkeypatch.setattr(delegation, "collect_agent_tasks", collect)
    assert await agent._collect_delegated_results() is True
    assert (
        agent.state.context[-1].metadata["qwenpaw_tag"] == "agent_task_results"
    )
    assert await agent._collect_delegated_results() is False


async def test_doom_gate_does_not_stop_legitimate_running_polls():
    gate = DoomLoopGate(window_size=3)
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                exchange(
                    "check_agent_task",
                    "[TASK_ID: task-one]\n[STATUS: running]",
                )
            ]
        )
    )
    for iteration in range(12):
        assert (
            await gate.check({"agent": agent, "iteration": iteration}) is None
        )


async def test_poll_wait_returns_report_instead_of_stale_running(monkeypatch):
    responses = iter(
        [
            {"status": "running"},
            {
                "status": "finished",
                "result": {
                    "status": "completed",
                    "output": [
                        {"content": [{"type": "text", "text": "final"}]}
                    ],
                },
            },
        ]
    )
    monkeypatch.setattr(
        agent_management,
        "get_agent_chat_task_status",
        lambda *a, **k: next(responses),
    )
    sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda _: sleep(0))
    result = await agent_management.check_agent_task("task-one")
    assert "[STATUS: finished]" in result.content[0].text
    assert "final" in result.content[0].text


async def test_reasoning_consumes_collected_report_before_emitting_final(
    monkeypatch,
):
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent.state = SimpleNamespace(
        context=[exchange("submit_to_agent", "[TASK_ID: task-one]")]
    )
    agent._request_context = {}
    agent._gate_pending_stop = None
    agent._gate_pending_continue = None
    monkeypatch.setattr(agent, "_maybe_inject_convergence_hint", lambda: None)
    monkeypatch.setattr(agent, "_model_rejects_media", lambda: False)
    monkeypatch.setattr(
        agent, "_uses_request_time_media_normalization", lambda: True
    )
    monkeypatch.setattr(agent, "_set_formatter_media_strip", lambda _: None)
    monkeypatch.setattr(
        agent,
        "_run_stop_handlers",
        AsyncMock(return_value=StopHandlerResult()),
    )
    from qwenpaw.agents import model_factory

    monkeypatch.setattr(
        model_factory, "_supports_multimodal_for_current_model", lambda: True
    )

    async def model_reply(self, **kwargs):
        yield Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(text="回答")],
        )

    monkeypatch.setattr(Agent, "_reasoning", model_reply)
    monkeypatch.setattr(
        delegation, "collect_agent_tasks", AsyncMock(return_value="已完成报告")
    )
    assert [evt async for evt in agent._reasoning()] == []
    assert agent.state.context[-1].content[0].text == "已完成报告"
    assert len([evt async for evt in agent._reasoning()]) == 1


async def test_completed_tool_hints_are_consumed_during_current_turn():
    agent = QwenPawAgent.__new__(QwenPawAgent)
    hint = Msg(
        name="system",
        role="assistant",
        content=[TextBlock(text="真实后台结果")],
    )
    coordinator = SimpleNamespace(
        pop_pending_hints=AsyncMock(side_effect=[[hint], []])
    )
    agent._request_context = {
        "session_id": "root",
        "tool_coordinator": coordinator,
    }
    agent.state = SimpleNamespace(context=[])
    assert await agent._inject_pending_hints() is True
    assert agent.state.context == [hint]
    assert await agent._inject_pending_hints() is False
