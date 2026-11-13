#!/usr/bin/env python3
"""Fixed read-only CMDB entry point; no shell or user-supplied destination."""

import importlib
import json
import os
import re
import sys
from urllib.parse import urlsplit

from cmdb_output import run_cli, safe_print
from zgops_http import (
    configure_bearer,
    create_session,
    envelope,
    fetch_with_auth_fallback,
)


def read_path(command: str, arguments: list[str]) -> str:
    if command == "list-models" and not arguments:
        return "/api/v0.1/ci_types?per_page=200"
    if command in {"model-attributes", "model-relations"} and len(arguments) == 1:
        identifier = arguments[0]
        if not identifier.isascii() or not identifier.isdecimal():
            raise ValueError("模型 ID 必须是正整数")
        if command == "model-attributes":
            return f"/api/v0.1/ci_types/{identifier}/attributes"
        return f"/api/v0.1/ci_type_relations?ci_type_id={identifier}"
    if command == "fetch" and len(arguments) == 1:
        target = urlsplit(arguments[0])
        if target.scheme or target.netloc or target.fragment or "%" in target.path:
            raise ValueError("只允许固定的 CMDB 查询路径")
        if re.fullmatch(
            r"/api/v0\.1/(?:ci_types(?:/[0-9]+/(?:attributes|relations|parents))?|"
            r"ci_type_relations|ci_type_groups|relation_types|attributes|"
            r"ci/(?:s|[0-9]+)|ci_relations/s)",
            target.path,
        ):
            return arguments[0]
    raise ValueError("不支持的只读命令或参数")


def main() -> int:
    if len(sys.argv) < 2:
        raise ValueError("缺少只读子命令")
    command, arguments = sys.argv[1], sys.argv[2:]
    modules = {
        "find-project": "find_project",
        "app-topology": "app_topology",
        "analyze": "analyze_cmdb",
        "inoe-stat": "inoe_cmdb_stats",
    }
    if command in modules:
        module = importlib.import_module(modules[command])
        sys.argv = [module.__file__, *arguments]
        return module.main()
    path = read_path(command, arguments)
    base = os.environ["INOE_API_BASE_URL"].rstrip("/") + "/cmdb"
    with create_session() as session:
        configure_bearer(session, os.environ.get("INOE_API_TOKEN", ""))
        response = fetch_with_auth_fallback(session, base_url=base, path=path)
        response.raise_for_status()
        safe_print(json.dumps(envelope(response), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
