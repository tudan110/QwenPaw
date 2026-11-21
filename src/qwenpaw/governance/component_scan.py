# -*- coding: utf-8 -*-
"""Read-only exposure/content checks and opt-in known dependency advisories."""

from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from packaging.utils import canonicalize_name

from ..constant import EnvVarLoader
from .component_events import label, now

OSV_ENDPOINT = "https://api.osv.dev/v1/querybatch"


def row(kind, name, scope, status, detail, findings=()):
    return {
        "kind": kind,
        "name": label(name),
        "scope": label(scope),
        "status": status,
        "detail": detail,
        "findings": list(findings),
    }


def scan_dependencies(client: httpx.Client | None = None) -> list[dict]:
    if client is None and not EnvVarLoader.get_bool(
        "QWENPAW_GOVERNANCE_OSV_ENABLED", False
    ):
        return [
            row(
                "dependency",
                "Python 运行环境依赖",
                "全局",
                "not_covered",
                "部署未启用 OSV 公告查询；未判定无已知漏洞。",
            )
        ]
    installed = sorted(
        {
            (canonicalize_name(dist.metadata["Name"]), dist.version)
            for dist in metadata.distributions()
            if dist.metadata["Name"] and dist.version
        }
    )
    rows = []
    with httpx.Client(timeout=8, trust_env=False) as default_client:
        api = client or default_client
        for offset in range(0, len(installed), 100):
            batch = installed[offset : offset + 100]
            queries = [
                {
                    "package": {"ecosystem": "PyPI", "name": name},
                    "version": version,
                }
                for name, version in batch
            ]
            try:
                response = api.post(OSV_ENDPOINT, json={"queries": queries})
                response.raise_for_status()
                results = response.json()["results"]
                if not isinstance(results, list) or len(results) != len(batch):
                    raise ValueError("invalid advisory response")
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                rows.extend(
                    row(
                        "dependency",
                        f"{name} {version}",
                        "全局",
                        "incomplete",
                        "OSV 公告库不可达或结果不完整。",
                    )
                    for name, version in batch
                )
                continue
            for (name, version), result in zip(batch, results):
                vulns = (
                    result.get("vulns", [])
                    if isinstance(result, dict)
                    else None
                )
                ids = (
                    [v.get("id") for v in vulns if isinstance(v, dict)]
                    if isinstance(vulns, list)
                    else []
                )
                advisories = [
                    v
                    for v in ids
                    if isinstance(v, str) and re.fullmatch(r"[\w.-]{2,100}", v)
                ]
                incomplete = (
                    not isinstance(vulns, list)
                    or len(advisories) != len(vulns)
                    or bool(result.get("next_page_token"))
                    or bool(set(result) - {"vulns", "next_page_token"})
                )
                detail = (
                    "按当前安装版本查询 OSV 已知公告；不代表不存在未知漏洞。"
                )
                if incomplete:
                    detail = "OSV 返回不完整；仅展示已取得的公告，仍需复核。"
                rows.append(
                    row(
                        "dependency",
                        f"{name} {version}",
                        "全局",
                        (
                            "findings"
                            if advisories
                            else "incomplete" if incomplete else "clear"
                        ),
                        detail,
                        advisories[:20],
                    )
                )
    return rows or [
        row(
            "dependency",
            "Python 运行环境依赖",
            "全局",
            "not_covered",
            "未取得安装版本。",
        )
    ]


def scan_skills(roots: list[tuple[str, Path]]) -> list[dict]:
    from ..security.skill_scanner.scanner import SkillScanner

    scanner = SkillScanner(max_files=150, max_file_size=1024 * 1024)
    rows = []
    remaining = 150
    for scope, root in roots:
        if root.is_symlink() or (
            hasattr(root, "is_junction") and root.is_junction()
        ):
            rows.append(
                row(
                    "skill",
                    "技能目录",
                    scope,
                    "incomplete",
                    "未读取链接目录。",
                )
            )
            continue
        try:
            with os.scandir(root) as entries:
                paths = [
                    Path(entry.path)
                    for entry in entries
                    if not entry.name.startswith(".")
                    and (Path(entry.path) / "SKILL.md").is_file()
                ]
        except FileNotFoundError:
            paths = []
        except OSError:
            rows.append(
                row(
                    "skill",
                    "技能目录",
                    scope,
                    "incomplete",
                    "无法读取技能目录。",
                )
            )
            continue
        if not paths:
            rows.append(
                row(
                    "skill",
                    "技能目录",
                    scope,
                    "not_applicable",
                    "未发现已安装技能。",
                )
            )
        for path in sorted(paths):
            if remaining <= 0:
                rows.append(
                    row(
                        "skill",
                        "其余技能",
                        scope,
                        "incomplete",
                        "达到单次扫描上限（150 个技能）。",
                    )
                )
                break
            remaining -= 1
            if (
                path.is_symlink()
                or (hasattr(path, "is_junction") and path.is_junction())
                or not path.resolve().is_relative_to(root.resolve())
            ):
                rows.append(
                    row(
                        "skill",
                        path.name,
                        scope,
                        "incomplete",
                        "未读取链接技能。",
                    )
                )
                continue
            try:
                result = scanner.scan_skill(path)
            except Exception:
                rows.append(
                    row(
                        "skill",
                        path.name,
                        scope,
                        "incomplete",
                        "技能静态分析失败。",
                    )
                )
                continue
            incomplete = (
                not result.analyzers_used
                or result.analyzers_failed
                or result.scannable_file_count == 0
                or result.coverage_limited
            )
            findings = [
                f"{label(f.rule_id)} · {label(f.severity.value)}：{label(f.title)}"
                for f in result.findings[:10]
            ]
            rows.append(
                row(
                    "skill",
                    path.name,
                    scope,
                    (
                        "findings"
                        if findings
                        else "incomplete" if incomplete else "clear"
                    ),
                    (
                        "规则静态检查；有文件被跳过或分析器未全部完成。"
                        if incomplete
                        else "按本地签名规则静态检查，不执行技能代码；不覆盖归档/二进制。"
                    ),
                    findings,
                )
            )
    return rows


def _endpoint_findings(address: str) -> list[str]:
    try:
        parsed = urlsplit(address)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ["未配置有效的 HTTP(S) 接口"]
        if parsed.username is not None or parsed.password is not None:
            return ["URL 包含内嵌凭据，应改用受控凭据配置"]
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            return ["使用非回环明文 HTTP；复核网络边界并优先配置 TLS"]
        return []
    except ValueError:
        return ["接口地址格式无效"]


def scan_endpoints(manager, workspaces: list[tuple[str, Path]]) -> list[dict]:
    from ..drivers.storage import list_card_paths, load_card
    from ..extensions.security.execution_policy import enabled
    from ..extensions.security.mcp_boundary import validate_endpoint

    rows = []
    ids = (
        set(manager.builtin_providers)
        | set(manager.custom_providers)
        | set(manager.plugin_providers)
    )
    for provider_id in sorted(ids):
        provider = manager.get_provider(provider_id)
        if (
            provider is None
            or not provider.base_url
            or not (
                provider.extra_models
                or provider.api_key
                or provider.is_local
                or provider.is_custom
            )
        ):
            continue
        findings = _endpoint_findings(provider.base_url)
        rows.append(
            row(
                "model",
                provider_id,
                "全局",
                "findings" if findings else "clear",
                "仅检查提供商地址配置，不鉴定模型文件、远端实现或版本漏洞。",
                findings,
            )
        )
    if not rows:
        rows.append(
            row(
                "model",
                "模型接口",
                "全局",
                "not_applicable",
                "未发现可检查的服务地址。",
            )
        )
    for scope, workspace in workspaces:
        paths = list_card_paths(workspace / "drivers")
        mcp_paths = [p for p in paths if p.parent.name == "mcp"]
        if not mcp_paths:
            rows.append(
                row(
                    "mcp",
                    "MCP 接口",
                    scope,
                    "not_applicable",
                    "未发现 MCP 配置。",
                )
            )
        for path in mcp_paths:
            try:
                card = load_card(path)
            except Exception:
                rows.append(
                    row(
                        "mcp", path.stem, scope, "incomplete", "配置无法读取。"
                    )
                )
                continue
            transport = card.endpoint.get("transport")
            findings = (
                []
                if transport == "stdio"
                else _endpoint_findings(str(card.endpoint.get("url", "")))
            )
            if enabled() and card.enabled:
                try:
                    validate_endpoint(card.endpoint)
                except PermissionError:
                    findings.append("当前启用的 MCP 不符合运行准入策略")
                except (TypeError, ValueError):
                    rows.append(
                        row(
                            "mcp",
                            card.name,
                            scope,
                            "incomplete",
                            "MCP 准入配置格式无效。",
                            findings,
                        )
                    )
                    continue
            if transport == "stdio" and not findings:
                status, detail = (
                    "not_covered",
                    "STDIO 未执行；本地命令来源和版本需人工核查。",
                )
            else:
                status = "findings" if findings else "clear"
                detail = "只核验地址配置和已启用的准入规则，不连接 MCP、不验证远端版本漏洞。"
            rows.append(row("mcp", card.name, scope, status, detail, findings))
    return rows


def run_scan(
    provider_manager, workspaces: list[tuple[str, Path]], pools: list[Path]
) -> dict:
    from ..plugins.registry import PluginRegistry

    roots = [
        (
            scope,
            workspace
            / (
                "skill"
                if not (workspace / "skills").exists()
                and (workspace / "skill").exists()
                else "skills"
            ),
        )
        for scope, workspace in workspaces
    ]
    roots += [(f"技能池 {idx + 1}", root) for idx, root in enumerate(pools)]
    rows = (
        scan_skills(roots)
        + scan_endpoints(provider_manager, workspaces)
        + scan_dependencies()
    )
    rows.extend(
        [
            row(
                "dependency",
                "智观AI前端与操作系统依赖",
                "全局",
                "not_covered",
                "当前入口不含前端及镜像 SBOM，需在构建/镜像阶段核验。",
            ),
            row(
                "plugin",
                "插件与外部服务版本",
                "全局",
                "not_covered",
                "未登记可核验版本/SBOM，不主动访问第三方服务；需运行发布侧扫描或核查厂商公告。",
            ),
        ]
    )
    for plugin_id, manifest in sorted(
        PluginRegistry().get_all_plugin_manifests().items()
    ):
        version = manifest.get("version")
        name = f"{plugin_id} {version}" if version else plugin_id
        rows.append(
            row(
                "plugin",
                name,
                "全局",
                "not_covered",
                "已登记插件；此次未检查其代码或版本漏洞。",
            )
        )
    return {"checked_at": now(), "rows": rows}
