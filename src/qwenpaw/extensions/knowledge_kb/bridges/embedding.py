"""Embedding bridge: replaces the legacy DashScope-only embedding_provider
by reading the knowledge agent's `running.embedding_config` (OpenAI-compatible).

Public surface mirrors the legacy module so core.py can use it as a drop-in:
    embed_texts(texts, ...) -> list[list[float]]
    cosine_sim(a, b) -> float
    EmbeddingError + subclasses
    DEFAULT_DASHSCOPE_MODEL  (legacy name kept; resolves to current config)
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..paths import KNOWLEDGE_AGENT_ID

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


def _resolve_config() -> dict:
    """Read knowledge agent's embedding_config. Returns dict with
    api_key/base_url/model_name/dimensions/max_input_length/max_batch_size.

    Resolution priority (mirrors qwenpaw's reme_light_memory_manager):
        knowledge agent.embedding_config  >  EMBEDDING_* env  >  empty

    Imports qwenpaw config lazily so this module stays importable in test
    contexts that don't pull in the full provider stack.
    """
    import os  # noqa: PLC0415

    from qwenpaw.config.config import load_agent_config  # noqa: PLC0415

    cfg = load_agent_config(KNOWLEDGE_AGENT_ID).running.embedding_config
    return {
        "api_key": (cfg.api_key or os.environ.get("EMBEDDING_API_KEY", "")).strip(),
        "base_url": (cfg.base_url or os.environ.get("EMBEDDING_BASE_URL", "")).strip().rstrip("/"),
        "model_name": (cfg.model_name or os.environ.get("EMBEDDING_MODEL_NAME", "")).strip(),
        "dimensions": int(cfg.dimensions or 1024),
        "use_dimensions": bool(cfg.use_dimensions),
        "max_input_length": int(cfg.max_input_length or 8192),
        "max_batch_size": int(cfg.max_batch_size or 10),
    }


def is_embedding_available() -> bool:
    """Embedding is usable iff agent has api_key + base_url + model_name."""
    try:
        cfg = _resolve_config()
    except Exception:
        return False
    return bool(cfg["api_key"] and cfg["base_url"] and cfg["model_name"])


def current_model_name() -> str:
    """Current embedding model name from agent config (used as model
    identifier when storing vectors)."""
    try:
        return _resolve_config()["model_name"] or "unknown"
    except Exception:
        return "unknown"


# Legacy compatibility: keep the constant name but make it dynamic.
class _DefaultModelProxy:
    def __str__(self) -> str:
        return current_model_name()

    def __repr__(self) -> str:
        return current_model_name()

    def __eq__(self, other) -> bool:
        return str(self) == other

    def __bool__(self) -> bool:
        return bool(current_model_name() and current_model_name() != "unknown")


DEFAULT_DASHSCOPE_MODEL = _DefaultModelProxy()
DEFAULT_DIM = 1024


# Legacy callers pass `provider` arg; we ignore it (single bridge target).
def embed_texts(
    texts: list[str],
    *,
    provider: str = "qwenpaw",
    model: str | None = None,
    timeout_s: float = 30.0,
    api_key: str | None = None,
    batch_id: str | None = None,
) -> list[list[float]]:
    """Return one vector per input text via the agent's OpenAI-compatible
    embedding endpoint. Batched in a single HTTP call.

    Raises EmbeddingError subclasses on failure.
    """
    _ = provider  # legacy param, ignored
    if not texts:
        return []

    cfg = _resolve_config()
    api_key = api_key or cfg["api_key"]
    base_url = cfg["base_url"]
    model_name = model or cfg["model_name"]

    if not api_key or not base_url or not model_name:
        raise EmbeddingDisabled(
            "knowledge agent embedding_config is incomplete "
            "(set api_key/base_url/model_name in console)"
        )

    body: dict = {
        "model": model_name,
        "input": texts,
        "encoding_format": "float",
    }
    if cfg["use_dimensions"]:
        body["dimensions"] = cfg["dimensions"]

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib_request.Request(
        f"{base_url}/embeddings",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "qwenpaw-kb/0.1",
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
            raise EmbeddingRateLimit(f"{base_url} 429: {exc.reason}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id,
             error=f"HTTP {exc.code}: {exc.reason}")
        raise EmbeddingProviderError(
            f"{base_url} HTTP {exc.code}: {exc.reason}",
        ) from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        latency = _ms_since(started)
        reason_str = str(getattr(exc, "reason", exc))
        if isinstance(exc, TimeoutError) or "timed out" in reason_str.lower():
            _log(model_name, len(texts), latency, "timeout", batch_id,
                 error=reason_str)
            raise EmbeddingTimeout(f"{base_url} timeout: {reason_str}") from exc
        _log(model_name, len(texts), latency, "server_error", batch_id,
             error=reason_str)
        raise EmbeddingProviderError(
            f"{base_url} transport: {reason_str}",
        ) from exc

    latency = _ms_since(started)
    if not raw:
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error="empty body")
        raise EmbeddingInvalidResponse("empty response body")

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"decode: {exc}")
        raise EmbeddingInvalidResponse(
            f"could not decode response: {exc}",
        ) from exc

    try:
        items = data["data"]
        vectors = [item["embedding"] for item in items]
    except (KeyError, IndexError, TypeError) as exc:
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"shape: {exc}")
        raise EmbeddingInvalidResponse(
            f"unexpected shape: {exc}",
        ) from exc

    if len(vectors) != len(texts):
        _log(model_name, len(texts), latency, "invalid_response", batch_id,
             error=f"count mismatch: sent {len(texts)} got {len(vectors)}")
        raise EmbeddingInvalidResponse(
            f"embedding count mismatch: sent {len(texts)} got {len(vectors)}"
        )

    usage = data.get("usage") or {}
    tokens_in = int(
        usage.get("prompt_tokens", 0) or usage.get("total_tokens", 0) or 0,
    )
    _log(model_name, len(texts), latency, "success", batch_id,
         tokens_in=tokens_in)

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
    return dot / (math.sqrt(na) * math.sqrt(nb))


# Legacy compatibility shim: old `is_provider_available("dashscope")` callsite.
def is_provider_available(provider: str) -> bool:
    _ = provider
    return is_embedding_available()


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
        "provider": "qwenpaw-embedding",
        "model": model,
        "n_texts": n_texts,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "status": status,
    }
    if error:
        entry["error"] = error
    prefix = "WARN:[kb-embed]" if latency_ms > SLOW_CALL_THRESHOLD_MS else "[kb-embed]"
    print(f"{prefix} {json.dumps(entry, ensure_ascii=False)}", flush=True)
