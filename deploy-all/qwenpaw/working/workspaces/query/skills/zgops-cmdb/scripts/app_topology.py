#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cmdb_output import run_cli, safe_print as print
from cmdb_contract import ci_detail, ci_identity, fetch_catalog_pages, fetch_ci_pages, fetch_relations, merge_cis
from find_project import (
    CmdbHttpClient,
    CmdbHttpStatusError,
    _clean_text,
    _match_projects,
    _normalize_token,
    _project_name,
    _resolve_zgops_env,
)


TYPE_BUCKET_PRIORITY = {
    "product": 10,
    "PhysicalMachine": 20,
    "vserver": 30,
    "docker": 40,
    "database": 50,
    "mysql": 51,
    "PostgreSQL": 52,
    "redis": 53,
    "Kafka": 54,
    "elasticsearch": 55,
    "nginx": 56,
    "apache": 57,
    "networkdevice": 60,
}

SOFTWARE_TYPES = {
    "database",
    "mysql",
    "PostgreSQL",
    "redis",
    "Kafka",
    "elasticsearch",
    "nginx",
    "apache",
}


# Some ZGOPS deployments encode a project's relationships as **inline attributes** on
# the project CI itself instead of (or in addition to) `ci_relations` rows — e.g. the
# project document carries `Kafka`, `mysql`, `redis`, `operatingsystem` fields whose
# values are the names of related CIs. The map below is the fallback catalog used
# when the live `/api/v0.1/ci_types` lookup is unavailable; keys are normalized
# (lower-case, punctuation-stripped via `_normalize_token`), values are the
# canonical `ci_type` to search.
INLINE_RELATION_TYPES = {
    "kafka": "Kafka",
    "redis": "redis",
    "elasticsearch": "elasticsearch",
    "nginx": "nginx",
    "apache": "apache",
    "mysql": "mysql",
    "postgresql": "PostgreSQL",
    "database": "database",
    "operatingsystem": "operatingsystem",
    "physicalmachine": "PhysicalMachine",
    "vserver": "vserver",
    "docker": "docker",
    "networkdevice": "networkdevice",
    "product": "product",
}


# Per-ci_type list of attributes that may carry a CI's display name. Used to
# match the values of inline relation attributes (which are typically display
# names like "kafka-web01") against actual CIs returned by `/api/v0.1/ci/s`.
_CI_TYPE_NAME_FIELDS: dict[str, list[str]] = {
    "vserver": ["vserver_name", "name", "private_ip", "manage_ip"],
    "docker": ["middleware_name", "name", "manage_ip", "private_ip"],
    "database": ["db_instance", "name", "manage_ip", "db_ip"],
    "mysql": ["db_instance", "name", "manage_ip", "db_ip"],
    "PostgreSQL": ["db_instance", "name", "manage_ip", "db_ip"],
    "redis": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "Kafka": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "elasticsearch": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "nginx": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "apache": ["middleware_name", "name", "middleware_ip", "manage_ip"],
    "networkdevice": ["dev_name", "name", "manage_ip"],
    "PhysicalMachine": ["host_name", "name", "private_ip", "manage_ip"],
    "operatingsystem": ["name", "os_name", "host_name"],
    "product": ["product_name", "name"],
    "project": ["project_name", "name"],
}


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = _clean_text(item)
            if text:
                result.append(text)
        return result
    text = _clean_text(value)
    if not text:
        return []
    separators = [",", "，", ";", "；", "|", "\n", "\t"]
    values = [text]
    for separator in separators:
        expanded: list[str] = []
        for item in values:
            expanded.extend(item.split(separator))
        values = expanded
    return [item.strip() for item in values if item.strip()]


def _fetch_relations(client: CmdbHttpClient, root_id: Any) -> list[dict[str, Any]]:
    return fetch_relations(client._request_json, root_id)


def _fetch_ci_detail(client: CmdbHttpClient, ci_id: Any) -> dict[str, Any]:
    """Fetch the full CI document so inline relation attributes are visible."""
    return ci_detail(client._request_json(
        f"/api/v0.1/ci/{urllib.parse.quote(str(ci_id), safe='')}"
    ))


def _fetch_ci_type_catalog(client: CmdbHttpClient) -> dict[str, str]:
    """Return a catalog mapping normalized type names/aliases → canonical ci_type.

    Pulls from `/api/v0.1/ci_types?per_page=200`; falls back to the hard-coded
    `INLINE_RELATION_TYPES` map when the metadata endpoint is unreachable.
    """
    catalog: dict[str, str] = {}
    try:
        payload = fetch_catalog_pages(client._request_json, "/api/v0.1/ci_types")
    except (urllib.error.HTTPError, CmdbHttpStatusError) as error:
        status = error.code if isinstance(error, urllib.error.HTTPError) else error.status_code
        if status != 404:
            raise
        print("模型元数据接口不可用（HTTP 404），使用旧版内联模型名称目录。", file=sys.stderr)
        payload = None

    type_items = payload if payload is not None else []

    for entry in type_items:
        if not isinstance(entry, dict):
            continue
        canonical = _clean_text(entry.get("name"))
        if not canonical:
            continue
        for key in ("name", "alias", "show_name"):
            token = _normalize_token(_clean_text(entry.get(key)))
            if token:
                catalog.setdefault(token, canonical)

    for normalized_key, canonical in INLINE_RELATION_TYPES.items():
        catalog.setdefault(normalized_key, canonical)
    return catalog


def _fetch_cis_by_type(client: CmdbHttpClient, ci_type: str) -> list[dict[str, Any]]:
    return fetch_ci_pages(
        client._request_json, "/api/v0.1/ci/s",
        {"q": f"_type:{ci_type}", "count": 10000},
    )


def _candidate_name_fields(ci_type: str) -> list[str]:
    return _CI_TYPE_NAME_FIELDS.get(ci_type, ["name"])


def _item_matches_token(item: dict[str, Any], ci_type: str, token_set: set[str]) -> bool:
    for field_name in _candidate_name_fields(ci_type):
        for value in _split_values(item.get(field_name)):
            if _normalize_token(value) in token_set:
                return True
    return False


def _resolve_inline_resources(
    client: CmdbHttpClient,
    project_detail: dict[str, Any],
) -> list[dict[str, Any]]:
    """Walk a project's attributes and resolve inline ci-type fields into CIs.

    Some ZGOPS environments record a project's related middleware/database/host
    set as inline string fields (e.g. `Kafka: "kafka-web01, kafka-web02"`). The
    `ci_relations` endpoint does not return those, so this is queried as a
    complement to `_fetch_relations`. Returns CI items that can be merged into
    the same items list `_build_tree` consumes.
    """
    if not isinstance(project_detail, dict) or not project_detail:
        return []

    catalog = _fetch_ci_type_catalog(client)

    candidates_by_type: dict[str, set[str]] = defaultdict(set)
    for key, value in project_detail.items():
        if not isinstance(key, str):
            continue
        canonical = catalog.get(_normalize_token(key))
        if not canonical or canonical == "project":
            continue
        for token in _split_values(value):
            normalized = _normalize_token(token)
            if normalized:
                candidates_by_type[canonical].add(normalized)

    resolved: list[dict[str, Any]] = []
    for ci_type, token_set in candidates_by_type.items():
        if not token_set:
            continue
        type_items = _fetch_cis_by_type(client, ci_type)
        if not type_items:
            continue
        for item in type_items:
            if _item_matches_token(item, ci_type, token_set):
                if not _clean_text(item.get("ci_type")):
                    item["ci_type"] = ci_type
                resolved.append(item)
    return resolved


def _merge_items(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Concatenate two CI lists, deduplicated by `_id` / `id`."""
    return merge_cis(primary, extra)


def _resource_label(item: dict[str, Any]) -> str:
    ci_type = _clean_text(item.get("ci_type"))
    candidates: list[Any] = []
    if ci_type == "project":
        candidates.extend([item.get("project_name"), item.get("name")])
    elif ci_type == "product":
        candidates.extend([item.get("product_name"), item.get("name")])
    elif ci_type == "vserver":
        candidates.extend([item.get("vserver_name"), item.get("name"), item.get("private_ip")])
    elif ci_type == "docker":
        candidates.extend([item.get("middleware_name"), item.get("manage_ip"), item.get("name")])
    elif ci_type in {"database", "mysql", "PostgreSQL"}:
        candidates.extend([item.get("db_instance"), item.get("name"), item.get("manage_ip"), item.get("db_ip")])
    elif ci_type in {"redis", "Kafka", "elasticsearch", "nginx", "apache"}:
        candidates.extend([item.get("middleware_name"), item.get("name"), item.get("middleware_ip")])
    elif ci_type == "networkdevice":
        candidates.extend([item.get("dev_name"), item.get("name"), item.get("manage_ip")])
    elif ci_type == "PhysicalMachine":
        candidates.extend([item.get("host_name"), item.get("name"), item.get("private_ip")])
    else:
        candidates.extend(
            [
                item.get("name"),
                item.get("project_name"),
                item.get("product_name"),
                item.get("middleware_name"),
                item.get("db_instance"),
                item.get("dev_name"),
                item.get("vserver_name"),
                item.get("manage_ip"),
                item.get("private_ip"),
            ]
        )

    for value in candidates:
        values = _split_values(value)
        if values:
            return values[0]

    ci_id = item.get("_id") or item.get("id") or "unknown"
    return f"{ci_type or 'resource'}-{ci_id}"


def _resource_ips(item: dict[str, Any]) -> set[str]:
    fields = [
        "private_ip",
        "manage_ip",
        "middleware_ip",
        "db_ip",
        "host_ip",
        "manager_ip",
        "AssociatedVM",
        "AssociatedPhyMachine",
        "deploy_target",
    ]
    values: set[str] = set()
    for field_name in fields:
        for token in _split_values(item.get(field_name)):
            values.add(token)
    return values


def _resource_node(item: dict[str, Any]) -> dict[str, Any]:
    label = _resource_label(item)
    ci_type = _clean_text(item.get("ci_type"))
    alias = _clean_text(item.get("ci_type_alias")) or ci_type or "资源"
    return {
        "name": label,
        "value": {
            "id": item.get("_id") or item.get("id"),
            "ciType": ci_type,
            "ciTypeAlias": alias,
        },
        "children": [],
    }


def _bucket_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    ci_type = _clean_text(item.get("ci_type"))
    return TYPE_BUCKET_PRIORITY.get(ci_type, 999), _resource_label(item)


def _build_tree(project: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    root_name = _project_name(project) or "应用"
    filtered_items = [item for item in items if ci_identity(item) != ci_identity(project)]
    filtered_items.sort(key=_bucket_sort_key)
    direct_children = [_resource_node(item) for item in filtered_items]

    root = {
        "name": root_name,
        "value": {
            "id": project.get("_id") or project.get("id"),
            "ciType": "project",
            "ciTypeAlias": _clean_text(project.get("ci_type_alias")) or "应用",
            "relationEvidence": "queried-downstream-overview",
        },
        "children": sorted(direct_children, key=lambda node: node["name"]),
    }
    return root


def _build_option(tree: dict[str, Any], title: str) -> dict[str, Any]:
    return {
        "series": [
            {
                "type": "tree",
                "data": [tree],
                "orient": "LR",
                "initialTreeDepth": -1,
                "expandAndCollapse": True,
                "animationDuration": 550,
                "animationDurationUpdate": 750,
                "label": {
                    "position": "left",
                    "verticalAlign": "middle",
                    "align": "right",
                    "fontSize": 12,
                },
                "leaves": {
                    "label": {
                        "position": "right",
                        "verticalAlign": "middle",
                        "align": "left",
                    }
                },
            }
        ],
    }


def _render_markdown(project_name: str, items: list[dict[str, Any]], option: dict[str, Any]) -> str:
    type_counter: dict[str, int] = defaultdict(int)
    for item in items:
        type_counter[_clean_text(item.get("ci_type_alias")) or _clean_text(item.get("ci_type")) or "资源"] += 1

    summary = "、".join(
        f"{name} {count} 个" for name, count in sorted(type_counter.items(), key=lambda item: item[0])
    )
    lines = [
        f"`{project_name}` 当前共发现 {len(items)} 个关联资源。",
        f"资源分布：{summary}。",
        "以下是查询范围内的关联资源概览，不代表资源之间的直接部署关系。",
        "",
        "```echarts",
        json.dumps(option, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="输出指定应用的标准 ECharts 拓扑")
    parser.add_argument("keyword", help="应用名")
    parser.add_argument(
        "--output",
        choices=["markdown", "echarts", "json"],
        default="markdown",
        help="输出格式",
    )
    args = parser.parse_args()

    env = _resolve_zgops_env()
    client = CmdbHttpClient(
        base_url=env.get("INOE_API_BASE_URL", ""),
        token=env.get("INOE_API_TOKEN", ""),
    )
    client.try_login()

    projects = client.list_projects()
    matched_projects, _mode = _match_projects(projects, args.keyword)
    if not matched_projects:
        print(f"未找到应用：{args.keyword}", file=sys.stderr)
        return 1
    if len(matched_projects) > 1:
        print(f"存在多个与 {args.keyword} 匹配的应用，请使用精确名称。", file=sys.stderr)
        return 1

    project = matched_projects[0]
    project_name = _project_name(project) or _clean_text(args.keyword)
    project_id = project.get("_id") or project.get("id")
    items = _fetch_relations(client, project_id)

    # Some ZGOPS deployments express a project's relationships as inline
    # attributes on the project CI itself (e.g. `Kafka`, `mysql`, `redis`,
    # `operatingsystem` fields whose values are CI names). Always merge those
    # in — `ci_relations` alone is not authoritative.
    project_detail = _fetch_ci_detail(client, project_id) or project
    inline_items = _resolve_inline_resources(client, project_detail)
    items = [
        item for item in _merge_items(items, inline_items)
        if ci_identity(item) != ci_identity(project)
    ]

    tree = _build_tree(project, items)
    option = _build_option(tree, f"{project_name} 应用关系拓扑")

    if args.output == "json":
        print(
            json.dumps(
                {
                    "project": project_name,
                    "root_id": project.get("_id") or project.get("id"),
                    "resource_count": len(items),
                    "view": "association-overview",
                    "query_levels": [1, 2, 3],
                    "query_direction": "forward",
                    "option": option,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.output == "echarts":
        print(json.dumps(option, ensure_ascii=False, indent=2))
        return 0

    print(_render_markdown(project_name, items, option))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
