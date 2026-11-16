import json
import socket
import asyncio

import httpx
import pytest

from qwenpaw.extensions.security.egress_policy import (
    PinnedAsyncTransport,
    select_address,
)


def test_proxy_and_mounts_cannot_bypass_the_controlled_transport(monkeypatch):
    from qwenpaw.extensions.security.egress_policy import (
        controlled_async_client,
        controlled_client,
    )

    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    for factory in (controlled_async_client, controlled_client):
        with pytest.raises(PermissionError):
            factory(proxy="http://proxy.example:3128")
        with pytest.raises(PermissionError):
            factory(
                mounts={"https://": httpx.MockTransport(lambda r: httpx.Response(200))}
            )


@pytest.fixture
def rules(monkeypatch):
    monkeypatch.setenv(
        "QWENPAW_EGRESS_RULES",
        json.dumps(
            [
                {
                    "url": "https://model.example/v1/chat/completions",
                    "methods": ["POST"],
                    "networks": ["192.0.2.0/24"],
                }
            ]
        ),
    )


def test_exact_url_method_and_every_dns_answer_are_checked(rules):
    request = httpx.Request("POST", "https://model.example/v1/chat/completions")
    assert select_address(request, ["192.0.2.1"]) == "192.0.2.1"
    with pytest.raises(PermissionError):
        select_address(request, ["192.0.2.1", "127.0.0.1"])
    for url in [
        "https://model.example/admin",
        "https://model.example:8443/v1/chat/completions",
        "https://other.example/v1/chat/completions",
    ]:
        with pytest.raises(PermissionError):
            select_address(httpx.Request("POST", url), ["192.0.2.1"])
    with pytest.raises(PermissionError):
        select_address(httpx.Request("GET", str(request.url)), ["192.0.2.1"])


async def test_transport_pins_socket_address_and_preserves_tls_name(rules, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
        ],
    )
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = PinnedAsyncTransport()
    await transport._inner.aclose()
    transport._inner = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post(
            "https://model.example/v1/chat/completions",
            headers={"Host": "evil.example"},
        )
    assert seen[0].url.host == "192.0.2.1"
    assert seen[0].headers["host"] == "model.example"
    assert seen[0].extensions["sni_hostname"] == "model.example"


async def test_real_http_transport_does_not_follow_redirect_even_if_caller_requests_it(
    monkeypatch,
):
    from qwenpaw.extensions.security.egress_policy import controlled_async_client

    requests = []

    async def handler(reader, writer):
        try:
            data = await reader.readuntil(b"\r\n\r\n")
            requests.append(data)
            writer.write(
                b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:9/steal\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    url = f"http://127.0.0.1:{port}/allowed"
    monkeypatch.setenv(
        "QWENPAW_EGRESS_RULES",
        json.dumps([{"url": url, "methods": ["GET"], "networks": ["127.0.0.1/32"]}]),
    )
    try:
        async with controlled_async_client(timeout=2) as client:
            with pytest.raises(PermissionError, match="重定向"):
                await client.get(
                    url,
                    headers={"Authorization": "Bearer fixture"},
                    follow_redirects=True,
                )
        assert len(requests) == 1
        assert b"GET /allowed " in requests[0]
    finally:
        server.close()
        await server.wait_closed()
