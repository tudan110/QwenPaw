"""Office tool registration, production permissions and file operations."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from test_report_export_flow import flow  # noqa: F401

ROOT = Path(__file__).resolve().parents[3] / "src/qwenpaw"


@pytest.fixture
def office_tool(flow, monkeypatch):  # noqa: F811
    modules = {}
    for name, relative in (
        (
            "qwenpaw.extensions.office_documents",
            "extensions/office_documents.py",
        ),
        (
            "qwenpaw.agents.tools.office_document",
            "agents/tools/office_document.py",
        ),
    ):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules["qwenpaw.agents.tools.office_document"]


async def test_registered_tool_is_available_to_ordinary_production_users(
    office_tool, flow, tmp_path  # noqa: F811
):
    from qwenpaw.runtime.tool_registry import get_builtin_tool_funcs

    assert office_tool.process_office_document in get_builtin_tool_funcs()
    params = {
        "operation": "create_xlsx",
        "rows": [["资源", "数量"], ["MySQL", 2]],
    }
    assert (
        await flow.policy.check_tool("process_office_document", params)
        is False
    )
    result = await office_tool.process_office_document(**params)
    assert result.state == "ok", result.content
    path = Path(json.loads(result.content[0]["text"])["file_path"])
    assert path.parent == tmp_path / "artifacts/office"
    result = await office_tool.process_office_document("inspect", str(path))
    assert result.state == "ok"
    assert json.loads(result.content[0]["text"])["sheets"][0]["rows"][1] == [
        "MySQL",
        2,
    ]
    with pytest.raises(PermissionError):
        await flow.policy.check_tool("write_file", {"file_path": "script.py"})
    with pytest.raises(PermissionError):
        flow.policy.check_shell('python -c "print(1)"')


async def test_malformed_input_and_outside_workspace_return_errors(
    office_tool, tmp_path
):
    source = tmp_path / "bad.docx"
    source.write_bytes(b"not a document")
    assert (
        await office_tool.process_office_document("inspect", str(source))
    ).state == "error"
    assert (
        await office_tool.process_office_document(
            "inspect", str(tmp_path.parent / "outside.docx")
        )
    ).state == "error"
    assert not (tmp_path / "artifacts").exists()


async def test_creation_uses_existing_report_renderer(office_tool, tmp_path):
    from docx import Document

    result = await office_tool.process_office_document(
        "create_docx", content="# 报告\n中文验证"
    )
    assert result.state == "ok", result.content
    path = Path(json.loads(result.content[0]["text"])["file_path"])
    assert "中文验证" in "\n".join(
        paragraph.text for paragraph in Document(path).paragraphs
    )


async def test_office_pdf_text_export_uses_real_renderer(office_tool):
    from pypdf import PdfReader

    created = await office_tool.process_office_document(
        "create_docx", content="# 导出验收\n中文资源清单"
    )
    assert created.state == "ok", created.content
    source = Path(json.loads(created.content[0]["text"])["file_path"])
    original = source.read_bytes()
    result = await office_tool.process_office_document(
        "export_pdf", str(source)
    )
    assert result.state == "ok", result.content
    metadata = json.loads(result.content[0]["text"])
    output = Path(metadata["file_path"])
    assert output.suffix == ".pdf"
    assert output.parent == source.parent
    assert "不保留原版式" in metadata["note"]
    assert "中文资源清单" in "\n".join(
        page.extract_text() or "" for page in PdfReader(output).pages
    )
    assert source.read_bytes() == original
