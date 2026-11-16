"""Fail-closed JSON/SSE boundary for business responses.

Production SSE is buffered until completion (bounded to 8 MiB). We redact
individual fields, then check concatenated text for credentials split across
events. This deliberately trades first-token latency for validated output;
unbounded streams require a protocol-aware incremental guard before reopening.
Authentication exchanges are outside this business-output boundary.
"""

from __future__ import annotations

import json

from .channel_patch import BLOCKED_TEXT, _safe_redact

_TEXT_FIELDS = {
    "text",
    "content",
    "delta",
    "refusal",
    "arguments",
    "message",
    "reasoning_content",
    "reasoning",
    "result_summary",
    "answer",
}
_SECRET_FIELDS = {
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "secret",
    "client_secret",
    "private_key",
}


def _walk(value, texts: list[str], key=""):
    if isinstance(value, str):
        if key.lower() in _SECRET_FIELDS:
            return "[REDACTED]"
        safe, _ = _safe_redact(value)
        texts.append(safe)
        return safe
    if isinstance(value, list):
        return [_walk(item, texts, key) for item in value]
    if isinstance(value, dict):
        return {_safe_redact(k)[0]: _walk(v, texts, k) for k, v in value.items()}
    return value


def _guard_body(body: bytes, sse: bool) -> bytes:
    if not sse:
        return json.dumps(_walk(json.loads(body), []), ensure_ascii=False).encode()
    events = []
    texts = []
    for event in body.decode("utf-8").replace("\r\n", "\n").split("\n\n"):
        lines = event.splitlines()
        data = "\n".join(
            line[5:].lstrip(" ") for line in lines if line.startswith("data:")
        )
        if not data or data == "[DONE]":
            events.append(_safe_redact(event)[0])
            continue
        payload = _walk(json.loads(data), texts)
        metadata = [
            _safe_redact(line)[0] for line in lines if not line.startswith("data:")
        ]
        events.append(
            "\n".join([*metadata, "data: " + json.dumps(payload, ensure_ascii=False)])
        )
    joined = "".join(texts)
    _, hits = _safe_redact(joined)
    if hits:
        raise ValueError("split sensitive content")
    return "\n\n".join(events).encode()


def _business_path(path: str) -> bool:
    from ...api.access_policy import resource_path

    path = resource_path(path)
    return (
        path.startswith(
            ("/api/console/chat", "/api/chats", "/api/messages", "/api/console/inbox")
        )
        or path.startswith(
            (
                "/api/portal/knowledge-base/query",
                "/api/portal/knowledge-base/rag-synthesize",
                "/api/portal/alarm-analyst/diagnose",
                "/api/portal/fault-disposal/diagnose",
            )
        )
        or any(
            path.startswith(f"/api/portal/{name}-adapter/")
            for name in ("qiming", "xingchen", "kunlun")
        )
    )


class OutputBoundaryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _business_path(scope.get("path", "")):
            return await self.app(scope, receive, send)
        from ..execution_policy import enabled

        if not enabled():
            return await self.app(scope, receive, send)
        from qwenpaw.constant import EnvVarLoader

        maximum = max(
            1024, int(EnvVarLoader.get_str("QWENPAW_OUTPUT_MAX_BYTES", "8388608"))
        )
        start = None
        buffer = bytearray()
        guarded = False
        sse = False
        oversized = False
        start_sent = False

        async def guarded_send(message):
            nonlocal start, guarded, sse, oversized, start_sent
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"").decode().lower()
                sse = "text/event-stream" in content_type
                guarded = sse or "application/json" in content_type
                if guarded:
                    start = message
                    return
            if message["type"] != "http.response.body" or not guarded:
                await send(message)
                return
            chunk = message.get("body", b"")
            if len(buffer) + len(chunk) > maximum:
                oversized = True
                buffer.clear()
            elif not oversized:
                buffer.extend(chunk)
            if message.get("more_body", False):
                if sse:
                    if not start_sent:
                        start["headers"] = [
                            (k, v)
                            for k, v in start.get("headers", [])
                            if k.lower()
                            not in {b"content-length", b"cache-control", b"etag"}
                        ]
                        start["headers"].append((b"cache-control", b"no-store"))
                        await send(start)
                        start_sent = True
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b": output safety check pending\n\n",
                            "more_body": True,
                        }
                    )
                return
            try:
                if oversized:
                    raise ValueError("response limit")
                body = _guard_body(bytes(buffer), sse)
            except Exception:
                payload = json.dumps(
                    {
                        "error": {
                            "code": "OUTPUT_SECURITY_BLOCKED",
                            "message": BLOCKED_TEXT,
                        }
                    },
                    ensure_ascii=False,
                ).encode()
                body = b"data: " + payload + b"\n\ndata: [DONE]\n\n" if sse else payload
                if not sse:
                    start["status"] = 503
            start["headers"] = [
                (k, v)
                for k, v in start.get("headers", [])
                if k.lower() not in {b"content-length", b"etag"}
            ]
            start["headers"].append((b"cache-control", b"no-store"))
            if not start_sent:
                await send(start)
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, guarded_send)
