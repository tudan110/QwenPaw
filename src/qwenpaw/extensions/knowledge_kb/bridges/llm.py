"""LLM bridge: replaces the legacy DeepSeek-only llm_provider by routing
through qwenpaw's `create_model_and_formatter` against the knowledge agent.

Public surface mirrors the legacy module shape, but `call_llm` is async
since FastAPI route handlers can await it directly.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from ..paths import KNOWLEDGE_AGENT_ID

SLOW_CALL_THRESHOLD_MS = 10_000


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


def is_llm_available() -> bool:
    """LLM is usable iff the knowledge agent has an active model configured.

    qwenpaw imports are lazy so this module remains importable in minimal
    environments.
    """
    try:
        from qwenpaw.agents.model_factory import (  # noqa: PLC0415
            create_model_and_formatter,
        )

        create_model_and_formatter(agent_id=KNOWLEDGE_AGENT_ID)
        return True
    except Exception:  # pylint: disable=broad-except
        return False


def _extract_text(response) -> str:
    """Pull text out of an agentscope ChatResponse (mirrors
    qwenpaw.app.routers.skills_stream._extract_text_from_response)."""
    if hasattr(response, "text"):
        text = response.text
        if isinstance(text, str):
            return text
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "".join(parts)
    if isinstance(response, str):
        return response
    return ""


async def call_llm(
    messages: list[dict],
    *,
    timeout_s: float = 30.0,
    request_id: str | None = None,
) -> dict:
    """Call qwenpaw's chat model bound to the knowledge agent.

    Success return mirrors legacy shape:
      {answer, provider, model, latency_ms, tokens_in, tokens_out,
       request_id, created_at}

    `timeout_s` is informational only; underlying model has its own timeouts.
    """
    _ = timeout_s
    query_hash = _user_message_hash(messages)

    from qwenpaw.agents.model_factory import (  # noqa: PLC0415
        create_model_and_formatter,
    )

    try:
        model, _formatter = create_model_and_formatter(
            agent_id=KNOWLEDGE_AGENT_ID,
        )
    except Exception as exc:  # pylint: disable=broad-except
        _log("qwenpaw", "unknown", query_hash, 0, "disabled",
             request_id, error=str(exc))
        raise LLMDisabled(
            "knowledge agent has no active model configured "
            "(set provider/model in console)"
        ) from exc

    model_name = getattr(getattr(model, "_model", None), "model_name", None) \
        or getattr(model, "model_name", None) \
        or "unknown"

    started = time.monotonic()
    try:
        response = await model(messages)
    except TimeoutError as exc:
        latency = _ms_since(started)
        _log("qwenpaw", model_name, query_hash, latency, "timeout",
             request_id, error=str(exc))
        raise LLMTimeout(f"qwenpaw chat timeout: {exc}") from exc
    except Exception as exc:  # pylint: disable=broad-except
        latency = _ms_since(started)
        msg = str(exc)
        if "rate" in msg.lower() and "limit" in msg.lower():
            _log("qwenpaw", model_name, query_hash, latency, "rate_limited",
                 request_id, error=msg)
            raise LLMRateLimit(f"qwenpaw chat rate-limited: {msg}") from exc
        _log("qwenpaw", model_name, query_hash, latency, "server_error",
             request_id, error=msg)
        raise LLMProviderError(f"qwenpaw chat error: {msg}") from exc

    latency = _ms_since(started)

    answer = ""
    if hasattr(response, "__aiter__"):
        # Streaming response; accumulate text deltas.
        accumulated = ""
        try:
            async for chunk in response:
                text = _extract_text(chunk)
                if text and len(text) > len(accumulated):
                    accumulated = text
        except Exception as exc:  # pylint: disable=broad-except
            _log("qwenpaw", model_name, query_hash, latency, "invalid_response",
                 request_id, error=f"stream error: {exc}")
            raise LLMInvalidResponse(f"stream error: {exc}") from exc
        answer = accumulated
    else:
        answer = _extract_text(response)

    if not isinstance(answer, str) or not answer.strip():
        _log("qwenpaw", model_name, query_hash, latency, "invalid_response",
             request_id, error="empty answer")
        raise LLMInvalidResponse("empty answer from chat model")

    usage = getattr(response, "usage", None) or {}
    tokens_in = int(
        usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0,
    )
    tokens_out = int(
        usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0,
    )

    _log("qwenpaw", model_name, query_hash, latency, "success",
         request_id, tokens_in=tokens_in, tokens_out=tokens_out)

    return {
        "answer": answer,
        "provider": "qwenpaw",
        "model": model_name,
        "latency_ms": latency,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "request_id": request_id,
        "created_at": _now_iso(),
    }


def _ms_since(started_monotonic: float) -> int:
    return int((time.monotonic() - started_monotonic) * 1000)


def _user_message_hash(messages: list[dict]) -> str:
    joined = "".join(
        m.get("content", "") for m in messages if m.get("role") == "user"
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log(
    provider: str,
    model: str,
    query_hash: str,
    latency_ms: int,
    status: str,
    request_id: str | None,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
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
    prefix = "WARN:[kb-llm]" if latency_ms > SLOW_CALL_THRESHOLD_MS else "[kb-llm]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
