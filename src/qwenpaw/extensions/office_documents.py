"""Bounded Office operations without model-supplied code or shell commands.

Inputs are passive OOXML packages from the active workspace. All writes make
new copies in a fixed artifact directory; original documents are never edited.
"""

from __future__ import annotations

import io
import json
import os
import posixpath
import re
import stat
import uuid
import zipfile
from contextlib import ExitStack
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 10_000_000
MAX_EXPANDED_BYTES = 50_000_000
MAX_CELLS = 20_000
MAX_TEXT = 100_000
FORMATS = {"docx", "xlsx", "pptx"}


def _workspace_path(root: Path, value: str) -> Path:
    from .security.execution_policy import check_path

    check_path(value)
    root = root.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    if not path.resolve().is_relative_to(root):
        raise ValueError("Office 文件必须位于当前工作区")
    for entry in (path, *path.parents):
        if entry == root:
            break
        if entry.is_symlink():
            raise ValueError("Office 文件路径不能包含符号链接")
    return path.resolve()


def _package(path: Path, root: Path) -> bytes:
    if path.suffix.lower().lstrip(".") not in FORMATS:
        raise ValueError("仅支持无宏的 docx、xlsx、pptx 文件")
    root = root.resolve(strict=True)
    parts = path.relative_to(root).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        parent_fd = os.open(root, directory_flags)
        stack.callback(os.close, parent_fd)
        for name in parts[:-1]:
            parent_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            stack.callback(os.close, parent_fd)
        fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Office 输入必须是普通文件")
            if info.st_size > MAX_FILE_BYTES:
                raise ValueError("Office 输入文件不得超过 10 MB")
            data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Office 输入文件不得超过 10 MB")
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 2000 or len(set(names)) != len(names):
            raise ValueError("Office 文件条目数量异常")
        if sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("Office 解压大小不得超过 50 MB")
        for entry in entries:
            name = entry.filename.lower()
            if (
                entry.flag_bits & 1
                or name.startswith("/")
                or ".." in Path(name).parts
                or "\\" in name
                or name.endswith(".bin")
                or "/embeddings/" in name
                or "/activex/" in name
                or "externallink" in name
                or "vbaproject" in name
            ):
                raise ValueError("Office 文件包含加密、宏或嵌入内容")
            if name.endswith((".xml", ".rels")):
                content = package.read(entry)
                declarations = content.upper().replace(b"\x00", b"")
                if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
                    raise ValueError("Office XML 不允许实体声明")
                element = ET.fromstring(content)
                if name.endswith(".rels") and any(
                    node.get("TargetMode", "").lower() == "external"
                    for node in element.iter()
                ):
                    raise ValueError("Office 文件不允许外部链接")
                if (
                    name == "[content_types].xml"
                    and b"macroenabled" in content.lower()
                ):
                    raise ValueError("Office 文件不允许宏")
    return data


def _spreadsheet(data: bytes, *, allow_formulas: bool = False):
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), keep_links=False)
    if (
        len(workbook.worksheets) > 50
        or sum(sheet.max_row * sheet.max_column for sheet in workbook)
        > MAX_CELLS
    ):
        workbook.close()
        raise ValueError("电子表格最多支持 50 张表、20000 个单元格")
    # Downloaded artifacts must not introduce or preserve executable formulas.
    # Formula calculation remains a separate capability, never a shell escape.
    for sheet in workbook:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f" and not allow_formulas:
                    workbook.close()
                    raise ValueError("当前安全入口不处理含公式的工作簿")
    return workbook


def _extract(data: bytes, format: str) -> dict:
    if format == "xlsx":
        # openpyxl never calculates formulas; inspection returns formula text.
        # Mutating or exporting formula workbooks remains separately bounded.
        workbook = _spreadsheet(data, allow_formulas=True)
        try:
            result = {
                "sheets": [
                    {
                        "name": sheet.title,
                        "rows": list(sheet.values),
                    }
                    for sheet in workbook
                ]
            }
        finally:
            workbook.close()
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            if format == "docx":
                names = ["word/document.xml"]
            else:
                names = _slide_names(package)
            result = {"sections": []}
            for name in names:
                document = ET.fromstring(package.read(name))
                paragraphs = [
                    "".join(
                        node.text or ""
                        for node in paragraph.iter()
                        if node.tag.rsplit("}", 1)[-1] == "t"
                    )
                    for paragraph in document.iter()
                    if paragraph.tag.rsplit("}", 1)[-1] == "p"
                ]
                result["sections"].append(
                    {"part": name, "text": "\n".join(paragraphs)}
                )
    if len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_TEXT:
        raise ValueError("文档提取结果超过 100000 字符，请拆分文件")
    return result


def _slide_names(package: zipfile.ZipFile) -> list[str]:
    """Follow presentation order, falling back for minimal fixtures."""
    slides = {
        name
        for name in package.namelist()
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
    }
    main = "ppt/presentation.xml"
    relationships = "ppt/_rels/presentation.xml.rels"
    if (
        main not in package.namelist()
        or relationships not in package.namelist()
    ):
        return sorted(
            slides,
            key=lambda name: int(Path(name).stem.removeprefix("slide")),
        )
    relation_targets = {}
    for node in ET.fromstring(package.read(relationships)):
        target = node.get("Target", "")
        relation_targets[node.get("Id")] = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else "ppt/" + target
        )
    names = []
    for node in ET.fromstring(package.read(main)).iter():
        if node.tag.rsplit("}", 1)[-1] == "sldId":
            relation_id = node.get(
                "{http://schemas.openxmlformats.org/"
                "officeDocument/2006/relationships}id"
            )
            slide_target = relation_targets.get(relation_id)
            if slide_target is None or slide_target not in slides:
                raise ValueError("PPTX 幻灯片关系不完整")
            names.append(slide_target)
    return names


def _persist(root: Path, data: bytes, format: str) -> Path:
    directory = _workspace_path(root, "artifacts/office")
    path = directory / f"document-{uuid.uuid4().hex}.{format}"
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Office 输出文件不得超过 10 MB")
    # Anchor all traversal to open directory descriptors, refusing links even
    # if a checked directory is replaced between validation and creation.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        parent_fd = os.open(root.resolve(strict=True), directory_flags)
        stack.callback(os.close, parent_fd)
        for name in ("artifacts", "office"):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            stack.callback(os.close, parent_fd)
        fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
        except BaseException:
            os.unlink(path.name, dir_fd=parent_fd)
            raise
    return path


def process_document(
    root: Path,
    operation: str,
    file_path: str = "",
    rows: list | None = None,
    updates: list | None = None,
    replacements: list | None = None,
    content: str = "",
) -> dict:
    """Execute a fixed operation and return extracted data or a new path."""
    operations = {
        "inspect",
        "create_xlsx",
        "create_docx",
        "edit_xlsx",
        "replace_text",
        "export_pdf",
    }
    if operation not in operations:
        raise ValueError("不支持的 Office 操作")
    if (
        len(
            json.dumps(
                [rows, updates, replacements, content], ensure_ascii=False
            )
        )
        > MAX_TEXT
    ):
        raise ValueError("Office 操作参数超过 100000 字符")
    if operation == "create_docx":
        from .report_export import _write_docx
        import tempfile

        if not content.strip():
            raise ValueError("Word 正文不能为空")
        with tempfile.TemporaryDirectory(
            prefix="qwenpaw-office-"
        ) as temporary:
            target = Path(temporary) / "document.docx"
            _write_docx(content, "文档", target)
            document_bytes = target.read_bytes()
        return {"file_path": str(_persist(root, document_bytes, "docx"))}
    if operation == "create_xlsx":
        from openpyxl import Workbook

        if (
            not rows
            or any(not isinstance(row, list) for row in rows)
            or len(rows) * max(map(len, rows)) > MAX_CELLS
        ):
            raise ValueError("电子表格需包含 1 至 20000 个单元格")
        workbook = Workbook()
        for row in rows:
            workbook.active.append([_cell_value(value) for value in row])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        return {"file_path": str(_persist(root, output.getvalue(), "xlsx"))}
    path = _workspace_path(root, file_path)
    data = _package(path, root)
    format = path.suffix.lower()[1:]
    if operation == "inspect":
        return _extract(data, format)
    if operation == "edit_xlsx":
        if format != "xlsx" or not updates or len(updates) > 2000:
            raise ValueError("edit_xlsx 需要 xlsx 文件和 1 至 2000 个更新")
        workbook = _spreadsheet(data)
        try:
            for update in updates:
                sheet = workbook[update["sheet"]]
                address = update["cell"]
                if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,4}", address):
                    raise ValueError("需要单个 A1 格式单元格地址")
                sheet[address] = _cell_value(update["value"])
            if (
                sum(sheet.max_row * sheet.max_column for sheet in workbook)
                > MAX_CELLS
            ):
                raise ValueError("更新后的表格超过 20000 个单元格")
            output = io.BytesIO()
            workbook.save(output)
        finally:
            workbook.close()
        return {"file_path": str(_persist(root, output.getvalue(), "xlsx"))}
    if operation == "replace_text":
        from lxml import etree

        if (
            format not in {"docx", "pptx"}
            or not replacements
            or len(replacements) > 100
        ):
            raise ValueError("replace_text 需要 docx/pptx 和 1 至 100 组替换")
        for replacement in replacements:
            if not replacement.get("find") or not isinstance(
                replacement.get("replace"), str
            ):
                raise ValueError("替换项需要非空 find 和文本 replace")
        _extract(data, format)  # Bound total text before replacement work.
        output = io.BytesIO()
        count = 0
        total_text = 0
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            with zipfile.ZipFile(
                output, "w", zipfile.ZIP_DEFLATED
            ) as target_package:
                for entry in source.infolist():
                    payload = source.read(entry)
                    if entry.filename == "word/document.xml" or re.fullmatch(
                        r"ppt/slides/slide\d+\.xml", entry.filename
                    ):
                        document = etree.fromstring(
                            payload,
                            parser=etree.XMLParser(
                                resolve_entities=False,
                                no_network=True,
                                load_dtd=False,
                            ),
                        )
                        for node in document.iter():
                            if (
                                isinstance(node.tag, str)
                                and node.tag.rsplit("}", 1)[-1] == "t"
                                and node.text
                            ):
                                for replacement in replacements:
                                    matches = node.text.count(
                                        replacement["find"]
                                    )
                                    size = len(node.text) + matches * (
                                        len(replacement["replace"])
                                        - len(replacement["find"])
                                    )
                                    if size > MAX_TEXT:
                                        raise ValueError(
                                            "替换后的文本超过 100000 字符"
                                        )
                                    count += node.text.count(
                                        replacement["find"]
                                    )
                                    node.text = node.text.replace(
                                        replacement["find"],
                                        replacement["replace"],
                                    )
                                total_text += len(node.text)
                                if total_text > MAX_TEXT:
                                    raise ValueError(
                                        "替换后的文本超过 100000 字符"
                                    )
                        payload = etree.tostring(
                            document, encoding="utf-8", xml_declaration=True
                        )
                    target_package.writestr(entry.filename, payload)
        if not count:
            raise ValueError("未匹配文本；此入口仅替换同一文本片段内的内容")
        return {
            "file_path": str(_persist(root, output.getvalue(), format)),
            "replacements": count,
        }
    from .report_export import _write_pdf
    import tempfile

    extracted = _extract(data, format)
    text = json.dumps(extracted, ensure_ascii=False, default=str, indent=2)
    # Rebuild passive text with the trusted renderer; never ask LibreOffice
    # to open the supplied package (fields, links and formulas cannot run).
    with tempfile.TemporaryDirectory(prefix="qwenpaw-office-") as temporary:
        target = Path(temporary) / "document.pdf"
        _write_pdf(text, "文档文本导出", target)
        pdf_bytes = target.read_bytes()
    return {
        "file_path": str(_persist(root, pdf_bytes, "pdf")),
        "note": "文本重排导出，不保留原版式",
    }


def _cell_value(value):
    if not isinstance(value, (str, int, float, bool, type(None))):
        raise ValueError("单元格仅支持文本、数字、布尔值或空值")
    if isinstance(value, str) and value.lstrip().startswith("="):
        raise ValueError("此入口不接受公式，请使用普通值")
    return value
