"""LLM provider abstraction.

MVP ships DeepSeek only; structure reserved for future providers (OpenAI-compatible).
Pure stdlib (urllib.request + json). No KB content is injected at this layer —
caller formats messages. Errors are raised as LLMError subclasses so endpoint
handlers can map them to distinct HTTP 503 reasons.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request


DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

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


def is_provider_available(provider: str) -> bool:
    if provider == "deepseek":
        return bool(os.environ.get("DEEPSEEK_API_KEY"))
    return False


def call_llm(
    provider: str,
    messages: list[dict],
    *,
    model: str | None = None,
    timeout_s: float = 30.0,
    request_id: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Dispatch to a provider. Raises LLMError subclasses on failure.

    Success return:
      {answer, provider, model, latency_ms, tokens_in, tokens_out,
       request_id, created_at}

    api_key: if provided, overrides env var. Lets the frontend pass a user-local key
    without requiring server-side env config.
    """
    if provider == "deepseek":
        return _call_deepseek(
            messages, model=model, timeout_s=timeout_s, request_id=request_id, api_key=api_key
        )
    raise LLMProviderError(f"unknown provider: {provider}")


def _call_deepseek(
    messages: list[dict],
    *,
    model: str | None,
    timeout_s: float,
    request_id: str | None,
    api_key: str | None = None,
) -> dict:
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise LLMDisabled("no DEEPSEEK_API_KEY (neither server env nor client-provided)")

    model_name = model or DEFAULT_DEEPSEEK_MODEL
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
            "User-Agent": "KBMVP/0.2",
        },
    )

    started = time.monotonic()
    try:
        with urllib_request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except urllib_error.HTTPError as exc:
        latency = _ms_since(started)
        if exc.code == 429:
            _log("deepseek", model_name, query_hash, latency, "rate_limited",
                 request_id, error=f"HTTP 429: {exc.reason}")
            raise LLMRateLimit(f"deepseek 429: {exc.reason}") from exc
        _log("deepseek", model_name, query_hash, latency, "server_error",
             request_id, error=f"HTTP {exc.code}: {exc.reason}")
        raise LLMProviderError(f"deepseek HTTP {exc.code}: {exc.reason}") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        latency = _ms_since(started)
        reason_str = str(getattr(exc, "reason", exc))
        if isinstance(exc, TimeoutError) or "timed out" in reason_str.lower():
            _log("deepseek", model_name, query_hash, latency, "timeout",
                 request_id, error=reason_str)
            raise LLMTimeout(f"deepseek timeout: {reason_str}") from exc
        _log("deepseek", model_name, query_hash, latency, "server_error",
             request_id, error=reason_str)
        raise LLMProviderError(f"deepseek transport error: {reason_str}") from exc

    latency = _ms_since(started)
    if not raw:
        _log("deepseek", model_name, query_hash, latency, "invalid_response",
             request_id, error="empty body")
        raise LLMInvalidResponse("empty response body")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log("deepseek", model_name, query_hash, latency, "invalid_response",
             request_id, error=f"decode failed: {exc}")
        raise LLMInvalidResponse(f"could not decode response: {exc}") from exc

    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        _log("deepseek", model_name, query_hash, latency, "invalid_response",
             request_id, error=f"unexpected shape: {exc}")
        raise LLMInvalidResponse(f"unexpected response shape: {exc}") from exc

    if not isinstance(answer, str) or not answer.strip():
        _log("deepseek", model_name, query_hash, latency, "invalid_response",
             request_id, error="empty answer")
        raise LLMInvalidResponse("empty answer from deepseek")

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


def _ms_since(started_monotonic: float) -> int:
    return int((time.monotonic() - started_monotonic) * 1000)


def _user_message_hash(messages: list[dict]) -> str:
    joined = "".join(m.get("content", "") for m in messages if m.get("role") == "user")
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
    prefix = "WARN:[llm]" if latency_ms > SLOW_CALL_THRESHOLD_MS else "[llm]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
