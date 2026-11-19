"""Exact admission does not inherit permitted hosts or service-domain suffixes."""
import json

import httpx
import pytest

from qwenpaw.drivers.handlers.mcp_stateful_client import HttpStatefulClient
from qwenpaw.extensions.security.mcp_boundary import validate_endpoint


@pytest.fixture
def exact(monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_HOSTS", "another-host")
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_ENDPOINTS", json.dumps([
        {"transport": "sse", "url": "https://data.test.invalid/sse"},
        {"transport": "sse", "url": "https://data.test.invalid/message"},
    ]))


def test_only_registered_transport_scheme_host_port_and_path_match(exact):
    validate_endpoint({"transport": "sse", "url": "https://data.test.invalid:443/sse"})
    for transport, address in [
        ("streamable_http", "https://data.test.invalid/sse"),
        ("sse", "http://data.test.invalid/sse"),
        ("sse", "https://data.test.invalid:8443/sse"),
        ("sse", "https://data.test.invalid/SSE"),
        ("sse", "https://data.test.invalid/sse?api_key=secret"),
        ("sse", "https://data.test.invalid/sse#fragment"),
        ("sse", "https://data.test.invalid/%73se"),
        ("sse", "https://data.test.invalid/a/../sse"),
        ("sse", "https://mcp.ns.svc.cluster.local/sse"),
        ("sse", "http://another-host/sse"),
    ]:
        with pytest.raises(PermissionError):
            validate_endpoint({"transport": transport, "url": address})


@pytest.mark.asyncio
async def test_transport_checks_same_origin_path_before_request(exact):
    client = HttpStatefulClient(
        name="test", transport="sse", url="https://data.test.invalid/sse",
    )
    # The SSE server can advertise a second endpoint with a session ID,
    # but it must still be explicitly listed for the same origin.
    await client._check_request_origin(httpx.Request(
        "POST", "https://data.test.invalid/message?session_id=fixture",
    ))
    for unlisted in ("https://data.test.invalid/other", "https://other.test.invalid/message"):
        with pytest.raises(PermissionError):
            await client._check_request_origin(httpx.Request("POST", unlisted))


@pytest.mark.parametrize("config", ["[]", "{}", "["])
def test_empty_or_invalid_exact_policy_fails_closed(exact, monkeypatch, config):
    monkeypatch.setenv("QWENPAW_MCP_ALLOWED_ENDPOINTS", config)
    with pytest.raises(PermissionError):
        validate_endpoint({"transport": "sse", "url": "https://data.test.invalid/sse"})
