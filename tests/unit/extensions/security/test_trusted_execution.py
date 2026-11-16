"""Production capability and endpoint admission must fail closed."""

from unittest.mock import AsyncMock

import pytest

from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.security import execution_policy
from qwenpaw.extensions.security.mcp_boundary import validate_endpoint


@pytest.fixture(autouse=True)
def production(monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_ADMIN_INOE_USER_IDS", "7")
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_URLS", '["https://mcp.example:443/sse"]')
    monkeypatch.setenv("QWENPAW_READONLY_TOOL_NAMES", "")


async def test_unknown_tool_denied_even_for_admin(monkeypatch):
    token = CURRENT_IDENTITY.set(
        AccessIdentity(user={"userId": 7}, inoe_token="fixture")
    )
    validator = AsyncMock(return_value={"code": 200, "user": {"userId": 7}})
    monkeypatch.setattr(execution_policy, "_validate_inoe_token", validator)
    try:
        with pytest.raises(PermissionError, match="未登记"):
            await execution_policy.check_tool("unknown_business_action", {})
        validator.assert_not_awaited()
    finally:
        CURRENT_IDENTITY.reset(token)


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example/sse",
        "https://mcp.example:8443/sse",
        "https://mcp.example/other",
        "http://unknown.ns.svc/sse",
        "http://localhost/sse",
        "https://mcp.example/sse?token=secret",
        "https://mcp.example/%73se",
        "https://mcp.example/sse#other",
        "https://name:secret@mcp.example/sse",
    ],
)
def test_endpoint_requires_exact_declared_origin_and_path(url):
    with pytest.raises(PermissionError):
        validate_endpoint({"transport": "sse", "url": url})


def test_declared_endpoint_accepts_equivalent_default_port():
    validate_endpoint({"transport": "sse", "url": "https://mcp.example/sse"})


def test_legacy_hostname_declaration_does_not_authorize_every_port(monkeypatch):
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "legacy.example")
    with pytest.raises(PermissionError):
        validate_endpoint(
            {"transport": "sse", "url": "https://legacy.example:8443/private"}
        )


async def test_media_parse_failure_cannot_forward_unchecked_source(monkeypatch):
    from types import SimpleNamespace
    from qwenpaw.agents import utils
    from qwenpaw.hooks.request_setup.media_hook import MediaProcessHook

    async def fail(_):
        raise RuntimeError("private parser details")

    monkeypatch.setattr(utils, "process_file_and_media_blocks_in_message", fail)
    with pytest.raises(PermissionError, match="未校验"):
        await MediaProcessHook().run(
            SimpleNamespace(input_msgs=[SimpleNamespace(content=[])])
        )
