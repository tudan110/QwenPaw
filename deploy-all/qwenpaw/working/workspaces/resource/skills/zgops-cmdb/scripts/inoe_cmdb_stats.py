#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INOE 网关 CMDB 统计接口查询。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, parse_qsl, urlsplit

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cmdb_output import redact_output, run_cli, safe_print as print
from cmdb_contract import CmdbContractError, catalog_items, ensure_success, fetch_catalog_pages


RESOURCE_TYPE_MAP = {
    "database": {"label": "数据库", "type_kind": "group"},
    "db": {"label": "数据库", "type_kind": "group"},
    "数据库": {"label": "数据库", "type_kind": "group"},
    "middleware": {"label": "中间件", "type_kind": "group"},
    "middle": {"label": "中间件", "type_kind": "group"},
    "中间件": {"label": "中间件", "type_kind": "group"},
    "network": {"label": "networkdevice", "type_kind": "model"},
    "network_device": {"label": "networkdevice", "type_kind": "model"},
    "网络设备": {"label": "networkdevice", "type_kind": "model"},
    "网络": {"label": "networkdevice", "type_kind": "model"},
    "server": {"label": "计算资源", "type_kind": "group"},
    "compute": {"label": "计算资源", "type_kind": "group"},
    "计算资源": {"label": "计算资源", "type_kind": "group"},
    "服务器": {"label": "计算资源", "type_kind": "group"},
    "os": {"label": "operatingsystem", "type_kind": "model"},
    "operating_system": {"label": "operatingsystem", "type_kind": "model"},
    "操作系统": {"label": "operatingsystem", "type_kind": "model"},
}

DEFAULT_STAT_PATHS = {
    "count": "/cmdb/api/v0.1/ci/count",
    "group": "/cmdb/api/v0.1/ci/count/group",
    "child": "/cmdb/api/v0.1/ci/count/child",
    "child-group": "/cmdb/api/v0.1/ci/count/child/group",
    "group-attr": "/cmdb/api/v0.1/ci/count/group/attr",
}

STAT_PATH_ENV = {
    "count": "INOE_CMDB_COUNT_PATH",
    "group": "INOE_CMDB_COUNT_GROUP_PATH",
    "child": "INOE_CMDB_COUNT_CHILD_PATH",
    "child-group": "INOE_CMDB_COUNT_CHILD_GROUP_PATH",
    "group-attr": "INOE_CMDB_COUNT_GROUP_ATTR_PATH",
}

ATTR_ALIASES = {
    "vendor": "vendor",
    "manufacturer": "vendor",
    "manufacture": "vendor",
    "factory": "vendor",
    "厂商": "vendor",
    "厂家": "vendor",
    "制造商": "vendor",
    "brand": "vendor",
    "品牌": "vendor",
    "db_type": "db_type",
    "database_type": "db_type",
    "数据库类型": "db_type",
    "os_type": "os_type",
    "系统类型": "os_type",
    "dev_class": "dev_class",
    "设备类型": "dev_class",
}

COUNT_FIELDS = [
    ("total", "总数"),
    ("normalCount", "正常"),
    ("abnormalCount", "异常"),
    ("emergencyCount", "紧急"),
    ("severeCount", "严重"),
    ("minorCount", "次要"),
    ("warningCount", "预警"),
    ("unmonitoredCount", "未监控"),
]


# INOE_* / ZGOPS_* 凭证由设置页统一管理并物化到 os.environ（子进程继承）。
# 不再读取技能目录下的 .env。


def normalize_resource(resource_type: str | None, type_id: str | None) -> dict[str, Any]:
    if type_id:
        return {"type_id": str(type_id), "label": f"type={type_id}", "type_source": "explicit"}
    raw = (resource_type or "database").strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    alias = RESOURCE_TYPE_MAP.get(key)
    return {
        **(alias or {"label": raw}),
        "type_id": None,
        "type_source": "unresolved",
    }


def normalize_attr(attr: str | None) -> str | None:
    if not attr:
        return None
    raw = attr.strip()
    key = raw.lower().replace("-", "_").replace(" ", "_")
    return ATTR_ALIASES.get(key, raw)


def make_error(code: int, msg: str) -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": None}


def api_base_url() -> str:
    return (os.getenv("INOE_CMDB_API_BASE_URL") or os.getenv("INOE_API_BASE_URL") or "").strip().rstrip("/")


def api_token() -> str:
    return (os.getenv("INOE_API_TOKEN") or "").strip()


def curl_enabled() -> bool:
    return os.getenv("INOE_ENABLE_CURL_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}


def stat_path(stat: str) -> str:
    return (os.getenv(STAT_PATH_ENV.get(stat, "")) or DEFAULT_STAT_PATHS[stat]).strip()


def ci_types_path() -> str:
    return (os.getenv("INOE_CMDB_TYPES_PATH") or "/cmdb/api/v0.1/ci_types").strip()


def ci_type_groups_path() -> str:
    return (os.getenv("INOE_CMDB_TYPE_GROUPS_PATH") or "/cmdb/api/v0.1/ci_types/groups").strip()


def parse_json_response(text: str) -> dict[str, Any]:
    if not text.strip():
        return make_error(500, "接口返回空响应")
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    return {"code": 200, "msg": "操作成功", "data": data}


def curl_get(url: str, headers: dict[str, str], timeout_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(delete=False) as body_file:
        body_path = body_file.name
    args = [
        "curl",
        "-sS",
        "-X",
        "GET",
        "--connect-timeout",
        str(timeout_seconds),
        "--max-time",
        str(timeout_seconds),
        "-o",
        body_path,
        "-w",
        "%{http_code}",
    ]
    for key, value in headers.items():
        args.extend(["-H", f"{key}: {value}"])
    args.append(url)
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=max(timeout_seconds + 5, 10),
            check=False,
        )
        if completed.returncode != 0:
            return make_error(500, (completed.stderr or completed.stdout or "curl 请求失败").strip())
        status_code = int((completed.stdout or "").strip() or "0")
        response_text = Path(body_path).read_text(encoding="utf-8", errors="replace")
        if status_code >= 400:
            return make_error(status_code, response_text[:500])
        return parse_json_response(response_text)
    except json.JSONDecodeError as error:
        return make_error(500, f"curl 响应解析失败: {error}")
    except subprocess.TimeoutExpired:
        return make_error(408, "请求超时")
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass


def request_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    base_url = api_base_url()
    token = api_token()
    if not base_url:
        return make_error(400, "未设置 INOE_API_BASE_URL")
    if not token:
        return make_error(401, "未设置 INOE_API_TOKEN")
    if base_url.endswith("/cmdb") and path.startswith("/cmdb/"):
        path = path[len("/cmdb"):]
    url = f"{base_url}{path}?{urlencode(params)}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/plain, */*"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code >= 400:
            return make_error(response.status_code, response.text[:500])
        return parse_json_response(response.text)
    except (requests.ConnectionError, requests.Timeout, OSError):
        if curl_enabled():
            return curl_get(url, headers, 30)
        return make_error(408, "请求失败且 curl fallback 未启用")
    except json.JSONDecodeError as error:
        return make_error(500, f"响应解析失败: {error}")
    except requests.RequestException as error:
        if curl_enabled():
            return curl_get(url, headers, 30)
        return make_error(500, f"请求异常: {error}")


def list_from_payload(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    candidates: list[Any] = [payload.get("data"), payload]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
        if isinstance(candidate, dict):
            for key in keys:
                value = candidate.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
    return []


def normalize_match_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def match_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = normalize_match_text(value)
        if text:
            tokens.add(text)
            tokens.add(text.replace("_", ""))
    return tokens


def resource_match_tokens(resource_type: str | None) -> set[str]:
    raw = (resource_type or "database").strip()
    tokens = match_tokens(raw)
    fallback = RESOURCE_TYPE_MAP.get(normalize_match_text(raw))
    if fallback:
        tokens.update(match_tokens(fallback.get("label"), fallback.get("type_id")))
    return tokens


def query_type_catalog() -> dict[str, Any]:
    groups_payload = request_get(ci_type_groups_path(), {"need_other": "true"})
    groups = catalog_items(groups_payload, ("groups", "ci_type_groups", "ciTypeGroups"))
    def request_catalog(uri: str) -> dict[str, Any]:
        parsed = urlsplit(uri)
        params = {key: int(value) for key, value in parse_qsl(parsed.query)}
        return request_get(parsed.path, params)

    ci_types = fetch_catalog_pages(
        request_catalog, ci_types_path(), ("ci_types", "ciTypes", "types", "result")
    )
    return {
        "groups": groups,
        "ci_types": ci_types,
    }


def resolve_resource(
    resource_type: str | None,
    type_id: str | None,
    *,
    dynamic_type: bool = True,
    type_kind: str | None = None,
) -> dict[str, Any]:
    if type_kind not in (None, "group", "model"):
        raise ValueError("type_kind 必须为 group 或 model")
    raw = (resource_type or "database").strip()
    if not type_id and raw.isdigit():
        type_id = raw
    if type_id and (not str(type_id).isdigit() or int(type_id) < 1):
        raise ValueError("type_id 必须为正整数")
    if not dynamic_type:
        if not type_id or not type_kind:
            raise ValueError("禁用元数据解析时必须提供 --type_id 和 --type_kind；不再使用固定 ID 映射")
        return {
            "type_id": str(type_id), "label": f"type={type_id}",
            "type_source": "explicit", "type_kind": type_kind, "members": [],
        }
    catalog = query_type_catalog()
    alias = RESOURCE_TYPE_MAP.get(normalize_match_text(raw))
    if not type_id and type_kind is None and alias:
        type_kind = alias["type_kind"]
    wanted = match_tokens(raw, alias.get("label") if alias else None)
    if alias and alias["label"] == "数据库":
        wanted.update(match_tokens("数据存储"))
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for kind, entries in (("group", catalog["groups"]), ("model", catalog["ci_types"])):
        if type_kind and kind != type_kind:
            continue
        for item in entries:
            if type_id:
                score = 100 if str(item.get("id")) == str(type_id) else 0
            else:
                tokens = match_tokens(item.get("name"), item.get("alias"))
                score = 100 if wanted & tokens else 0
                if kind == "group" and alias and not score:
                    score = 50 if any(
                        token.endswith(target) for token in tokens for target in wanted
                        if target
                    ) else 0
            if score:
                candidates.append((score, kind, item))
    if not candidates:
        raise ValueError(f"未找到 {type_kind or '模型/分组'}：{type_id or raw}；请从 types 目录选择实际名称或 ID")
    best = max(score for score, _, _ in candidates)
    selected = [(kind, item) for score, kind, item in candidates if score == best]
    if len(selected) != 1:
        choices = "、".join(
            f"{kind}:{item.get('id')}({item.get('name') or item.get('alias')})"
            for kind, item in selected
        )
        raise ValueError(f"模型/分组有多个候选：{choices}；请明确 --type_id 和 --type_kind")
    kind, item = selected[0]
    members = []
    if kind == "group":
        by_id = {str(model["id"]): model for model in catalog["ci_types"]}
        for child in item.get("ci_types", []) or []:
            child_id = child.get("id") if isinstance(child, dict) else child
            model = by_id.get(str(child_id))
            if model is None:
                raise CmdbContractError(f"分组引用的模型 {child_id} 不在完整模型目录中")
            if not any(str(member["id"]) == str(model["id"]) for member in members):
                members.append(model)
    return {
        "type_id": str(item["id"]),
        "label": str(item.get("alias") or item.get("name") or f"type={item['id']}"),
        "type_source": "explicit" if type_id else ("cmdb_group" if kind == "group" else "ci_type"),
        "type_kind": kind,
        "members": members,
    }


def query_types() -> dict[str, Any]:
    try:
        catalog = query_type_catalog()
    except (CmdbContractError, ValueError) as error:
        return make_error(getattr(error, "code", 400), str(error))
    rows: list[dict[str, Any]] = []
    for group in catalog["groups"]:
        children = [
            {
                "id": child.get("id"),
                "name": child.get("name"),
                "alias": child.get("alias"),
            }
            for child in group.get("ci_types", []) or []
            if isinstance(child, dict)
        ]
        rows.append({
            "id": group.get("id"),
            "name": group.get("name") or group.get("alias"),
            "kind": "group",
            "children": children,
        })
    return {
        "code": 200,
        "msg": "操作成功",
        "data": rows,
        "_query": {
            "stat": "types",
            "path": ci_type_groups_path(),
            "types_path": ci_types_path(),
        },
    }


def _aggregate_attribute_rows(
    payloads: list[dict[str, Any]], *, pure_count: bool, label: str,
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    fields = ["count"] if pure_count else [field for field, _ in COUNT_FIELDS]
    for payload in payloads:
        ensure_success(payload)
        for row in rows_from_payload(payload):
            if pure_count and not {"type", "count"} <= row.keys():
                raise CmdbContractError("属性数量统计缺少 type/count 字段")
            value = row.get("type") if pure_count else row.get("resourceClass") or row.get("resourceType")
            name = "未知" if value in (None, "") else str(value)
            target = combined.setdefault(
                name, {"type": name} if pure_count else {"resourceClass": name, "resourceType": label}
            )
            for field in fields:
                if field not in row:
                    continue
                value = row[field]
                if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
                    raise CmdbContractError(f"统计字段 {field} 不是非负整数")
                target[field] = target.get(field, 0) + int(value)
    return list(combined.values())


def query_stat(
    stat: str, resource_type: str | None, type_id: str | None, attr: str | None,
    *, dynamic_type: bool = True, type_kind: str | None = None,
) -> dict[str, Any]:
    if stat not in DEFAULT_STAT_PATHS:
        return make_error(400, f"不支持的统计类型: {stat}")
    normalized_attr = normalize_attr(attr)
    if normalized_attr and (
        normalized_attr.lower() in (
            "bearer_token", "login_pwd", "password", "passwd", "pwd", "token",
            "api_key", "access_token", "refresh_token", "client_secret",
            "secret", "private_key", "authorization",
        )
        or normalized_attr.lower().endswith(("_password", "_pwd", "_token"))
    ):
        return make_error(400, "不支持按凭证属性分组")
    if stat in ("child-group", "group-attr") and not normalized_attr:
        return make_error(400, f"{stat} 必须指定 --attr")
    if stat in ("count", "child") and normalized_attr:
        return make_error(400, f"{stat} 不接受 --attr，请使用 group、child-group 或 group-attr")
    if not dynamic_type and (not type_id or not type_kind):
        return make_error(400, "禁用元数据解析时必须提供 --type_id 和 --type_kind")
    try:
        preferred_kind = type_kind
        if preferred_kind is None and type_id and stat != "group":
            preferred_kind = "group" if stat == "count" else "model"
        resource = resolve_resource(
            resource_type, type_id, dynamic_type=dynamic_type,
            type_kind=preferred_kind,
        )
        if stat == "child" and resource["type_kind"] != "model":
            raise ValueError("child 只统计具体模型；资源分组请使用 count 或 group")
        effective = stat
        if resource["type_kind"] == "model" and stat in ("count", "group"):
            effective = "child-group" if normalized_attr else "child"
        path = stat_path(effective)
        model_ids = []
        if resource["type_kind"] == "group" and normalized_attr:
            if not dynamic_type:
                raise ValueError("分组属性统计需要完整模型目录，不能禁用元数据解析")
            path = stat_path("group-attr" if stat == "group-attr" else "child-group")
            model_ids = [str(model["id"]) for model in resource["members"]]
            payloads = []
            for model_id in model_ids:
                item = request_get(path, {"type": model_id, "attr": normalized_attr})
                ensure_success(item)
                payloads.append(item)
            payload = {
                "code": 200, "msg": "操作成功",
                "data": _aggregate_attribute_rows(
                    payloads, pure_count=stat == "group-attr", label=resource["label"],
                ),
            }
        else:
            params: dict[str, Any] = {"type": resource["type_id"]}
            if normalized_attr:
                params["attr"] = normalized_attr
            payload = request_get(path, params)
            ensure_success(payload)
        if not isinstance(payload.get("data"), (list, dict)):
            raise CmdbContractError("统计响应缺少 data 对象或列表")
        count_field = "count" if stat == "group-attr" else "total"
        for row in rows_from_payload(payload):
            value = row.get(count_field)
            if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
                raise CmdbContractError(f"统计响应缺少有效的 {count_field} 数量")
    except (ValueError, CmdbContractError) as error:
        return make_error(getattr(error, "code", 400), str(error))
    payload["_query"] = {
        "stat": stat,
        "resource_type": resource["label"],
        "type": resource["type_id"],
        "type_source": resource.get("type_source"),
        "type_kind": resource["type_kind"],
        "model_ids": model_ids,
        "result_kind": "ci-count" if stat == "group-attr" else "resource-alarm-status",
        "attr": normalized_attr,
        "path": path,
    }
    return payload


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        if any(not isinstance(item, dict) for item in data):
            raise CmdbContractError("统计 data 列表包含非对象，不能当作空结果")
        return data
    if isinstance(data, dict):
        return [data]
    return []


def value_text(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def row_name(row: dict[str, Any], index: int) -> str:
    for key in ("name", "resourceClass", "resourceType", "vendor", "alias", "type"):
        if row.get(key):
            return str(row[key])
    return f"分组{index}"


def markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无该查询范围的分组数据，不能据此判断资源数量为零。"
    if all("count" in row and "type" in row for row in rows):
        lines = ["| 分组 | 资源数量 |", "| --- | --- |"]
        lines.extend(
            f"| {value_text(row['type'])} | {value_text(row['count'])} |"
            for row in rows
        )
        return "\n".join(lines)
    headers = ["分组", *[label for _, label in COUNT_FIELDS]]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for index, row in enumerate(rows, start=1):
        values = [row_name(row, index), *[value_text(row.get(field)) for field, _ in COUNT_FIELDS]]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def build_chart(title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = [row_name(row, index) for index, row in enumerate(rows, start=1)]
    totals = [row.get("count", row.get("total")) or 0 for row in rows]
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": 48, "right": 24, "bottom": 72, "top": 56},
        "xAxis": {"type": "category", "data": names, "axisLabel": {"rotate": 25}},
        "yAxis": {"type": "value", "name": "数量"},
        "series": [{"name": "总数", "type": "bar", "barMaxWidth": 42, "data": totals}],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    query = payload.get("_query") or {}
    if query.get("stat") == "types":
        return render_types_markdown(payload)

    title = f"{query.get('resource_type', '资源')}统计"
    if query.get("attr") == "vendor":
        title = f"{query.get('resource_type', '资源')}制造商分布统计"
    elif query.get("attr"):
        title = f"{query.get('resource_type', '资源')}按 {query.get('attr')} 分布统计"

    if payload.get("code") not in {None, 200}:
        return f"# {title}\n\n查询失败：{payload.get('msg') or payload}"

    rows = rows_from_payload(payload)
    model_ids = query.get("model_ids") or []
    query_description = (
        f"{query.get('path')}，分别查询模型 ID：{', '.join(model_ids)}"
        if model_ids
        else f"{query.get('path')}?type={query.get('type')}"
        + (f"&attr={query.get('attr')}" if query.get("attr") else "")
    )
    lines = [
        f"# {title}",
        "",
        f"- 接口：`{query_description}`",
        f"- 类型来源：`{query.get('type_source') or '-'}`",
        f"- 目标类别：`{query.get('type_kind') or '-'}`",
        "- 统计口径：" + (
            "按属性分组的 CI 数量。"
            if query.get("result_kind") == "ci-count"
            else "资源告警状态数量，不是告警事件条数。"
        ),
        f"- 返回分组：{len(rows)} 个",
        "",
        markdown_table(rows),
    ]
    if rows:
        lines.extend(["", "```echarts", json.dumps(build_chart(title, rows), ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines)


def render_types_markdown(payload: dict[str, Any]) -> str:
    rows = rows_from_payload(payload)
    lines = [
        "# CMDB 资源类型目录",
        "",
        f"- 分组接口：`{(payload.get('_query') or {}).get('path')}`",
        f"- 分组数量：{len(rows)}",
        "",
        "| 分组ID | 分组名称 | 子模型 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        children = row.get("children") or []
        child_text = "、".join(
            f"{child.get('alias') or child.get('name')}({child.get('id')})"
            for child in children
            if isinstance(child, dict)
        )
        lines.append(f"| {value_text(row.get('id'))} | {value_text(row.get('name'))} | {child_text or '-'} |")
    query = payload.get("_query") or {}
    errors = [query.get("groups_error"), query.get("types_error")]
    errors = [str(error) for error in errors if error]
    if errors:
        lines.extend(["", "元数据查询提示：" + "；".join(errors)])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 INOE 网关 CMDB 统计接口")
    parser.add_argument("stat", nargs="?", default="group", choices=sorted([*DEFAULT_STAT_PATHS, "types"]), help="统计接口类型")
    parser.add_argument("--resource_type", default="database", help="database/middleware/network/server/os 或中文名称")
    parser.add_argument("--type_id", help="直接指定 CMDB type id，优先级高于 resource_type")
    parser.add_argument("--type_kind", choices=["group", "model"], help="明确 ID 是模型分组还是具体模型，避免同号歧义")
    parser.add_argument("--attr", help="分组字段，例如 vendor/制造商/厂商/db_type/os_type/dev_class")
    parser.add_argument("--no_dynamic_type", action="store_true", help="仅使用明确的 --type_id/--type_kind，不使用固定 ID 映射")
    parser.add_argument("--output", choices=["json", "markdown"], default="markdown")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.stat == "types":
        payload = query_types()
    else:
        payload = query_stat(
            args.stat,
            args.resource_type,
            args.type_id,
            args.attr,
            dynamic_type=not args.no_dynamic_type,
            type_kind=args.type_kind,
        )
    payload = redact_output(payload)
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(payload))
    return 0 if payload.get("code") in {None, 200} else 1


if __name__ == "__main__":
    sys.exit(run_cli(main))
