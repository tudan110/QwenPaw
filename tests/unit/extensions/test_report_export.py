"""Real document generation and export boundary regressions."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
from docx import Document

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "src/qwenpaw/extensions/report_export.py"
)
# Can also be run without importing the complete application dependency tree.
_SPEC = importlib.util.spec_from_file_location("report_export", _MODULE_PATH)
renderer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(renderer)

CONTENT = """# 告警统计报告
当前共有 2 条告警。
- 数据库连接异常
1. 人工核查
| 级别 | 数量 |
| --- | --- |
| 严重 | 2 |
```python
print('这是报告正文，不执行')
```
<img src="https://example.invalid/private">
"""


def export(tmp_path, content=CONTENT, title="中文报告", format="docx"):
    return renderer.export_report(
        content, title, format, "gateway", tmp_path / "reports"
    )


def test_docx_contains_chinese_table_code_and_literal_html(tmp_path):
    path = export(tmp_path)
    document = Document(path)
    text = "\n".join(p.text for p in document.paragraphs)
    assert "告警统计报告" in text
    assert "数据库连接异常" in text
    assert "print('这是报告正文，不执行')" in text
    assert '<img src="https://example.invalid/private">' in text
    rows = [[c.text for c in row.cells] for row in document.tables[0].rows]
    assert rows == [
        ["级别", "数量"],
        ["严重", "2"],
    ]
    assert not any(
        "image" in rel.reltype for rel in document.part.rels.values()
    )


def test_markdown_is_preserved_and_names_are_unique(tmp_path):
    first = export(tmp_path, format="md", title="../../报告 [下载]")
    second = export(tmp_path, format="md", title="../../报告 [下载]")
    assert first != second
    assert first.parent == (tmp_path / "reports/gateway").resolve()
    assert first.read_text() == CONTENT
    assert "[" not in first.name and ".." not in first.name


def test_rejects_excessive_paragraph_count(tmp_path):
    with pytest.raises(ValueError, match="5000"):
        export(tmp_path, content="正文\n" * 5001)
    assert not (tmp_path / "reports").exists()


def test_rejects_excessive_table_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "MAX_TABLE_CELLS", 4)
    with pytest.raises(ValueError, match="单元格"):
        export(
            tmp_path, content="| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |"
        )
    assert list((tmp_path / "reports/gateway").iterdir()) == []


@pytest.mark.parametrize("agent", ["", "..", "../secret", "/tmp", "a/b"])
def test_rejects_agent_path_traversal(tmp_path, agent):
    with pytest.raises(ValueError, match="智能体"):
        renderer.export_report(CONTENT, "报告", "md", agent, tmp_path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"content": " "},
        {"content": "x" * (renderer.MAX_CONTENT_BYTES + 1)},
        {"content": "bad\x00text"},
        {"title": ""},
        {"title": "x" * 201},
        {"format": "html"},
        {"format": "../../pdf"},
    ],
)
def test_rejects_invalid_input(tmp_path, kwargs):
    with pytest.raises(ValueError):
        export(tmp_path, **kwargs)
    assert not (tmp_path / "reports").exists()


def test_rejects_agent_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "reports"
    root.mkdir()
    (root / "gateway").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        export(tmp_path)
    assert list(outside.iterdir()) == []


def test_rejects_report_root_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        export(tmp_path)


def test_pdf_fixed_converter_no_shell_and_private_profile(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(renderer, "_libreoffice", lambda: "/usr/bin/soffice")

    def convert(command, **kwargs):
        assert command[0] == "/usr/bin/soffice"
        assert "--headless" in command
        assert "pdf:writer_pdf_Export" in command
        assert command[1].startswith("-env:UserInstallation=file://")
        assert kwargs["timeout"] == 60
        assert "shell" not in kwargs
        source = Path(command[-1])
        assert source.suffix == ".docx"
        assert "告警统计报告" in "\n".join(
            p.text for p in Document(source).paragraphs
        )
        source.with_suffix(".pdf").write_bytes(b"%PDF-1.7\nverified")

    monkeypatch.setattr(renderer.subprocess, "run", convert)
    result = export(tmp_path, format="pdf")
    assert result.read_bytes().startswith(b"%PDF-")
    assert list(result.parent.iterdir()) == [result]


@pytest.mark.parametrize("outcome", ["timeout", "missing", "invalid"])
def test_pdf_failure_leaves_no_downloadable_artifact(
    tmp_path, monkeypatch, outcome
):
    monkeypatch.setattr(renderer, "_libreoffice", lambda: "/usr/bin/soffice")

    def convert(command, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if outcome == "invalid":
            Path(command[-1]).with_suffix(".pdf").write_bytes(b"not a PDF")

    monkeypatch.setattr(renderer.subprocess, "run", convert)
    with pytest.raises(RuntimeError):
        export(tmp_path, format="pdf")
    assert list((tmp_path / "reports/gateway").iterdir()) == []


def test_real_pdf_contains_chinese_text(tmp_path):
    try:
        renderer._libreoffice()
    except RuntimeError:
        pytest.skip("LibreOffice is not installed")
    pypdf = pytest.importorskip("pypdf")
    result = export(tmp_path, format="pdf")
    document = pypdf.PdfReader(result)
    assert len(document.pages) >= 1
    text = "".join(page.extract_text() for page in document.pages)
    assert "告警统计报告" in text
    assert "严重" in text
