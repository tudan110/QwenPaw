#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import urljoin

import requests


def normalize_api_path(path: str) -> str:
    path = path.strip()
    if not path:
        raise ValueError("API 路径不能为空")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return path


def build_url(base_url: str, path: str) -> str:
    path = normalize_api_path(path)
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept-Language": "zh"})
    return session


def login(session: requests.Session, base_url: str, username: str, password: str) -> dict[str, Any]:
    url = build_url(base_url, "/api/v1/acl/login")
    response = session.post(
        url,
        json={"username": username, "password": password},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("token")
    if not token:
        raise RuntimeError("登录响应缺少 token")
    session.headers["Access-Token"] = token
    return payload


def parse_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def envelope(response: requests.Response) -> dict[str, Any]:
    return {"状态码": response.status_code, "响应体": parse_body(response)}


def main() -> int:
    parser = argparse.ArgumentParser(description="VEOPS CMDB 后台 HTTP 客户端")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="后台登录并检查会话是否可用")

    fetch_parser = subparsers.add_parser("fetch", help="后台拉取指定 API")
    fetch_parser.add_argument("path", help="API 路径，例如 /api/v0.1/ci_types")

    args = parser.parse_args()

    base_url = os.environ["VEOPS_BASE_URL"]
    username = os.environ["VEOPS_USERNAME"]
    password = os.environ["VEOPS_PASSWORD"]
    cmdb_url = os.environ.get("VEOPS_CMDB_URL", base_url.rstrip("/") + "/cmdb/")

    session = create_session()

    try:
        auth_payload = login(session, base_url, username, password)

        if args.command == "login":
            info_response = session.get(
                build_url(base_url, "/api/v1/acl/users/info"),
                timeout=20,
            )
            info_response.raise_for_status()
            info = parse_body(info_response)
            print(
                json.dumps(
                    {
                        "状态": "已登录",
                        "用户名": auth_payload.get("username"),
                        "CMDB": cmdb_url,
                        "用户信息": info.get("result", info),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        response = session.get(build_url(base_url, args.path), timeout=30)
        print(json.dumps(envelope(response), ensure_ascii=False, indent=2))
        return 0
    except requests.HTTPError as exc:
        response = exc.response
        if response is None:
            print(json.dumps({"状态码": 0, "响应体": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(envelope(response), ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"状态码": 0, "响应体": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2)
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
