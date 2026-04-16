#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_token(value: str) -> str:
    text = _clean_text(value).lower()
    for src, dst in (("（", "("), ("）", ")")):
        text = text.replace(src, dst)
    return "".join(ch for ch in text if ch not in " \t\r\n_-()/\\:：")


class CmdbHttpClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        body = None
        req_headers = {"Accept-Language": "zh"}
        if headers:
            req_headers.update(headers)
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=req_headers,
            method=method,
        )
        with self.opener.open(req, timeout=30) as response:
            return json.load(response)

    def login(self) -> None:
        payload = self._request_json(
            "/api/v1/acl/login",
            method="POST",
            payload={"username": self.username, "password": self.password},
        )
        token = _clean_text(payload.get("token"))
        if not token:
            raise RuntimeError(f"登录响应缺少 token: {payload}")
        self.opener.addheaders = [("Access-Token", token), ("Accept-Language", "zh")]

    def list_projects(self) -> list[dict[str, Any]]:
        query = urllib.parse.quote("_type:project", safe=":_")
        payload = self._request_json(f"/api/v0.1/ci/s?q={query}&count=200&page=1")
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, list):
                return result
        if isinstance(payload, list):
            return payload
        return []


def _project_name(project: dict[str, Any]) -> str:
    return (
        _clean_text(project.get("project_name"))
        or _clean_text(project.get("name"))
        or _clean_text(project.get("ci_type_alias"))
    )


def _project_summary(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project.get("_id") or project.get("id"),
        "name": _project_name(project),
        "type": _clean_text(project.get("project_type")),
        "status": _clean_text(project.get("project_status")),
        "platform": [
            _clean_text(item)
            for item in (project.get("platform") or [])
            if _clean_text(item)
        ],
    }


def _match_projects(projects: list[dict[str, Any]], keyword: str) -> tuple[list[dict[str, Any]], str]:
    cleaned_keyword = _clean_text(keyword)
    if not cleaned_keyword:
        return projects, "all"

    normalized_keyword = _normalize_token(cleaned_keyword)
    exact_matches = [
        item
        for item in projects
        if _normalize_token(_project_name(item)) == normalized_keyword
    ]
    if exact_matches:
        return exact_matches, "exact"

    partial_matches = [
        item
        for item in projects
        if normalized_keyword and normalized_keyword in _normalize_token(_project_name(item))
    ]
    return partial_matches, "partial"


def _render_markdown(
    *,
    all_projects: list[dict[str, Any]],
    matched_projects: list[dict[str, Any]],
    mode: str,
    keyword: str,
) -> str:
    if mode == "all":
        if len(all_projects) == 1:
            only = _project_summary(all_projects[0])
            return "\n".join(
                [
                    f"当前系统仅发现 1 个应用：`{only['name']}`（ID: `{only['id']}`）",
                    "",
                    "后续拓扑查询可直接使用：",
                    f"`scripts/veops-cmdb.sh fetch \"/api/v0.1/ci_relations/s?root_id={only['id']}&level=1,2,3&count=10000\"`",
                ]
            )

        lines = [
            f"当前系统存在 {len(all_projects)} 个应用，不能默认任选一个进行拓扑查询。",
            "",
            "请明确指定应用名。当前可选应用：",
        ]
        for item in sorted((_project_summary(project) for project in all_projects), key=lambda entry: entry["name"]):
            lines.append(f"- `{item['name']}`（ID: `{item['id']}`）")
        return "\n".join(lines)

    if not matched_projects:
        lines = [
            f"未找到与 `{keyword}` 匹配的应用。",
            "",
            "当前可选应用：",
        ]
        for item in sorted((_project_summary(project) for project in all_projects), key=lambda entry: entry["name"]):
            lines.append(f"- `{item['name']}`（ID: `{item['id']}`）")
        return "\n".join(lines)

    if len(matched_projects) > 1:
        lines = [
            f"存在多个与 `{keyword}` 匹配的应用，不能默认选择其一。",
            "",
            "请从以下候选中指定一个精确应用名：",
        ]
        for item in sorted((_project_summary(project) for project in matched_projects), key=lambda entry: entry["name"]):
            lines.append(f"- `{item['name']}`（ID: `{item['id']}`）")
        return "\n".join(lines)

    item = _project_summary(matched_projects[0])
    return "\n".join(
        [
            f"已匹配到应用：`{item['name']}`（ID: `{item['id']}`）",
            "",
            "后续拓扑查询请只针对该应用执行：",
            f"`scripts/veops-cmdb.sh fetch \"/api/v0.1/ci_relations/s?root_id={item['id']}&level=1,2,3&count=10000\"`",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="解析 CMDB 应用拓扑查询目标")
    parser.add_argument("keyword", nargs="?", default="", help="应用名或关键字")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    env_file = Path(os.environ.get("VEOPS_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))
    env = _load_env_file(env_file)
    client = CmdbHttpClient(
        base_url=env["VEOPS_BASE_URL"],
        username=env["VEOPS_USERNAME"],
        password=env["VEOPS_PASSWORD"],
    )
    client.login()
    projects = client.list_projects()
    matched_projects, mode = _match_projects(projects, args.keyword)

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "keyword": _clean_text(args.keyword),
                    "total": len(projects),
                    "matches": [_project_summary(item) for item in matched_projects],
                    "projects": [_project_summary(item) for item in projects],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(
        _render_markdown(
            all_projects=projects,
            matched_projects=matched_projects,
            mode=mode,
            keyword=_clean_text(args.keyword),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
