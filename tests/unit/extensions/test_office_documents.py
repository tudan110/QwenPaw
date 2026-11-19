"""Functional production Office operations and adversarial package checks."""

import importlib.util
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest
from docx import Document
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[3] / "src/qwenpaw"


@pytest.fixture
def office(monkeypatch):
    policy = ModuleType("qwenpaw.extensions.security.execution_policy")
    policy.check_path = lambda path: None
    monkeypatch.setitem(sys.modules, policy.__name__, policy)
    name = "qwenpaw.extensions.office_documents"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "extensions/office_documents.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def document(path):
    doc = Document()
    doc.add_paragraph("数据库需要处理")
    doc.save(path)


def test_xlsx_create_edit_read_source_preserved(office, tmp_path):
    created = office.process_document(
        tmp_path, "create_xlsx", rows=[["资源", "数量"], ["MySQL", 2]]
    )
    original = Path(created["file_path"])
    edited = office.process_document(
        tmp_path,
        "edit_xlsx",
        str(original),
        updates=[{"sheet": "Sheet", "cell": "B2", "value": 3}],
    )
    assert original != Path(edited["file_path"])
    assert (
        office.process_document(tmp_path, "inspect", str(original))["sheets"][
            0
        ]["rows"][1][1]
        == 2
    )
    assert (
        office.process_document(tmp_path, "inspect", edited["file_path"])[
            "sheets"
        ][0]["rows"][1][1]
        == 3
    )
    assert original.is_relative_to(tmp_path / "artifacts/office")


def test_docx_replacement_and_inspection(office, tmp_path):
    source = tmp_path / "document.docx"
    document(source)
    result = office.process_document(
        tmp_path,
        "replace_text",
        str(source),
        replacements=[{"find": "数据库", "replace": "缓存"}],
    )
    assert result["replacements"] == 1
    assert (
        "缓存需要处理"
        in office.process_document(tmp_path, "inspect", result["file_path"])[
            "sections"
        ][0]["text"]
    )
    assert "数据库需要处理" in Document(source).paragraphs[0].text


def test_pptx_text_inspection_and_replacement(office, tmp_path):
    source = tmp_path / "presentation.pptx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(
            "ppt/slides/slide1.xml",
            '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r>'
            "<a:t>告警报告</a:t></a:r></a:p></p:sld>",
        )
    result = office.process_document(
        tmp_path,
        "replace_text",
        str(source),
        replacements=[{"find": "告警", "replace": "巡检"}],
    )
    assert (
        "巡检报告"
        in office.process_document(tmp_path, "inspect", result["file_path"])[
            "sections"
        ][0]["text"]
    )


@pytest.mark.parametrize(
    "name,payload",
    [
        ("word/vbaProject.bin", b"macro"),
        ("word/embeddings/content.docx", b"nested"),
        ("../outside.xml", b"<root/>"),
        (
            "word/document.xml",
            b'<!DOCTYPE x [<!ENTITY e "payload">]><x>&e;</x>',
        ),
        (
            "word/_rels/document.xml.rels",
            b'<Relationships><Relationship TargetMode="External" '
            b'Target="http://example.com"/></Relationships>',
        ),
    ],
)
def test_active_packages_rejected(office, tmp_path, name, payload):
    source = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(name, payload)
    with pytest.raises(ValueError):
        office.process_document(tmp_path, "inspect", str(source))
    assert not (tmp_path / "artifacts").exists()


def test_workspace_boundary_and_symlinks(office, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.docx"
    document(outside)
    with pytest.raises(ValueError, match="工作区"):
        office.process_document(workspace, "inspect", str(outside))
    linked = workspace / "linked.docx"
    linked.symlink_to(outside)
    with pytest.raises(ValueError):
        office.process_document(workspace, "inspect", str(linked))
    (workspace / "artifacts").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        office.process_document(workspace, "create_xlsx", rows=[[1]])


def test_formulas_and_oversized_dimensions_rejected(office, tmp_path):
    with pytest.raises(ValueError, match="公式"):
        office.process_document(
            tmp_path,
            "create_xlsx",
            rows=[['=WEBSERVICE("http://example.com")']],
        )
    source = tmp_path / "formula.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "=1+2"
    workbook.save(source)
    result = office.process_document(tmp_path, "inspect", str(source))
    assert result["sheets"][0]["rows"][0][0] == "=1+2"
    with pytest.raises(ValueError, match="公式"):
        office.process_document(
            tmp_path,
            "edit_xlsx",
            str(source),
            updates=[{"sheet": "Sheet", "cell": "B1", "value": 3}],
        )
    workbook.active["A1"] = 1
    workbook.active["ZZ99999"] = 2
    workbook.save(source)
    with pytest.raises(ValueError, match="单元格"):
        office.process_document(tmp_path, "inspect", str(source))


def test_bomb_size_limit_before_decompression(office, tmp_path, monkeypatch):
    source = tmp_path / "bomb.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", b" " * 2000)
    monkeypatch.setattr(office, "MAX_EXPANDED_BYTES", 1000)
    with pytest.raises(ValueError, match="解压"):
        office.process_document(tmp_path, "inspect", str(source))


def test_directory_swap_cannot_redirect_office_output(
    office, tmp_path, monkeypatch
):
    outside = tmp_path / "outside"
    outside.mkdir()
    mkdir = office.os.mkdir

    def swap(name, mode=0o777, *, dir_fd=None):
        if name == "artifacts":
            (tmp_path / "artifacts").symlink_to(
                outside, target_is_directory=True
            )
            raise FileExistsError(name)
        return mkdir(name, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(office.os, "mkdir", swap)
    with pytest.raises(OSError):
        office.process_document(tmp_path, "create_xlsx", rows=[[1]])
    assert list(outside.iterdir()) == []


def test_output_never_overwrites_existing_document(
    office, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    monkeypatch.setattr(
        office.uuid, "uuid4", lambda: SimpleNamespace(hex="a" * 32)
    )
    result = office.process_document(tmp_path, "create_xlsx", rows=[[1]])
    original = Path(result["file_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        office.process_document(tmp_path, "create_xlsx", rows=[[2]])
    assert Path(result["file_path"]).read_bytes() == original


def test_pptx_uses_slide_relationship_order_with_numeric_fallback(
    office, tmp_path
):
    source = tmp_path / "ordered.pptx"
    with zipfile.ZipFile(source, "w") as package:
        for index in (1, 10, 2):
            package.writestr(
                f"ppt/slides/slide{index}.xml",
                '<p:sld xmlns:p="p" xmlns:a="a"><a:p>'
                f"<a:t>{index}</a:t></a:p></p:sld>",
            )
    result = office.process_document(tmp_path, "inspect", str(source))
    assert [section["text"] for section in result["sections"]] == [
        "1",
        "2",
        "10",
    ]
    with zipfile.ZipFile(source, "a") as package:
        package.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="p" '
            'xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships"><p:sldIdLst>'
            '<p:sldId id="1" r:id="rId10"/>'
            '<p:sldId id="2" r:id="rId2"/>'
            '<p:sldId id="3" r:id="rId1"/>'
            "</p:sldIdLst></p:presentation>",
        )
        package.writestr(
            "ppt/_rels/presentation.xml.rels",
            "<Relationships>"
            + "".join(
                f'<Relationship Id="rId{i}" Target="slides/slide{i}.xml"/>'
                for i in (1, 2, 10)
            )
            + "</Relationships>",
        )
    result = office.process_document(tmp_path, "inspect", str(source))
    assert [section["text"] for section in result["sections"]] == [
        "10",
        "2",
        "1",
    ]


def test_utf16_entity_declarations_rejected(office, tmp_path):
    source = tmp_path / "unsafe.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-16"?>'
                '<!DOCTYPE x [<!ENTITY e "payload">]><x>&e;</x>'
            ).encode("utf-16"),
        )
    with pytest.raises(ValueError, match="实体"):
        office.process_document(tmp_path, "inspect", str(source))
