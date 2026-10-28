#!/usr/bin/env python3
"""Retrieve supplementary knowledge through the existing Portal API."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

DEFAULT_TIMEOUT_SECONDS = 60


def _last_api_base_url() -> str:
    # Importing qwenpaw bootstraps persisted envs and acquires a restore lock.
    # A standalone read-only query only needs the persisted endpoint.
    working_dir = os.environ.get(
        "QWENPAW_WORKING_DIR", os.environ.get("COPAW_WORKING_DIR", "")
    )
    if working_dir:
        root = Path(working_dir).expanduser().resolve()
    else:
        legacy = Path.home() / ".copaw"
        root = legacy if legacy.exists() else Path.home() / ".qwenpaw"
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("应用配置不是 JSON 对象，无法读取应用地址")
    address = config.get("last_api") or {}
    if not isinstance(address, dict):
        raise ValueError("应用地址配置格式异常")
    host = address.get("host", config.get("last_api_host"))
    port = address.get("port", config.get("last_api_port"))
    if not host or port is None:
        raise ValueError(
            "未取得应用地址，请配置 ALARM_ANALYST_KNOWLEDGE_API_BASE_URL"
        )
    if not isinstance(host, str) or not host.strip():
        raise ValueError("应用地址的主机名无效")
    port_text = str(port)
    if (
        isinstance(port, bool)
        or not port_text.isascii()
        or not port_text.isdigit()
        or not 1 <= int(port_text) <= 65535
    ):
        raise ValueError("应用地址的端口须为 1～65535 的整数")
    port = int(port_text)
    host = host.strip()
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1" if host == "0.0.0.0" else "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/api/portal"


def _resolve_base_url(value: str | None) -> str:
    base = (
        (
            value
            or os.getenv("ALARM_ANALYST_KNOWLEDGE_API_BASE_URL", "").strip()
            or _last_api_base_url()
        )
        .strip()
        .rstrip("/")
    )
    parts = urlsplit(base)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "知识库 API 地址须为 HTTP(S) 地址，不得包含凭据、查询参数或片段"
        )
    return base


def _validate_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("知识库响应不是 JSON 对象")
    if not isinstance(payload.get("query_id"), str) or not payload["query_id"]:
        raise ValueError("知识库响应缺少 query_id")
    evidence = payload.get("relevant_evidence")
    flags = payload.get("flags")
    if not isinstance(evidence, list) or not isinstance(flags, dict):
        raise ValueError("知识库响应缺少证据列表或状态标记")
    if not isinstance(flags.get("insufficient_evidence"), bool):
        raise ValueError("知识库响应缺少证据不足标记")
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("知识库证据格式异常")
        citation = item.get("citation")
        if (
            not isinstance(item.get("evidence_id"), str)
            or not item["evidence_id"].strip()
            or not isinstance(citation, dict)
            or not isinstance(citation.get("source_label"), str)
            or not citation["source_label"].strip()
            or not any(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("chunk_text", "chunk_summary")
            )
        ):
            raise ValueError("知识库证据缺少标识、来源或正文")
    return payload


def query_knowledge(
    query: str,
    *,
    api_base_url: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query": query.strip(),
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "attempted": False,
    }
    try:
        if not result["query"]:
            raise ValueError("知识库检索条件不能为空")
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv(
                "ALARM_ANALYST_KNOWLEDGE_TIMEOUT_SECONDS",
                str(DEFAULT_TIMEOUT_SECONDS),
            )
        )
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("知识库检索超时须为大于 0 的有限秒数")
        base_url = _resolve_base_url(api_base_url)
        headers = {"Accept": "application/json", "X-Agent-Id": "fault"}
        token = os.getenv("ALARM_ANALYST_KNOWLEDGE_API_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        result["attempted"] = True
        # Do not retry or follow redirects: failures must remain visible,
        # and a redirect must not forward fault context to another service.
        with requests.post(
            f"{base_url}/knowledge-base/query",
            json={"query": result["query"], "filters": {}},
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                result.update(
                    status="error",
                    error=f"知识库检索失败：HTTP {response.status_code}",
                )
                return result
            payload = _validate_response(response.json())
        if not payload["relevant_evidence"]:
            status = "no_match"
        elif payload["flags"]["insufficient_evidence"]:
            status = "insufficient_evidence"
        else:
            status = "retrieved"
        result.update(status=status, result=payload)
        return result
    except requests.Timeout:
        error = "知识库检索超时，未取得补充资料"
    except requests.exceptions.JSONDecodeError:
        error = "知识库响应不是有效 JSON，未取得补充资料"
    except requests.RequestException:
        error = "知识库检索连接或传输失败，未取得补充资料"
    except (ValueError, ImportError, OSError) as exc:
        # Request exceptions above deliberately omit URLs, headers and bodies.
        error = f"知识库检索配置或响应异常：{exc}"
    result.update(status="error", error=error)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", required=True, help="故障对象、现象或关键词"
    )
    parser.add_argument(
        "--api-base-url",
        help="Portal API 根地址（含 /api/portal）；默认读取环境变量或应用地址",
    )
    parser.add_argument("--timeout", type=float, help="单次请求超时秒数")
    args = parser.parse_args(argv)
    result = query_knowledge(
        args.query,
        api_base_url=args.api_base_url,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "error":
        print(result["error"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
