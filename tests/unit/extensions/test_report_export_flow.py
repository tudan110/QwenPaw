"""Exercise the real export tool, production gate and download router.

Only unrelated runtime/identity services are replaced; rendering and HTTP
file delivery use their real implementations. No live SSO credentials.
"""

import importlib.util
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import unquote

import pytest
from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[3] / "src/qwenpaw"


@pytest.fixture
def flow(monkeypatch, tmp_path):
    def module(name, **values):
        result = ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        result = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, result)
        spec.loader.exec_module(result)
        return result

    for package in (
        "qwenpaw",
        "qwenpaw.agents",
        "qwenpaw.agents.tools",
        "qwenpaw.app",
        "qwenpaw.config",
        "qwenpaw.runtime",
        "qwenpaw.extensions",
        "qwenpaw.extensions.api",
        "qwenpaw.extensions.security",
        "agentscope",
    ):
        module(package, __path__=[])
    module(
        "agentscope.message",
        TextBlock=lambda **kw: kw,
        ToolResultState=SimpleNamespace(SUCCESS="ok", ERROR="error"),
    )
    module("agentscope.tool", ToolChunk=lambda **kw: SimpleNamespace(**kw))
    load("qwenpaw.runtime.tool_registry", "runtime/tool_registry.py")
    module("qwenpaw.app.agent_context", get_current_agent_id=lambda: "gateway")
    paths = module(
        "qwenpaw.extensions.runtime_data_paths",
        REPORTS_DATA_DIR=tmp_path / "reports",
    )
    module(
        "qwenpaw.constant",
        WORKING_DIR=tmp_path,
        SECRET_DIR=tmp_path / "secrets",
        BACKUP_DIR=tmp_path / "backups",
        EnvVarLoader=SimpleNamespace(get_str=os.environ.get),
    )
    module(
        "qwenpaw.config.context", get_current_workspace_dir=lambda: tmp_path
    )
    identity = ContextVar(
        "test_export_identity", default=SimpleNamespace(is_admin=False)
    )
    module(
        "qwenpaw.extensions.api.access_session",
        CURRENT_IDENTITY=identity,
        get_access_store=lambda: None,
        user_subject=lambda user: user,
    )
    module("qwenpaw.extensions.api.sso_settings_store")
    module("qwenpaw.extensions.api.sso_backend", _validate_inoe_token=None)
    module("qwenpaw.extensions.api.sso_auth", extract_user=lambda user: user)
    module("qwenpaw.extensions.security.managed_integrity", inspect_skill=None)
    load(
        "qwenpaw.extensions.security.business_reads",
        "extensions/security/business_reads.py",
    )
    load(
        "qwenpaw.extensions.security.skill_scripts",
        "extensions/security/skill_scripts.py",
    )
    load(
        "qwenpaw.extensions.security.skill_cli",
        "extensions/security/skill_cli.py",
    )
    renderer = load(
        "qwenpaw.extensions.report_export", "extensions/report_export.py"
    )
    tool = load(
        "qwenpaw.agents.tools.export_report", "agents/tools/export_report.py"
    )
    policy = load(
        "qwenpaw.extensions.security.execution_policy",
        "extensions/security/execution_policy.py",
    )
    load("qwenpaw.extensions.security.agent_export", "extensions/security/agent_export.py")
    router = load(
        "qwenpaw.extensions.api.agent_reports",
        "extensions/api/agent_reports.py",
    )
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "true")
    return SimpleNamespace(
        tool=tool, policy=policy, router=router, renderer=renderer, paths=paths
    )


@pytest.mark.parametrize("format", ["docx", "md", "pdf"])
async def test_non_production_export_and_download(flow, format, monkeypatch):
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")
    if format == "pdf":
        try:
            flow.renderer._libreoffice()
        except RuntimeError:
            pytest.skip("LibreOffice is not installed")
    params = {
        "content": "# 告警报告\n中文导出验证",
        "title": "报告",
        "format": format,
    }
    assert await flow.policy.check_tool("export_report", params) is False
    result = await flow.tool.export_report(**params)
    assert result.state == "ok", result.content
    href = result.content[0]["text"].split("](", 1)[1][:-1]
    assert href.startswith("/api/portal/agents/gateway/reports/")
    app = FastAPI()
    app.include_router(flow.router.router, prefix="/api/portal")
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(href)
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    path = (
        flow.paths.REPORTS_DATA_DIR
        / "gateway"
        / unquote(href.rsplit("/", 1)[1])
    )
    assert response.content == path.read_bytes()
    if format == "pdf":
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF-")
    elif format == "docx":
        assert "wordprocessingml" in response.headers["content-type"]
        assert "中文导出验证" in "\n".join(
            p.text for p in Document(path).paragraphs
        )


async def test_production_blocks_unstructured_export_before_artifact_creation(flow):
    for tool, options in (
        ("export_report", {}), ("process_office_document", {"operation": "create_xlsx"}),
        ("send_file_to_user", {}), ("append_file", {}), ("edit_file", {}),
    ):
        with pytest.raises(PermissionError, match="导出策略已拦截"):
            await flow.policy.check_tool(tool, options)
    assert await flow.policy.check_tool("process_office_document", {"operation": "inspect"}) is False
    for format in ("pdf", "docx", "md"):
        result = await flow.tool.export_report("工单明细", format=format)
        assert result.state == "error"
        assert "导出策略已拦截" in result.content[0]["text"]
        assert "](" not in result.content[0]["text"]
    assert not flow.paths.REPORTS_DATA_DIR.exists()


async def test_general_writes_and_shell_stay_denied(flow):
    with pytest.raises(PermissionError):
        await flow.policy.check_tool("write_file", {"file_path": "script.py"})
    with pytest.raises(PermissionError):
        flow.policy.check_shell('python -c "print(1)"')


async def test_export_error_is_not_a_download_or_markdown_fallback(flow):
    result = await flow.tool.export_report("正文", format="html")
    assert result.state == "error"
    assert "](" not in result.content[0]["text"]
    assert not flow.paths.REPORTS_DATA_DIR.exists()


async def test_default_pdf_and_default_tool_registration(flow, monkeypatch):
    from qwenpaw.runtime.tool_registry import get_builtin_tool_funcs

    assert flow.tool.export_report in get_builtin_tool_funcs()
    monkeypatch.setenv("QWENPAW_PRODUCTION_GUARDS", "false")

    def render(content, title, format, agent_id, reports_root):
        assert format == "pdf"
        assert agent_id == "gateway"
        assert reports_root == flow.paths.REPORTS_DATA_DIR
        return reports_root / agent_id / "report.pdf"

    monkeypatch.setattr(flow.renderer, "export_report", render)
    result = await flow.tool.export_report("中文正文")
    assert result.state == "ok"
    assert "report.pdf" in result.content[0]["text"]


@pytest.mark.parametrize("tool_name", ["write_file", "export_report"])
async def test_fallback_runtime_guard_blocks_export(flow, tool_name):
    from agentscope.permission import PermissionBehavior
    from qwenpaw.runtime.tool_guard import (
        _guarded_tool_call,
        _guarded_tool_check_permissions,
    )

    tool = SimpleNamespace(name=tool_name)
    decision = await _guarded_tool_check_permissions(tool, {}, None)
    assert decision.behavior == PermissionBehavior.DENY
    assert "导出策略已拦截" in decision.message
    with pytest.raises(PermissionError, match="导出策略已拦截"):
        await _guarded_tool_call(tool)
