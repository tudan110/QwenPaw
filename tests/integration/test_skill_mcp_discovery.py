"""One MCP discovery failure must not hide healthy Driver capabilities."""

import json
from unittest.mock import AsyncMock

import pytest

from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
from qwenpaw.drivers.contracts import DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from qwenpaw.runtime.skill_routes import build_skill_route_hint
from tests.integration.driver_mcp_fakes import (
    FakeStdIOClient,
    patch_mcp_runtime_clients,
)


@pytest.mark.parametrize(
    "failure,reason",
    [
        (
            ConnectionError("sensitive-failure-detail connection URL"),
            "mcp_transport_unavailable",
        ),
        (
            TimeoutError("sensitive-failure-detail connection URL"),
            "mcp_transport_unavailable",
        ),
        (
            ValueError("sensitive-failure-detail business error"),
            "mcp_discovery_failed",
        ),
    ],
)
async def test_discovery_isolated_per_driver(
    tmp_path,
    monkeypatch,
    failure,
    reason,
    caplog,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    manager.register_handler_type("mcp", MCPDriverHandler)
    for name in ("alarm", "inspection"):
        dump_card(
            DriverCard(
                name=name,
                protocol="mcp",
                endpoint={"transport": "stdio", "command": "fake-mcp"},
                policy=[PolicyRule(subject="*", effect="allow")],
            ),
            card_path(tmp_path / "drivers", name, protocol="mcp"),
        )
    await manager.start()
    try:
        failed_client = next(
            client
            for client in FakeStdIOClient.instances
            if client.kwargs["name"] == "alarm"
        )
        failed_client.list_tools = AsyncMock(side_effect=failure)
        states = {}
        tools, _ = await build_driver_agent_tools(
            manager,
            {},
            discovery_states=states,
        )
        assert states == {"alarm": reason, "inspection": "mcp_ready"}
        assert tools
        assert all(tool.name.startswith("inspection__") for tool in tools)
        hint = await build_skill_route_hint(
            manager,
            ["alarm-analyst"],
            tools,
            discovery_states=states,
        )
        json_start = hint.index("\n[") + 1
        routes = {
            route["driver"]: route for route in json.loads(hint[json_start:])
        }
        assert routes["inspection"]["route"] == "mcp"
        assert routes["alarm"]["reason"] == reason
        assert "sensitive-failure-detail" not in hint
        assert "sensitive-failure-detail" not in caplog.text
    finally:
        await manager.shutdown_all()


async def test_inventory_failure_has_explicit_unknown_discovery_state():
    manager = AsyncMock()
    manager.list_drivers.side_effect = ValueError(
        "sensitive-failure-detail malformed file"
    )
    states = {"alarm": "mcp_ready"}
    tools, hints = await build_driver_agent_tools(
        manager,
        {},
        discovery_states=states,
    )
    assert tools == []
    assert hints == []
    assert states == {"*": "mcp_discovery_failed"}
    manager.list_driver_capabilities.assert_not_called()
