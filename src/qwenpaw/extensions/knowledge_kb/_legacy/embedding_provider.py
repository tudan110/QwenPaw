"""Embedding provider abstraction.

MVP ships DashScope (Alibaba) text-embedding-v4 via their OpenAI-compatible
endpoint. Pure stdlib (urllib.request + json). Structure mirrors llm_provider.py.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request


DASHSCOPE_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DEFAULT_DASHSCOPE_MODEL = "text-embedding-v4"
DEFAULT_DIM = 1024

SLOW_CALL_THRESHOLD_MS = 8_000


class EmbeddingError(Exception):
    reason: str = "unknown"


class EmbeddingDisabled(EmbeddingError):
    reason = "disabled"


class EmbeddingTimeout(EmbeddingError):
    reason = "timeout"


class EmbeddingRateLimit(EmbeddingError):
    reason = "rate_limited"


class EmbeddingProviderError(EmbeddingError):
    reason = "server_error"


class EmbeddingInvalidResponse(EmbeddingError):
    reason = "invalid_response"


def is_provider_available(provider: str) -> bool:
    if provider == "dashscope":
        return bool(os.environ.get("DASHSCOPE_API_KEY"))
    return False


def embed_texts(
    texts: list[str],
    *,
    provider: str = "dashscope",
    model: str | None = None,
    timeout_s: float = 30.0,
    api_key: str | None = None,
    batch_id: str | None = None,
) -> list[list[float]]:
    """Return one vector per input text. Batched in a single HTTP call.

    Raises EmbeddingError subclasses on failure.
    """
    if provider == "dashscope":
        return _call_dashscope(
            texts, model=model, timeout_s=timeout_s, api_key=api_key, batch_id=batch_id
        )
    raise EmbeddingProviderError(f"unknown provider: {provider}")


def _call_dashscope(
    texts: list[str],
    *,
    model: str | None,
    timeout_s: float,
    api_key: str | None,
    batch_id: str | None,
) -> list[list[float]]:
    api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise EmbeddingDisabled("DASHSCOPE_API_KEY not set (neither env nor client)")

    if not texts:
        return []

    model_name = model or DEFAULT_DASHSCOPE_MODEL
    # DashScope's v4 supports single or list input; we always send a list.
    payload = json.dumps(
        {"model": model_name, "input": texts, "encoding_format": "float"},
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib_request.Request(
        DASHSCOPE_ENDPOINT,
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
            _log(model_name, len(texts), latency, "rate_limited", batch_id,
                 error=f"HTTP 429: {exc.reason}")
            raise EmbeddingRateLimit(f"dashscope 429: {exc.reason}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id,
             error=f"HTTP {exc.code}: {exc.reason}")
        raise EmbeddingProviderError(f"dashscope HTTP {exc.code}: {exc.reason}") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        latency = _ms_since(started)
        reason_str = str(getattr(exc, "reason", exc))
        if isinstance(exc, TimeoutError) or "timed out" in reason_str.lower():
            _log(model_name, len(texts), latency, "timeout", batch_id, error=reason_str)
            raise EmbeddingTimeout(f"dashscope timeout: {reason_str}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id, error=reason_str)
        raise EmbeddingProviderError(f"dashscope transport: {reason_str}") from exc

    latency = _ms_since(started)
    if not raw:
        _log(model_name, len(texts), latency, "invalid_response", batch_id, error="empty body")
        raise EmbeddingInvalidResponse("empty response body")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log(model_name, len(texts), latency, "invalid_response", batch_id, error=f"decode: {exc}")
        raise EmbeddingInvalidResponse(f"could not decode response: {exc}") from exc

    try:
        items = data["data"]
        vectors = [item["embedding"] for item in items]
    except (KeyError, IndexError, TypeError) as exc:
        _log(model_name, len(texts), latency, "invalid_response", batch_id, error=f"shape: {exc}")
        raise EmbeddingInvalidResponse(f"unexpected shape: {exc}") from exc

    if len(vectors) != len(texts):
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"count mismatch: sent {len(texts)} got {len(vectors)}")
        raise EmbeddingInvalidResponse(
            f"embedding count mismatch: sent {len(texts)} got {len(vectors)}"
        )

    usage = data.get("usage") or {}
    tokens_in = int(usage.get("prompt_tokens", 0) or usage.get("total_tokens", 0) or 0)
    _log(model_name, len(texts), latency, "success", batch_id, tokens_in=tokens_in)

    # Basic sanity check
    if vectors and len(vectors[0]) == 0:
        raise EmbeddingInvalidResponse("empty vector returned")

    return vectors


def cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    import math
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _ms_since(started_monotonic: float) -> int:
    return int((time.monotonic() - started_monotonic) * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _log(
    model: str,
    n_texts: int,
    latency_ms: int,
    status: str,
    batch_id: str | None,
    *,
    tokens_in: int = 0,
    error: str | None = None,
) -> None:
    entry = {
        "ts": _now_iso(),
        "batch_id": batch_id,
        "provider": "dashscope",
        "model": model,
        "n_texts": n_texts,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "status": status,
    }
    if error:
        entry["error"] = error
    prefix = "WARN:[embed]" if latency_ms > SLOW_CALL_THRESHOLD_MS else "[embed]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
