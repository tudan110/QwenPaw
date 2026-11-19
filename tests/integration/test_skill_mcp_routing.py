"""Effective Driver switches work before background handler reload."""

import json

import pytest

from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
from qwenpaw.drivers.capabilities import DriverInvocation
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


async def _manager(root, *, enabled=True, effect="allow"):
    card = DriverCard(
        name="alarm",
        protocol="mcp",
        enabled=enabled,
        endpoint={"transport": "stdio", "command": "fake-mcp"},
        policy=[PolicyRule(subject="*", effect=effect)],
    )
    path = card_path(root / "drivers", "alarm", protocol="mcp")
    dump_card(card, path)
    manager = DriverManager(
        root / "drivers",
        AsyncCredentialStore(root / "credentials.yaml"),
    )
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.start()
    return manager, card, path


async def _route(manager):
    tools, _ = await build_driver_agent_tools(manager, {})
    hint = await build_skill_route_hint(manager, ["real-alarm"], tools)
    start = hint.index("\n[") + 1
    return json.loads(hint[start:])[0]


@pytest.mark.asyncio
async def test_unconfigured_driver_uses_script_without_connecting(
    tmp_path,
    monkeypatch,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )
    manager.register_handler_type("mcp", MCPDriverHandler)
    await manager.start()
    try:
        route = await _route(manager)
        assert route["route"] == "script"
        assert route["reason"] == "mcp_not_configured"
        assert FakeStdIOClient.instances == []
    finally:
        await manager.shutdown_all()


@pytest.mark.asyncio
async def test_enabled_driver_routes_and_invokes_mcp(tmp_path, monkeypatch):
    patch_mcp_runtime_clients(monkeypatch)
    manager, _, _ = await _manager(tmp_path)
    try:
        assert (await _route(manager))["route"] == "mcp"
        capability = next(
            capability
            for capability in await manager.list_capabilities(kind="tool")
            if capability.name == "echo"
        )
        result = await manager.invoke_capability(
            DriverInvocation(capability.capability_id, {"query": "alarm"}),
        )
        assert result.ok
        assert result.value == {"echo": {"query": "alarm"}}
        assert FakeStdIOClient.instances[0].calls == [
            ("echo", {"query": "alarm"}),
        ]
    finally:
        await manager.shutdown_all()


@pytest.mark.asyncio
async def test_saved_disable_blocks_stale_tools_before_reload(
    tmp_path,
    monkeypatch,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager, card, path = await _manager(tmp_path)
    try:
        capabilities = await manager.list_capabilities(kind="tool")
        assert capabilities
        assert (await _route(manager))["route"] == "mcp"
        client = FakeStdIOClient.instances[0]

        # Persist the switch without reloading the connected handler.
        card.enabled = False
        dump_card(card, path)
        assert client.is_connected
        assert (await manager.list_drivers())[0].status == "disabled"
        assert await manager.list_capabilities(kind="tool") == []
        assert await manager.list_driver_capabilities("alarm") == []
        assert (await _route(manager))["reason"] == "mcp_disabled"
        result = await manager.invoke_capability(
            DriverInvocation(capabilities[0].capability_id, {}),
        )
        assert not result.ok
        assert result.error_type == "driver_unavailable"
        assert client.calls == []

        # A normal reload and re-enable restores tools on the next request.
        await manager.reload_driver("alarm")
        card.enabled = True
        dump_card(card, path)
        assert (await _route(manager))["reason"] == "mcp_not_ready"
        await manager.reload_driver("alarm")
        assert (await _route(manager))["route"] == "mcp"
    finally:
        await manager.shutdown_all()


@pytest.mark.asyncio
async def test_workspace_switches_are_isolated(tmp_path, monkeypatch):
    patch_mcp_runtime_clients(monkeypatch)
    first, _, _ = await _manager(tmp_path / "one", enabled=False)
    second, _, _ = await _manager(tmp_path / "two")
    try:
        assert (await _route(first))["route"] == "script"
        assert (await _route(second))["route"] == "mcp"
        assert len(FakeStdIOClient.instances) == 1
        assert FakeStdIOClient.instances[0].calls == []
    finally:
        await first.shutdown_all()
        await second.shutdown_all()


@pytest.mark.asyncio
async def test_invalid_card_never_becomes_script_fallback(
    tmp_path,
    monkeypatch,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager, _, path = await _manager(tmp_path)
    try:
        capabilities = await manager.list_capabilities(kind="tool")
        path.write_text("invalid: [", encoding="utf-8")
        route = await _route(manager)
        assert route["route"] == "unavailable"
        assert route["reason"] == "driver_configuration_error"
        result = await manager.invoke_capability(
            DriverInvocation(capabilities[0].capability_id, {}),
        )
        assert not result.ok
        assert FakeStdIOClient.instances[0].calls == []
    finally:
        await manager.shutdown_all()


@pytest.mark.asyncio
async def test_policy_denial_remains_a_denial_without_client_call(
    tmp_path,
    monkeypatch,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager, _, _ = await _manager(tmp_path, effect="deny")
    try:
        capabilities = await manager.list_capabilities(kind="tool")
        result = await manager.invoke_capability(
            DriverInvocation(capabilities[0].capability_id, {}),
        )
        assert result.error_type == "driver_policy_denied"
        assert FakeStdIOClient.instances[0].calls == []
    finally:
        await manager.shutdown_all()


@pytest.mark.asyncio
async def test_saved_whitelist_blocks_old_tools_without_script_fallback(
    tmp_path,
    monkeypatch,
):
    patch_mcp_runtime_clients(monkeypatch)
    manager, card, path = await _manager(tmp_path)
    try:
        capabilities = await manager.list_capabilities(kind="tool")
        echo = next(item for item in capabilities if item.name == "echo")
        card.config["tools"] = ["get_secret_status"]
        dump_card(card, path)
        visible = await manager.list_capabilities(kind="tool")
        assert [item.name for item in visible] == ["get_secret_status"]
        result = await manager.invoke_capability(
            DriverInvocation(echo.capability_id, {}),
        )
        assert result.error_type == "driver_policy_denied"
        assert FakeStdIOClient.instances[0].calls == []
        card.config["tools"] = []
        dump_card(card, path)
        assert (await _route(manager))["route"] == "blocked"
    finally:
        await manager.shutdown_all()
