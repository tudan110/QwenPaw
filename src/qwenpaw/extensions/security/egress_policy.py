"""Declared egress routes with DNS-to-socket pinning and origin TLS checks."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket

import httpx

from qwenpaw.constant import EnvVarLoader
from .mcp_boundary import endpoint_key


def _route(request: httpx.Request) -> dict:
    from urllib.parse import urlsplit, urlunsplit

    target = urlsplit(str(request.url))
    if target.username or target.password or target.fragment:
        raise PermissionError("外联目标不能包含身份或片段")
    key = endpoint_key(urlunsplit((target.scheme, target.netloc, target.path, "", "")))
    rules = json.loads(EnvVarLoader.get_str("QWENPAW_EGRESS_RULES", "[]"))
    if not isinstance(rules, list):
        raise PermissionError("外联规则格式错误")
    match = next(
        (
            rule
            for rule in rules
            if isinstance(rule, dict)
            and endpoint_key(str(rule.get("url", ""))) == key
            and request.method in rule.get("methods", [])
        ),
        None,
    )
    if match is None:
        raise PermissionError("外联协议、目标、端口、路径或方法未登记")
    return match


def select_address(request: httpx.Request, addresses: list[str]) -> str:
    match = _route(request)
    networks = [ipaddress.ip_network(value) for value in match.get("networks", [])]
    if not addresses:
        raise PermissionError("外联 DNS 未返回地址")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if (
            address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or str(address) in {"169.254.169.254", "fd00:ec2::254"}
        ):
            raise PermissionError("禁止访问元数据或特殊网络地址")
        if not any(address in network for network in networks):
            raise PermissionError("DNS 地址超出登记网络范围")
    return addresses[0]


def _resolve(host: str, port: int) -> list[str]:
    try:
        return sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        )
    except OSError:
        raise PermissionError("外联 DNS 解析失败") from None


def _pinned_request(request: httpx.Request, addresses: list[str]) -> httpx.Request:
    address = select_address(request, addresses)
    headers = request.headers.copy()
    headers["host"] = request.url.netloc.decode("ascii")
    return httpx.Request(
        request.method,
        request.url.copy_with(host=address),
        headers=headers,
        stream=request.stream,
        extensions={**request.extensions, "sni_hostname": request.url.host},
    )


def _audit_start(request):
    from qwenpaw.governance.audit import AuditLog
    from qwenpaw.governance.policy import ToolCallSpec
    from qwenpaw.app.agent_context import get_current_agent_id, get_current_session_id

    log = AuditLog.get_instance()
    spec = ToolCallSpec(
        tool_name="Egress",
        target=str(request.url.copy_with(query=None)),
        agent_id=get_current_agent_id() or "",
        session_id=get_current_session_id() or "",
        raw_params={"method": request.method},
    )
    return log, spec, log.execution_event("", spec, "started")


class PinnedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, control_exempt=False):
        # Different names can share an IP. Disable pooled reuse so TLS is
        # verified against each original hostname, never a prior IP peer.
        self._inner = httpx.AsyncHTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=0)
        )
        self._control_exempt = control_exempt

    async def handle_async_request(self, request):
        _route(request)  # Reject before DNS (hostnames can themselves be data).
        epoch = None
        if not self._control_exempt:
            from .execution_control import assert_execution_open

            epoch = assert_execution_open()
        addresses = await asyncio.to_thread(
            _resolve,
            request.url.host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        pinned = _pinned_request(request, addresses)
        if epoch is not None and assert_execution_open() != epoch:
            raise PermissionError("外联前控制版本已变化")
        audit = None if self._control_exempt else _audit_start(request)
        try:
            response = await self._inner.handle_async_request(pinned)
        except BaseException as exc:
            if audit:
                audit[0].execution_event(
                    "",
                    audit[1],
                    "failed",
                    trace_id=audit[2],
                    error_type=type(exc).__name__,
                )
            raise
        if audit:
            audit[0].execution_event(
                "",
                audit[1],
                f"headers_received_{response.status_code}",
                trace_id=audit[2],
            )
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise PermissionError("受控外联拒绝自动重定向")
        return response

    async def aclose(self):
        await self._inner.aclose()


class PinnedTransport(httpx.BaseTransport):
    def __init__(self):
        self._inner = httpx.HTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=0)
        )

    def handle_request(self, request):
        _route(request)
        from .execution_control import assert_execution_open

        epoch = assert_execution_open()
        addresses = _resolve(
            request.url.host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
        )
        pinned = _pinned_request(request, addresses)
        if assert_execution_open() != epoch:
            raise PermissionError("外联前控制版本已变化")
        log, spec, trace = _audit_start(request)
        try:
            response = self._inner.handle_request(pinned)
        except BaseException as exc:
            log.execution_event(
                "", spec, "failed", trace_id=trace, error_type=type(exc).__name__
            )
            raise
        log.execution_event(
            "", spec, f"headers_received_{response.status_code}", trace_id=trace
        )
        if 300 <= response.status_code < 400:
            response.close()
            raise PermissionError("受控外联拒绝自动重定向")
        return response

    def close(self):
        self._inner.close()


def controlled_async_client(*, control_exempt=False, **kwargs) -> httpx.AsyncClient:
    from .execution_policy import enabled

    if enabled():
        if kwargs.get("proxy") is not None or kwargs.get("mounts"):
            raise PermissionError("生产受控外联不允许代理或自定义传输挂载")
        kwargs.update(
            transport=PinnedAsyncTransport(control_exempt),
            follow_redirects=False,
            trust_env=False,
        )
    return httpx.AsyncClient(**kwargs)


def controlled_client(**kwargs) -> httpx.Client:
    from .execution_policy import enabled

    if enabled():
        if kwargs.get("proxy") is not None or kwargs.get("mounts"):
            raise PermissionError("生产受控外联不允许代理或自定义传输挂载")
        kwargs.update(
            transport=PinnedTransport(), follow_redirects=False, trust_env=False
        )
    return httpx.Client(**kwargs)
