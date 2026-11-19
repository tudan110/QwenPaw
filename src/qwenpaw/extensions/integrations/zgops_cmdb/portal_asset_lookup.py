"""Bounded CMDB asset lookup with the authenticated Portal caller's identity."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from urllib.parse import urlsplit

import httpx
from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.constant import EnvVarLoader
from qwenpaw.extensions.api.access_session import AccessIdentity, CURRENT_IDENTITY
from qwenpaw.extensions.api.chat_isolation import chat_isolation_enabled

_HUMAN_SOURCES = {"inoe", "mixed", "qwenpaw"}
_EXACT_NAME = re.compile(r"[\w][\w. -]{0,159}")
_MAX_RESULTS = 20

PORTAL_ASSET_LOOKUP_HINT = (
    "Portal CMDB 精确资产查询：用户提供了具体设备或资产名称时，请直接调用 "
    "lookup_portal_cmdb_asset(name=资产全名)。这个只读工具使用当前 Portal "
    "登录用户的智观权限，不受通用 Skill MCP/脚本路由的影响。名称查询必须以该工具"
    "的响应为准；若查询失败、拒绝或没有可见匹配，不要换凭据、换脚本或猜测数据。"
    "其他 CMDB 操作仍遵循 Skill execution routes。"
)


def _human_identity() -> AccessIdentity | None:
    identity = CURRENT_IDENTITY.get()
    if identity and identity.source in _HUMAN_SOURCES and identity.user_id:
        return identity
    return None


def portal_asset_lookup_available(
    agent_id: str,
    effective_skills: Collection[str],
    request_context: Mapping[str, object],
) -> bool:
    return bool(
        agent_id == "gateway"
        and "zgops-cmdb" in effective_skills
        and request_context.get("channel") == "console"
        and chat_isolation_enabled()
        and _human_identity() is not None
    )


def _response(status: str, message: str, **fields) -> ToolChunk:
    payload = {"status": status, "message": message, **fields}
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


def _query_url() -> str:
    base = EnvVarLoader.get_str("INOE_API_BASE_URL", "").strip().rstrip("/")
    target = urlsplit(base)
    if (
        target.scheme not in {"http", "https"} or not target.hostname
        or target.username is not None or target.password is not None
        or target.query or target.fragment
    ):
        raise ValueError("Invalid configured INOE API base")
    return f"{base}/cmdb/api/v0.1/ci/s"


async def lookup_portal_cmdb_asset(name: str) -> ToolChunk:
    """按完整资产名称执行只读 CMDB 精确查询，返回当前登录用户可见的资产。

    Args:
        name: 完整设备名或资产名，不传通配符、筛选表达式或连接信息。
    """
    identity = _human_identity()
    if not chat_isolation_enabled() or not identity or not identity.inoe_token:
        return _response("authentication_required", "需要当前用户的智观业务凭据，请重新登录。")
    name = name.strip()
    if not _EXACT_NAME.fullmatch(name):
        return _response("invalid_name", "请提供一个明确的完整资产名称。")
    try:
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=False, trust_env=False,
        ) as client:
            response = await client.get(
                _query_url(),
                headers={
                    "Authorization": f"Bearer {identity.inoe_token}",
                    "Accept": "application/json",
                },
                params={
                    "q": f"name:{name}", "page": 1,
                    "count": _MAX_RESULTS, "fl": "name",
                },
            )
        status = response.status_code
        if response.is_success:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid CMDB query envelope")
            # Some INOE gateways return HTTP 200 for business auth errors.
            status = str(data.get("code", 200))
        else:
            data = {}
        if str(status) == "401":
            return _response("authentication_required", "智观 CMDB 未接受当前用户凭据，请重新登录。")
        if str(status) == "403":
            return _response("access_denied", "智观 CMDB 拒绝了当前登录用户的查询请求。")
        response.raise_for_status()
        if status not in {"0", "200"}:
            raise ValueError("Unsuccessful CMDB business response")
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        rows = payload.get("result")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Invalid CMDB query envelope")
    except (httpx.HTTPError, ValueError):
        return _response("query_failed", "智观 CMDB 未返回可用的查询结果。")
    matches = [
        {
            key: row[key] for key in ("_id", "name", "ci_type", "ci_type_alias")
            if isinstance(row.get(key), int)
            or (isinstance(row.get(key), str) and len(row[key]) <= 160)
        }
        for row in rows[:_MAX_RESULTS]
        if isinstance(row.get("name"), str) and row["name"].casefold() == name.casefold()
    ]
    if not matches:
        return _response("no_visible_match", "智观 CMDB 没有返回当前用户可见的同名资产。")
    return _response("ok", "查询到当前用户可见的同名资产。", assets=matches)
