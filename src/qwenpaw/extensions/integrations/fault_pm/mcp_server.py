"""
Managed MCP server for PM/operations APIs over HTTP.

Tools:
- pm_api_post_json(endpoint, payload): generic JSON POST caller
- pm_api_get(endpoint, params): generic GET caller
- get_pm_data_new(payload): compatibility wrapper for the PM endpoint
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_BASE_URL = ""
LEGACY_PM_DATA_ENDPOINT = "prod-api/resource/pm/getPmDataNew"
DEFAULT_TIMEOUT_SECONDS = 15.0


mcp = FastMCP("fault-pm-mcp")


def _is_true(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_headers(*, include_json_content_type: bool = True) -> dict[str, str]:
    headers = {"Accept": "application/json, text/plain, */*"}
    if include_json_content_type:
        headers["Content-Type"] = "application/json;charset=UTF-8"

    bearer_token = os.getenv("PM_API_BEARER_TOKEN", "").strip()
    if bearer_token:
        headers["Authorization"] = (
            bearer_token
            if bearer_token.lower().startswith("bearer ")
            else f"Bearer {bearer_token}"
        )

    cookie = os.getenv("PM_API_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie

    origin = os.getenv("PM_API_ORIGIN", "").strip()
    if origin:
        headers["Origin"] = origin

    referer = os.getenv("PM_API_REFERER", "").strip()
    if referer:
        headers["Referer"] = referer

    return headers


def _normalize_endpoint(endpoint: str) -> str:
    normalized = endpoint.strip().replace("\\", "/")
    if not normalized:
        return ""

    if normalized.startswith(("http://", "https://")):
        return normalized

    if re.match(r"^[A-Za-z]:/", normalized):
        marker = "/prod-api/"
        marker_pos = normalized.lower().find(marker)
        if marker_pos >= 0:
            normalized = normalized[marker_pos:]

    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    return normalized


def _build_request_url(base_url: str, endpoint: str) -> str:
    normalized_endpoint = _normalize_endpoint(endpoint)
    if normalized_endpoint.startswith(("http://", "https://")):
        return normalized_endpoint
    return urljoin(f"{base_url.rstrip('/')}/", normalized_endpoint.lstrip("/"))


async def _request_json(
    *,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_url = os.getenv("PM_API_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    timeout_seconds = float(
        os.getenv("PM_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)),
    )
    verify_ssl = _is_true(os.getenv("PM_API_VERIFY_SSL"), default=False)

    normalized_endpoint = _normalize_endpoint(endpoint)
    if not normalized_endpoint:
        return {
            "status_code": 0,
            "ok": False,
            "url": "",
            "error": "Missing endpoint.",
        }

    if not base_url and not normalized_endpoint.startswith(("http://", "https://")):
        return {
            "status_code": 0,
            "ok": False,
            "url": "",
            "error": "Missing PM_API_BASE_URL in .env.mcp.local.",
        }

    url = _build_request_url(base_url, endpoint)
    method_upper = method.strip().upper()
    headers = _build_headers(include_json_content_type=method_upper != "GET")

    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=verify_ssl,
            trust_env=False,
        ) as client:
            request_kwargs: dict[str, Any] = {"headers": headers}
            if method_upper == "GET":
                request_kwargs["params"] = params or {}
            else:
                request_kwargs["json"] = payload or {}

            response = await client.request(method_upper, url, **request_kwargs)

        try:
            body: Any = response.json()
        except ValueError:
            body = {"raw_text": response.text}

        return {
            "status_code": response.status_code,
            "ok": response.is_success,
            "url": url,
            "data": body,
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "ok": False,
            "url": url,
            "error": str(exc),
        }


@mcp.tool(description="Generic PM API POST request with a JSON payload.")
async def pm_api_post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await _request_json(method="POST", endpoint=endpoint, payload=payload)


@mcp.tool(description="Generic PM API GET request with query params.")
async def pm_api_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _request_json(method="GET", endpoint=endpoint, params=params or {})


@mcp.tool(description="Compatibility wrapper for the PM getPmDataNew endpoint.")
async def get_pm_data_new(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.getenv("PM_API_ENDPOINT", "").strip() or LEGACY_PM_DATA_ENDPOINT
    return await _request_json(method="POST", endpoint=endpoint, payload=payload)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
