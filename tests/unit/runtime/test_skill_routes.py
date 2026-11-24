"""Business skills resolve request-local routes without probing MCP."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.drivers.capabilities import DriverRuntimeInfo
from qwenpaw.runtime.skill_routes import build_skill_route_hint


def _manager(*infos):
    return SimpleNamespace(list_drivers=AsyncMock(return_value=list(infos)))


def _info(name="alarm", enabled=True, status="active", protocol="mcp"):
    return DriverRuntimeInfo(name, protocol, enabled, status)


def _tool(driver="alarm", name="alarm__queryHistoricalAlarms"):
    return SimpleNamespace(
        name=name,
        _capability=SimpleNamespace(driver_name=driver, protocol="mcp"),
    )


def _routes(hint):
    start = hint.index("\n[") + 1
    return json.loads(hint[start:])


@pytest.mark.parametrize(
    "infos,tools,route,reason",
    [
        ([], [], "script", "mcp_not_configured"),
        ([_info(enabled=False)], [_tool()], "script", "mcp_disabled"),
        ([_info()], [_tool()], "mcp", "mcp_ready"),
        ([_info(status="inactive")], [], "unavailable", "mcp_not_ready"),
        ([_info()], [], "blocked", "no_exposed_tools"),
        (
            [_info(status="error", enabled=False, protocol="")],
            [],
            "unavailable",
            "driver_configuration_error",
        ),
        (
            [_info(protocol="other")],
            [],
            "unavailable",
            "driver_configuration_error",
        ),
    ],
)
async def test_route_state_matrix(infos, tools, route, reason):
    manager = _manager(*infos)
    hint = await build_skill_route_hint(manager, ["real-alarm"], tools)
    actual = _routes(hint)[0]
    assert actual["route"] == route
    assert actual["reason"] == reason
    assert actual["tools"] == (
        ["alarm__queryHistoricalAlarms"] if route == "mcp" else []
    )
    manager.list_drivers.assert_awaited_once_with()


async def test_state_failure_is_not_unconfigured_and_does_not_leak_error():
    manager = _manager()
    manager.list_drivers.side_effect = RuntimeError("secret-token")
    for current in (manager, None):
        hint = await build_skill_route_hint(current, ["real-alarm"], [])
        assert _routes(hint)[0]["reason"] == "driver_state_unknown"
        assert "secret-token" not in hint


async def test_unrelated_skills_do_not_inspect_drivers():
    manager = _manager()
    assert await build_skill_route_hint(manager, ["docx"], []) is None
    manager.list_drivers.assert_not_called()


async def test_mixed_capabilities_and_partial_tool_visibility():
    manager = _manager(
        _info("cmdb-query", enabled=False),
        _info("inspection"),
    )
    hint = await build_skill_route_hint(
        manager,
        ["inspection-analyst", "inspection-analyst"],
        [_tool("inspection", "inspection__getMetricData")],
    )
    routes = _routes(hint)
    assert len(routes) == 2
    assert [row["route"] for row in routes] == ["script", "mcp"]
    assert routes[1]["tools"] == ["inspection__getMetricData"]
    assert "tool whitelist exclusions must not be bypassed" in hint


@pytest.mark.parametrize(
    "discovery,tools,expected_route,expected_reason",
    [
        (None, ["resource__querySyslogLogs", "resource__getSyslogLogDetail"], "mcp", "mcp_ready"),
        (None, [], "blocked", "no_exposed_tools"),
        ("mcp_transport_unavailable", [], "unavailable", "mcp_transport_unavailable"),
    ],
)
async def test_alarm_analyst_resolves_syslog_route(
    discovery, tools, expected_route, expected_reason,
):
    hint = await build_skill_route_hint(
        _manager(_info("resource")),
        ["alarm-analyst"],
        [_tool("resource", name) for name in tools],
        discovery_states={"resource": discovery} if discovery else {},
    )
    route = next(row for row in _routes(hint) if row["driver"] == "resource")
    assert route["route"] == expected_route
    assert route["reason"] == expected_reason
    assert route["tools"] == sorted(tools)


async def test_workspace_state_is_not_cached_between_requests():
    first = _manager(_info(enabled=False))
    second = _manager(_info())
    tools = [_tool()]
    assert (
        _routes(
            await build_skill_route_hint(
                first,
                ["real-alarm"],
                tools,
            )
        )[
            0
        ]["route"]
        == "script"
    )
    assert (
        _routes(
            await build_skill_route_hint(
                second,
                ["real-alarm"],
                tools,
            )
        )[
            0
        ]["route"]
        == "mcp"
    )
    first.list_drivers.return_value = [_info()]
    assert (
        _routes(
            await build_skill_route_hint(
                first,
                ["real-alarm"],
                tools,
            )
        )[
            0
        ]["route"]
        == "mcp"
    )


async def test_route_instructions_keep_read_only_and_error_boundaries():
    hint = await build_skill_route_hint(_manager(), ["real-alarm"], [])
    for boundary in (
        "business errors never trigger script fallback",
        "Never replay a write via script",
        "scripts must use --no-notify",
        "Do not probe MCP first",
        "generic execution_error is not",
    ):
        assert boundary in hint


async def test_route_hint_reaches_the_built_system_prompt(tmp_path):
    from qwenpaw.runtime.builder import AgentBuilder

    hint = await build_skill_route_hint(_manager(), ["real-alarm"], [])
    ctx = SimpleNamespace(
        workspace_dir=tmp_path,
        agent_id="query",
        workspace=None,
        extras={"driver_prompt_hints": [hint]},
    )
    config = SimpleNamespace(language="zh", heartbeat=None, running=None)
    prompt = AgentBuilder().build_prompt(ctx, config)
    assert "# Skill execution routes" in prompt
    assert '"reason": "mcp_not_configured"' in prompt
