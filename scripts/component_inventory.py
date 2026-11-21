#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export a local, read-only 401-3 component directory without loading QwenPaw.

Only declared metadata is collected. No plugin, model, skill or application is
imported or executed; no endpoint is contacted. This is not a runtime attestation
or a vulnerability/SBOM scanner.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import os
from pathlib import Path
import re
import stat
import tomllib
from urllib.parse import urlsplit


UNKNOWN = "待核实"
MAX_BYTES = 5 * 1024 * 1024
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "data"}
LIMITS = [
    "本报告仅整理401-3步骤1的组件目录，未因此完成步骤2至5。",
    "仓库/交付模板、配置声明与运行状态分开记录；未连接目标服务器核验。",
    "权限、数据范围、风险等级缺少审查依据时标为待核实，不自动认定低风险。",
    "版本约束不是已安装版本；文件摘要不是完整组件完整性或漏洞结论。",
    "依赖仅覆盖主项目及Console的直接依赖声明，不是完整SBOM。",
    "模型仅采集显式active_model；继承模型、全局Provider、动态组件和其他外部服务仍需补核。",
    "不读取.env、凭据目录、会话、知识库内容或组件代码的运行结果。",
]


def endpoint(value: str) -> str:
    """Keep only HTTP(S) scheme/host/port, never userinfo, path or parameters."""
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname:
            return UNKNOWN
        host = url.hostname
        if not re.fullmatch(r"[\w.:-]+", host):
            return UNKNOWN
        host = f"[{host}]" if ":" in host else host
        return f"{url.scheme}://{host}" + (f":{url.port}" if url.port else "")
    except ValueError:
        return UNKNOWN


def text(value: object, fallback: str = UNKNOWN) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    value = re.sub(r"https?://[^\s\"'<>]+", lambda m: endpoint(m[0]), value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [已隐藏]", value)
    value = re.sub(r"\bsk[-_][A-Za-z0-9_-]{8,}", "[已隐藏]", value)
    value = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[已隐藏]",
        value,
    )
    return " ".join(value.split())[:300]


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


class Inventory:
    def __init__(self) -> None:
        self.records: list[dict] = []
        self.warnings: list[str] = []

    @staticmethod
    def safe(path: Path, root: Path) -> bool:
        """Reject nested links/junctions, including ones pointing inside root."""
        try:
            if not path.resolve().is_relative_to(root):
                return False
            for current in [path, *path.parents]:
                if current == root:
                    break
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode) or (
                    getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                ):
                    return False
            return True
        except (OSError, ValueError, RuntimeError):
            return False

    def source(self, path: Path, root: Path, label: str) -> str:
        return text(f"{label}/{path.relative_to(root).as_posix()}")

    def read(self, path: Path, root: Path, label: str) -> str | None:
        source = self.source(path, root, label)
        try:
            if not self.safe(path, root) or not path.is_file():
                raise ValueError("unsafe or missing file")
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("file too large")
            return path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            self.warnings.append(f"未采集：{source}（缺失、不可读、过大或为链接）")
            return None

    def read_json(self, path: Path, root: Path, label: str) -> dict:
        raw = self.read(path, root, label)
        if raw is None:
            return {}
        try:
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("object required")
            return result
        except ValueError:
            self.warnings.append(f"未解析JSON对象：{self.source(path, root, label)}")
            return {}

    def files(self, root: Path, directory: Path, filename: str):
        if not directory.exists():
            return
        if not self.safe(directory, root):
            self.warnings.append(
                f"跳过链接目录：{self.source(directory, root, 'source')}"
            )
            return
        for current, directories, filenames in os.walk(
            directory, followlinks=False
        ):
            kept = []
            for name in sorted(directories):
                if name in SKIP_DIRS:
                    continue
                path = Path(current) / name
                if self.safe(path, root):
                    kept.append(name)
                else:
                    self.warnings.append(
                        f"跳过链接或不安全目录：{self.source(path, root, 'source')}"
                    )
            directories[:] = kept
            if filename in filenames:
                yield Path(current) / filename

    def add(
        self, kind: str, name: object, source: str, state: str, **fields
    ) -> None:
        record = {
            "kind": kind,
            "name": text(name),
            "source": source,
            "version": UNKNOWN,
            "purpose": UNKNOWN,
            "permissions": UNKNOWN,
            "data_scope": UNKNOWN,
            "risk_level": UNKNOWN,
            "state": state,
            "source_file_sha256": UNKNOWN,
        }
        record.update({key: text(value) for key, value in fields.items()})
        self.records.append(record)

    def skills(
        self, root: Path, directory: Path, label: str, state: str
    ) -> None:
        # A nested reference/scaffold SKILL.md is not another installed skill.
        for path in sorted(directory.glob("*/SKILL.md")):
            raw = self.read(path, root, label)
            if raw is None:
                continue
            # Deliberately parse only simple metadata scalars, never YAML tags.
            front = (
                raw.split("---", 2)[1]
                if raw.startswith("---") and raw.count("---") >= 2
                else ""
            )
            description = re.search(r"(?m)^description:\s*([^\n]+)", front)
            purpose = description[1].strip("\"'") if description else UNKNOWN
            if purpose in {"|", ">", "|-", ">-"}:
                purpose = UNKNOWN
            self.add(
                "技能",
                path.parent.name,
                self.source(path, root, label),
                state,
                purpose=purpose,
                source_file_sha256=self.digest(path, root),
            )

    def digest(self, path: Path, root: Path) -> str:
        try:
            if self.safe(path, root) and path.stat().st_size <= MAX_BYTES:
                return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
        return UNKNOWN

    def configs(self, root: Path, label: str, state: str) -> None:
        paths = sorted((root / "workspaces").glob("*/agent.json"))
        if (root / "config.json").exists():
            paths.insert(0, root / "config.json")
        if not paths:
            self.warnings.append(
                f"{label}未发现config.json或workspaces/*/agent.json，未采集模型/MCP/工具配置。"
            )
        for path in paths:
            config = self.read_json(path, root, label)
            source = self.source(path, root, label)
            model = mapping(config.get("active_model"))
            if model.get("model"):
                self.add(
                    "模型配置",
                    model["model"],
                    source,
                    state,
                    purpose="智能体推理",
                    provider=text(model.get("provider_id")),
                )
            for name, client in sorted(
                mapping(mapping(config.get("mcp")).get("clients")).items()
            ):
                if not isinstance(client, dict):
                    self.warnings.append(f"MCP条目格式异常：{source}")
                    continue
                enabled = {True: "声明启用", False: "声明停用"}.get(
                    client.get("enabled")
                    if isinstance(client.get("enabled"), bool)
                    else None,
                    "启用状态未声明",
                )
                target = endpoint(
                    str(client.get("url") or client.get("baseUrl") or "")
                )
                self.add(
                    "MCP服务",
                    name,
                    source,
                    f"{state}；{enabled}（未验证连通/生效）",
                    purpose=client.get("description"),
                    target_origin=target,
                )
            for name, tool in sorted(
                mapping(
                    mapping(config.get("tools")).get("builtin_tools")
                ).items()
            ):
                if not isinstance(tool, dict):
                    self.warnings.append(f"工具条目格式异常：{source}")
                    continue
                enabled = (
                    "声明启用"
                    if tool.get("enabled") is True
                    else "声明停用"
                    if tool.get("enabled") is False
                    else "启用状态未声明"
                )
                self.add(
                    "工具配置",
                    name,
                    source,
                    f"{state}；{enabled}（未验证执行）",
                    purpose=tool.get("description"),
                )
        self.skills(root, root / "skills", label, state)
        for workspace in sorted((root / "workspaces").glob("*")):
            if workspace.is_dir():
                self.skills(root, workspace / "skills", label, state)

    def repository(self, root: Path) -> None:
        path = root / "pyproject.toml"
        raw = self.read(path, root, "repo")
        if raw is not None:
            try:
                project = tomllib.loads(raw).get("project", {})
                for spec in project.get("dependencies", []):
                    if isinstance(spec, str):
                        name = re.match(r"[A-Za-z0-9_.-]+", spec)
                        self.add(
                            "Python直接依赖",
                            name[0] if name else UNKNOWN,
                            "repo/pyproject.toml",
                            "依赖声明（未核实安装版本）",
                            version=spec,
                            purpose="服务端直接依赖",
                        )
            except (ValueError, AttributeError, TypeError):
                self.warnings.append("未解析：repo/pyproject.toml")
        package = root / "console/package.json"
        if package.exists():
            data = self.read_json(package, root, "repo")
            for name, spec in sorted(
                mapping(data.get("dependencies")).items()
            ):
                self.add(
                    "Console直接依赖",
                    name,
                    "repo/console/package.json",
                    "依赖声明（未核实安装版本）",
                    version=spec,
                    purpose="Console直接依赖",
                )
        self.skills(
            root, root / "src/qwenpaw/agents/skills", "repo", "源码随附（未核实启用）"
        )
        for path in self.files(root, root / "plugins", "plugin.json"):
            data = self.read_json(path, root, "repo")
            if data:
                self.add(
                    "插件",
                    data.get("id") or path.parent.name,
                    self.source(path, root, "repo"),
                    "仓库示例/随附插件（未核实安装或启用）",
                    version=data.get("version"),
                    purpose=data.get("description"),
                )
        tool_path = root / "src/qwenpaw/config/config.py"
        raw = self.read(tool_path, root, "repo")
        if raw is not None:
            try:
                tree = ast.parse(raw)
                for function in tree.body:
                    if (
                        not isinstance(function, ast.FunctionDef)
                        or function.name != "_default_builtin_tools"
                    ):
                        continue
                    for node in function.body:
                        if not isinstance(node, ast.Assign) or not isinstance(
                            node.value, ast.Dict
                        ):
                            continue
                        if not any(
                            isinstance(t, ast.Name) and t.id == "tools"
                            for t in node.targets
                        ):
                            continue
                        for key in node.value.keys:
                            if isinstance(key, ast.Constant) and isinstance(
                                key.value, str
                            ):
                                self.add(
                                    "内置工具",
                                    key.value,
                                    "repo/src/qwenpaw/config/config.py",
                                    "源码定义（未核实当前智能体启用或权限）",
                                )
            except SyntaxError:
                self.warnings.append(
                    "未解析内置工具定义：repo/src/qwenpaw/config/config.py"
                )
        seed = root / "deploy-all/qwenpaw/working"
        if seed.exists() and self.safe(seed, root):
            self.configs(seed.resolve(), "delivery-template", "交付模板（非现场配置）")
        elif seed.exists():
            self.warnings.append("交付模板目录为链接或越出仓库，未采集。")

    def report(self, working_provided: bool) -> dict:
        counts = dict(sorted(Counter(r["kind"] for r in self.records).items()))
        return {
            "schema_version": "qwenpaw.component-directory.v1",
            "requirement": "401-3 / 步骤1 组件目录",
            "collected_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            "scope": "仓库与交付模板；另含显式工作目录配置（非运行态核验）"
            if working_provided
            else "仓库与交付模板；未采集目标工作目录",
            "limitations": LIMITS,
            "counts": counts,
            "warnings": self.warnings,
            "components": self.records,
        }


def render(report: dict) -> str:
    rows = []
    for record in report["components"]:

        def e(key):
            return escape(record[key])

        target = escape(
            record.get("target_origin", record.get("provider", UNKNOWN))
        )
        rows.append(
            f'<tr data-kind="{e("kind")}"><td><strong>{e("name")}</strong><small>{e("kind")}</small></td>'
            f'<td>{e("version")}<small>{e("source")}</small><details><summary>来源文件摘要</summary><code>{e("source_file_sha256")}</code></details></td>'
            f'<td>{e("purpose")}<small>目标源站 / Provider：{target}</small></td>'
            f'<td>权限：{e("permissions")}<small>数据范围：{e("data_scope")}</small></td>'
            f'<td>{e("risk_level")}</td><td>{e("state")}</td></tr>'
        )
    options = "".join(
        f"<option>{escape(kind)}</option>" for kind in report["counts"]
    )
    counts = "".join(
        f"<span>{escape(kind)} <b>{count}</b></span>"
        for kind, count in report["counts"].items()
    )
    warnings = "".join(
        f"<li>{escape(warning)}</li>" for warning in report["warnings"]
    )
    limits = "".join(
        f"<li>{escape(limit)}</li>" for limit in report["limitations"]
    )
    return (
        """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>组件目录 · 401-3</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#172b43;font:14px/1.6 'Microsoft YaHei',Arial,sans-serif}main{max-width:1560px;margin:32px auto;padding:0 24px}
h1{font-size:26px;margin:0 0 6px}p{margin:4px 0;color:#526478}.intro,.controls,table,details.notes{background:white;border:1px solid #dce3ec;border-radius:8px}.intro{padding:18px 22px}.counts{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.counts span{background:#e9eff6;border-radius:5px;padding:5px 10px}.controls{display:flex;gap:12px;align-items:center;padding:12px 16px;margin:16px 0}input,select{border:1px solid #bcc9d9;border-radius:4px;padding:8px;font:inherit}input{min-width:300px}table{width:100%;border-collapse:collapse;table-layout:fixed}th{text-align:left;background:#203e5d;color:white;padding:12px}td{padding:12px;border-bottom:1px solid #e5ebf2;vertical-align:top;overflow-wrap:anywhere}th:nth-child(1){width:17%}th:nth-child(2){width:27%}th:nth-child(3){width:18%}th:nth-child(4){width:14%}th:nth-child(5){width:7%}th:nth-child(6){width:17%}small{display:block;color:#5d6d80;margin-top:5px;font-size:12px}code{font-size:11px}summary{cursor:pointer;color:#2d5b85}details.notes{padding:12px 20px;margin-top:16px}.scope{margin-top:12px;color:#725316;background:#fff5d9;padding:10px 12px;border-radius:4px}#visible{margin-left:auto;color:#526478}tr[hidden]{display:none}@media print{body{background:white}main{margin:0;padding:0}.controls{display:none}thead{display:table-header-group}tr{break-inside:avoid}}
</style><main><header class="intro"><h1>组件目录</h1><p>可信互联网智能体 · 401-3 · 步骤1</p>"""
        + f"""
<p>采集时间（UTC）：{escape(report['collected_at'])}</p><p>采集范围：{escape(report['scope'])}</p>
<div class="scope">目录记录不等于组件已启用或审查通过。权限、数据范围和风险等级待逐项复核。</div></header>
<div class="counts">{counts}</div><div class="controls"><label>类别 <select id="kind"><option value="">全部类别</option>{options}</select></label><label>检索 <input id="query" placeholder="组件名称、来源或版本"></label><span id="visible"></span></div>
<table><thead><tr><th>组件 / 类型</th><th>版本声明 / 来源</th><th>功能用途</th><th>权限及数据范围</th><th>风险等级</th><th>取证状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<details class="notes" open><summary>本轮范围与限制</summary><ul>{limits}</ul></details>
<details class="notes" {'open' if warnings else ''}><summary>采集提醒（{len(report['warnings'])}）</summary><ul>{warnings}</ul></details>
"""
        + """</main><script>
const kind=document.getElementById('kind'),query=document.getElementById('query');
function filter(){let n=0;for(const row of document.querySelectorAll('tbody tr')){row.hidden=!!((kind.value&&row.dataset.kind!==kind.value)||!row.textContent.toLowerCase().includes(query.value.toLowerCase()));if(!row.hidden)n++;}document.getElementById('visible').textContent='显示 '+n+' 条目录记录';}
kind.addEventListener('change',filter);query.addEventListener('input',filter);filter();
</script></html>"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--working-dir", type=Path, help="可选：显式采集此工作目录；不读取其secret或.env"
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="新的报告目录；拒绝覆盖已有报告"
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    working = args.working_dir.resolve() if args.working_dir else None
    output = args.output_dir.resolve()
    if not (repo / "pyproject.toml").is_file():
        parser.error("repo-root必须包含pyproject.toml")
    if working and not working.is_dir():
        parser.error("working-dir必须为已存在目录")
    if working and output.is_relative_to(working):
        parser.error("报告目录不能位于被采集工作目录中")
    if any(
        (output / name).exists()
        for name in ("components.json", "components.html")
    ):
        parser.error("报告已存在，请指定新的output-dir")
    inventory = Inventory()
    inventory.repository(repo)
    if working:
        inventory.configs(working, "explicit-working-dir", "工作目录配置声明（非运行态核验）")
        inventory.warnings.append(
            "未读取secret中的Provider存储或动态插件注册；模型继承、动态工具、外部服务和传递依赖仍需现场补核。"
        )
    report = inventory.report(working is not None)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "components.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    with (output / "components.html").open("x", encoding="utf-8") as handle:
        handle.write(render(report))
    print(f"已生成{len(inventory.records)}条目录记录（不代表已启用或通过）：{output}")


if __name__ == "__main__":
    main()
