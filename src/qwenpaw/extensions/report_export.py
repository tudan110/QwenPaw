"""Bounded text-to-document export without user-supplied code or paths.

Markdown headings, lists, tables and fenced code receive basic formatting.
Links, HTML, images and other markup remain literal text: rendering never
fetches resources or executes active content.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

MAX_CONTENT_BYTES = 1_000_000
MAX_CONTENT_LINES = 5000
MAX_TABLE_CELLS = 2000
FORMATS = frozenset({"pdf", "docx", "md"})
_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CONVERTERS = (
    "/usr/bin/libreoffice",
    "/usr/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


def _libreoffice() -> str:
    for candidate in _CONVERTERS:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("PDF 导出需要镜像内预装 LibreOffice Writer")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_separator(line: str) -> bool:
    return "|" in line and all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in _cells(line)
    )


def _write_docx(content: str, title: str, target: Path) -> None:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Liberation Sans"
    normal.font.size = Pt(11)
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    fonts.set(qn("w:eastAsia"), "WenQuanYi Zen Hei")
    document.core_properties.title = title
    document.add_heading(title, level=0)
    lines = content.splitlines()
    index = 0
    in_code = False
    table_cells = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            run = document.add_paragraph().add_run(line)
            run.font.name = "Liberation Mono"
            run.font.size = Pt(9)
            continue
        if (
            "|" in line
            and index < len(lines)
            and _table_separator(lines[index])
        ):
            headers = _cells(line)
            if len(headers) > 32:
                raise ValueError("报告表格最多支持 32 列")
            table_cells += len(headers)
            if table_cells > MAX_TABLE_CELLS:
                raise ValueError("报告表格总单元格不得超过 2000 个")
            table = document.add_table(rows=1, cols=len(headers))
            table.style = "Table Grid"
            for cell, text in zip(table.rows[0].cells, headers):
                cell.text = text
            repeat = OxmlElement("w:tblHeader")
            table.rows[0]._tr.get_or_add_trPr().append(repeat)
            index += 1
            while index < len(lines) and "|" in lines[index]:
                values = _cells(lines[index])
                if len(values) != len(headers):
                    break
                table_cells += len(values)
                if table_cells > MAX_TABLE_CELLS:
                    raise ValueError("报告表格总单元格不得超过 2000 个")
                for cell, text in zip(table.add_row().cells, values):
                    cell.text = text
                index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        bullet = re.match(r"^\s*[-*+]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if heading:
            document.add_heading(heading[2], level=len(heading[1]))
        elif bullet:
            document.add_paragraph(bullet[1], style="List Bullet")
        elif numbered:
            document.add_paragraph(numbered[1], style="List Number")
        else:
            document.add_paragraph(line)
    document.save(target)


def _write_pdf(content: str, title: str, target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="qwenpaw-pdf-") as directory:
        temporary = Path(directory)
        source = temporary / "report.docx"
        _write_docx(content, title, source)
        command = [
            _libreoffice(),
            f"-env:UserInstallation={(temporary / 'profile').as_uri()}",
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(temporary),
            str(source),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                timeout=60,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=temporary,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("PDF 转换失败或超时，请检查导出服务") from exc
        result = temporary / "report.pdf"
        if not result.is_file():
            raise RuntimeError("PDF 转换未生成文件")
        data = result.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise RuntimeError("PDF 转换返回无效文件")
        target.write_bytes(data)


def export_report(
    content: str,
    title: str,
    format: str = "pdf",
    agent_id: str = "",
    reports_root: Path | None = None,
) -> Path:
    """Render supplied text into one uniquely named agent report.

    The caller supplies trusted server-side agent context and reports_root;
    neither should be exposed as model-controllable tool arguments.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("报告正文不能为空")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("报告正文不得超过 1 MB")
    if len(content.splitlines()) > MAX_CONTENT_LINES:
        raise ValueError("报告正文不得超过 5000 行")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in content):
        raise ValueError("报告正文包含不支持的控制字符")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("报告标题需为 1 至 200 个字符")
    if any(ord(char) < 32 for char in title):
        raise ValueError("报告标题包含不支持的控制字符")
    if format not in FORMATS:
        raise ValueError("报告格式仅支持 pdf、docx、md")
    if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
        raise ValueError("无效的智能体标识")
    if reports_root is None:
        raise ValueError("缺少服务端报告目录")
    root = Path(reports_root).absolute()
    if root.is_symlink():
        raise ValueError("报告目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    directory = root / agent_id
    if directory.is_symlink():
        raise ValueError("智能体报告目录不能是符号链接")
    directory.mkdir(exist_ok=True)
    if directory.resolve().parent != root:
        raise ValueError("报告目录超出允许范围")
    slug = re.sub(r"[^\w\-]+", "-", title.strip()).strip("-_")[:60]
    name = f"{slug or 'report'}-{uuid.uuid4().hex}.{format}"
    target = directory / name
    # Finish conversion before exposing a downloadable suffix to readers.
    fd, temporary_name = tempfile.mkstemp(prefix=".export-", dir=directory)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        if format == "md":
            temporary.write_text(content, encoding="utf-8")
        elif format == "docx":
            _write_docx(content, title, temporary)
        else:
            _write_pdf(content, title, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
