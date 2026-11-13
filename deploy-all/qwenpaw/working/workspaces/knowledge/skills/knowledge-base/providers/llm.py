"""LLM provider for HyDE query rewriting and downstream RAG synthesis.

DeepSeek today; structure leaves room for additional providers.
Pure stdlib (urllib + json). Raises LLMError subclasses on failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request


DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
SLOW_CALL_MS = 10_000


class LLMError(Exception):
    reason: str = "unknown"


class LLMDisabled(LLMError):
    reason = "disabled"


class LLMTimeout(LLMError):
    reason = "timeout"


class LLMRateLimit(LLMError):
    reason = "rate_limited"


class LLMProviderError(LLMError):
    reason = "server_error"


class LLMInvalidResponse(LLMError):
    reason = "invalid_response"


class LLMNotConfigured(LLMError):
    reason = "model_not_configured"


class LLMAuthError(LLMError):
    reason = "model_auth_failed"


def _model_error(exc: Exception) -> LLMError:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None)
        if status is None:
            status = getattr(getattr(current, "response", None), "status_code", None)
        if status in (401, 403):
            return LLMAuthError("model authentication failed")
        if status == 429:
            return LLMRateLimit("model rate limited")
        if isinstance(current, TimeoutError) or "timeout" in (
            type(current).__name__.lower()
        ):
            return LLMTimeout("model request timed out")
        current = current.__cause__ or current.__context__
    return LLMProviderError("qwenpaw active model execution failed")


def model_status(agent_id: str = "knowledge") -> dict:
    """Report configuration readiness, not a claim of upstream connectivity."""
    try:
        from qwenpaw.extensions.integrations.knowledge_model import (
            KnowledgeModelUnavailable, resolve_knowledge_model,
        )
    except ImportError:
        return {"enabled": False, "reason": "host_package_unavailable"}
    try:
        selection = resolve_knowledge_model(agent_id)
    except KnowledgeModelUnavailable as exc:
        return {"enabled": False, "reason": exc.reason}
    return {"enabled": True, "connectivity_checked": False,
            **selection.metadata()}


def is_available(provider: str = "deepseek") -> bool:
    """Check whether a provider is callable in the current process.

    Configuration readiness is checked without changing model selections.
    """
    if provider == "deepseek":
        return bool(os.environ.get("DEEPSEEK_API_KEY"))
    if provider in ("qwenpaw", "qwenpaw_active"):
        return model_status()["enabled"]
    return False


def first_available(*providers: str) -> str | None:
    """Return the first provider name from *providers that is_available()."""
    for p in providers:
        if is_available(p):
            return p
    return None


def call_llm(
    provider: str,
    messages: list[dict],
    *,
    model: str | None = None,
    timeout_s: float = 30.0,
    request_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Dispatch to a provider. Returns dict with answer, latency, tokens."""
    if provider == "deepseek":
        return _call_deepseek(
            messages, model=model, timeout_s=timeout_s,
            request_id=request_id, api_key=api_key,
        )
    if provider in ("qwenpaw", "qwenpaw_active"):
        return _call_qwenpaw_active(
            messages, timeout_s=timeout_s, request_id=request_id,
        )
    raise LLMProviderError(f"unknown provider: {provider}")


def _call_qwenpaw_active(
    messages: list[dict],
    *,
    timeout_s: float = 30.0,
    request_id: str | None = None,
    agent_id: str = "knowledge",
) -> dict:
    """Bridge into QwenPaw's currently-active LLM (set in the portal UI).

    The active model is async — we run it via asyncio.run from this sync entry
    point. Safe inside FastAPI's threadpool (no parent loop) but would deadlock
    if called from inside a running event loop.
    """
    import asyncio

    from qwenpaw.agents.model_factory import create_model_and_formatter

    started = time.monotonic()
    query_hash = _user_message_hash(messages)
    async def _run() -> str:
        from agentscope.message import Msg, TextBlock
        from qwenpaw.extensions.integrations.knowledge_model import (
            resolve_knowledge_model,
        )

        selection = resolve_knowledge_model(agent_id)
        metadata.update(selection.metadata())
        model, _ = create_model_and_formatter(
            agent_id=agent_id, model_slot=selection.slot,
        )
        normalized = [
            Msg(name=message["role"], role=message["role"],
                content=[TextBlock(text=message["content"])])
            for message in messages
        ]
        response = await model(normalized)
        return await _drain_response(response)

    metadata: dict = {}
    try:
        answer = asyncio.run(asyncio.wait_for(_run(), timeout=timeout_s))
    except asyncio.TimeoutError as exc:
        latency = _ms(started)
        _log("qwenpaw", "active", query_hash, latency, "timeout",
             request_id, error=type(exc).__name__)
        raise LLMTimeout("qwenpaw active model timeout") from exc
    except Exception as exc:
        from qwenpaw.extensions.integrations.knowledge_model import (
            KnowledgeModelUnavailable,
        )

        if isinstance(exc, KnowledgeModelUnavailable):
            _log("qwenpaw", "active", query_hash, _ms(started), exc.reason,
                 request_id, error=type(exc).__name__)
            error = LLMNotConfigured(exc.reason)
            error.reason = exc.reason
            raise error from exc
        error = _model_error(exc)
        latency = _ms(started)
        _log("qwenpaw", "active", query_hash, latency, error.reason,
             request_id, error=type(exc).__name__)
        raise error from exc

    latency = _ms(started)
    if not answer or not answer.strip():
        raise LLMInvalidResponse("empty answer from qwenpaw active model")

    _log("qwenpaw", "active", query_hash, latency, "success", request_id)
    return {
        "answer": answer,
        "provider": "qwenpaw_active",
        **metadata,
        "latency_ms": latency,
        "tokens_in": 0,
        "tokens_out": 0,
        "request_id": request_id,
        "created_at": _now_iso(),
    }


async def _drain_response(response) -> str:
    """Reduce an AgentScope-style streaming response to a single string. Mirrors
    the helper in extensions/integrations/knowledge_base.py."""
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_text(chunk)
            if not text:
                continue
            if text.startswith(accumulated):
                accumulated = text
            else:
                accumulated += text
        return accumulated.strip()
    return _extract_text(response)


def _extract_text(payload) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    content = getattr(payload, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        fragments: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    fragments.append(str(text))
            elif getattr(item, "text", None):
                fragments.append(str(getattr(item, "text")))
        return "\n".join(f.strip() for f in fragments if f).strip()
    text = getattr(payload, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(payload).strip()


def _call_deepseek(
    messages: list[dict],
    *,
    model: str | None,
    timeout_s: float,
    request_id: str | None,
    api_key: str | None,
) -> dict:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise LLMDisabled("DEEPSEEK_API_KEY not set")

    model_name = model or DEFAULT_MODEL
    query_hash = _user_message_hash(messages)

    payload = json.dumps(
        {"model": model_name, "messages": messages, "stream": False},
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib_request.Request(
        DEEPSEEK_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "QwenPawKB/1.0",
        },
    )

    started = time.monotonic()
    try:
        with urllib_request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib_error.HTTPError as exc:
        latency = _ms(started)
        if exc.code == 429:
            _log("deepseek", model_name, query_hash, latency, "rate_limited",
                 request_id, error=f"HTTP 429: {exc.reason}")
            raise LLMRateLimit(f"deepseek 429: {exc.reason}") from exc
        _log("deepseek", model_name, query_hash, latency, "server_error",
             request_id, error=f"HTTP {exc.code}: {exc.reason}")
        raise LLMProviderError(f"deepseek HTTP {exc.code}: {exc.reason}") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        latency = _ms(started)
        reason_str = str(getattr(exc, "reason", exc))
        if isinstance(exc, TimeoutError) or "timed out" in reason_str.lower():
            _log("deepseek", model_name, query_hash, latency, "timeout",
                 request_id, error=reason_str)
            raise LLMTimeout(f"deepseek timeout: {reason_str}") from exc
        _log("deepseek", model_name, query_hash, latency, "server_error",
             request_id, error=reason_str)
        raise LLMProviderError(f"deepseek transport: {reason_str}") from exc

    latency = _ms(started)
    if not raw:
        raise LLMInvalidResponse("empty response body")

    try:
        data = json.loads(raw.decode("utf-8"))
        answer = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, IndexError, TypeError) as exc:
        _log("deepseek", model_name, query_hash, latency, "invalid_response",
             request_id, error=f"shape: {exc}")
        raise LLMInvalidResponse(f"unexpected response: {exc}") from exc

    if not isinstance(answer, str) or not answer.strip():
        raise LLMInvalidResponse("empty answer")

    usage = data.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens", 0) or 0)
    tokens_out = int(usage.get("completion_tokens", 0) or 0)

    _log("deepseek", model_name, query_hash, latency, "success",
         request_id, tokens_in=tokens_in, tokens_out=tokens_out)

    return {
        "answer": answer,
        "provider": "deepseek",
        "model": model_name,
        "latency_ms": latency,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "request_id": request_id,
        "created_at": _now_iso(),
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user_message_hash(messages: list[dict]) -> str:
    joined = "".join(m.get("content", "") for m in messages if m.get("role") == "user")
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def _log(
    provider: str, model: str, query_hash: str, latency_ms: int, status: str,
    request_id: str | None, *, tokens_in: int = 0, tokens_out: int = 0,
    error: str | None = None,
) -> None:
    entry = {
        "ts": _now_iso(),
        "request_id": request_id,
        "query_hash": query_hash,
        "provider": provider,
        "model": model,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "status": status,
    }
    if error:
        entry["error"] = error
    prefix = "WARN:[llm]" if latency_ms > SLOW_CALL_MS else "[llm]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
