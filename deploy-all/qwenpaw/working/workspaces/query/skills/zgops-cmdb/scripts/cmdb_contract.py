"""Shared contracts for current CMDB responses and legacy CI wrappers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlencode


class CmdbContractError(RuntimeError):
    """A business failure or an invalid CMDB response, not an empty result."""

    def __init__(self, message: str, code: int = 500) -> None:
        super().__init__(message)
        self.code = code


def ensure_success(payload: Any) -> Any:
    if isinstance(payload, dict) and "_id" not in payload:
        code = payload.get("code")
        if code not in (None, 200, "200") or payload.get("success") is False:
            message = (
                payload.get("message")
                or payload.get("msg")
                or "CMDB query failed"
            )
            error_code = code if isinstance(code, int) else 500
            raise CmdbContractError(f"CMDB code={code}: {message}", error_code)
    return payload


def ci_detail(payload: Any) -> dict[str, Any]:
    ensure_success(payload)
    if isinstance(payload, dict):
        for key in ("ci", "result"):
            item = payload.get(key)
            if isinstance(item, dict) and item:
                ensure_success(item)
                return item
        if any(key in payload for key in ("_id", "id", "ci_type", "_type")):
            return payload
    raise CmdbContractError("CI detail response has no CI object")


def ci_items(payload: Any) -> list[dict[str, Any]]:
    ensure_success(payload)
    if isinstance(payload, dict):
        for key in ("result", "cis"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise CmdbContractError("CI search response has no CI list")
    if any(not isinstance(item, dict) for item in payload):
        raise CmdbContractError(
            "CI search returned a non-object item; check selected fields"
        )
    return payload


def catalog_items(payload: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    ensure_success(payload)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, (dict, list)):
            return catalog_items(data, keys)
        for key in keys:
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list) or any(
        not isinstance(item, dict) for item in payload
    ):
        raise CmdbContractError("CMDB metadata response has no object list")
    return payload


def fetch_catalog_pages(
    request_json: Callable[[str], Any],
    path: str,
    keys: Iterable[str] = ("ci_types", "result", "types", "items"),
) -> list[dict[str, Any]]:
    collected: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        payload = request_json(
            path + "?" + urlencode({"per_page": 200, "page": page})
        )
        rows = catalog_items(payload, keys)
        if any(
            isinstance(row.get("id"), bool) or row.get("id") is None
            for row in rows
        ):
            raise CmdbContractError("Model catalog contains an invalid ID")
        identities = {str(row["id"]) for row in rows}
        if rows and not identities - collected.keys():
            raise CmdbContractError(
                "Model catalog pagination made no progress"
            )
        for row in rows:
            collected[str(row["id"])] = row
        expected = (
            payload.get("numfound") if isinstance(payload, dict) else None
        )
        if expected is not None:
            if isinstance(expected, (bool, float)):
                raise CmdbContractError("Invalid numfound in model catalog")
            try:
                expected = int(expected)
            except (TypeError, ValueError) as error:
                raise CmdbContractError(
                    "Invalid numfound in model catalog"
                ) from error
            if expected < 0:
                raise CmdbContractError(
                    "Invalid negative numfound in model catalog"
                )
        if expected is None or len(collected) >= expected:
            return list(collected.values())
        if not rows:
            raise CmdbContractError("Model catalog pagination is incomplete")
        page += 1


def ci_identity(item: Mapping[str, Any]) -> str:
    value = item.get("_id", item.get("id"))
    if isinstance(value, bool) or value is None:
        raise CmdbContractError("CI item has no valid instance ID")
    text = str(value).strip()
    if not text:
        raise CmdbContractError("CI item has no valid instance ID")
    return text


def merge_cis(*collections: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for collection in collections:
        for item in collection:
            identity = ci_identity(item)
            if identity not in merged:
                merged[identity] = dict(item)
            else:
                for key, value in item.items():
                    if key not in merged[identity]:
                        merged[identity][key] = value
            directions = list(merged[identity].get("_query_directions", []))
            for direction in item.get("_query_directions", []):
                if direction not in directions:
                    directions.append(direction)
            if directions:
                merged[identity]["_query_directions"] = directions
    return list(merged.values())


def fetch_ci_pages(
    request_json: Callable[[str], Any],
    path: str,
    params: Mapping[str, Any],
) -> list[dict[str, Any]]:
    count = params.get("count", 10000)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    query = dict(params)
    query["count"] = count
    query["page"] = 1
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    returned = 0
    while True:
        payload = request_json(path + "?" + urlencode(query, safe=",:_"))
        items = ci_items(payload)
        expected = (
            payload.get("numfound") if isinstance(payload, dict) else None
        )
        if expected is not None:
            if isinstance(expected, (bool, float)):
                raise CmdbContractError("Invalid numfound in CI response")
            try:
                expected = int(expected)
            except (TypeError, ValueError) as error:
                raise CmdbContractError(
                    "Invalid numfound in CI response"
                ) from error
            if expected < 0:
                raise CmdbContractError(
                    "Invalid negative numfound in CI response"
                )
        if not items:
            if expected is not None and returned < expected:
                raise CmdbContractError(
                    "CI pagination ended before numfound was reached"
                )
            break
        identities = {ci_identity(item) for item in items}
        if not identities - seen:
            raise CmdbContractError(
                "CI pagination made no progress; results are incomplete"
            )
        seen.update(identities)
        collected.extend(items)
        returned = len(seen)
        if expected is not None and returned >= expected:
            break
        if expected is None and len(items) < count:
            break
        query["page"] += 1
    return merge_cis(collected)


def fetch_relations(
    request_json: Callable[[str], Any],
    root_id: Any,
    *,
    reverse: int = 0,
    levels: Iterable[int] = (1, 2, 3),
    count: int = 10000,
) -> list[dict[str, Any]]:
    if (
        isinstance(reverse, bool)
        or not isinstance(reverse, int)
        or reverse not in (0, 1)
    ):
        raise ValueError("reverse must be 0 or 1")
    selected = list(dict.fromkeys(levels))
    if not selected or any(
        isinstance(level, bool) or not isinstance(level, int) or level < 1
        for level in selected
    ):
        raise ValueError("levels must contain positive integers")
    params = {
        "root_id": ci_identity({"_id": root_id}),
        "level": ",".join(map(str, selected)),
        "count": count,
    }
    if reverse:
        params["reverse"] = reverse
    items = fetch_ci_pages(request_json, "/api/v0.1/ci_relations/s", params)
    direction = "reverse" if reverse else "forward"
    return [dict(item, _query_directions=[direction]) for item in items]
