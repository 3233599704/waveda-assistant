from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from raggg.config import Settings


MARKDOWN_EXTENSIONS = {".md", ".markdown"}
HTML_EXTENSIONS = {".html", ".htm"}
TEXT_EXTENSIONS = {".txt"}
PDF_EXTENSIONS = {".pdf"}
WORD_EXTENSIONS = {".docx"}
SUPPORTED_EXTENSIONS = MARKDOWN_EXTENSIONS | HTML_EXTENSIONS | TEXT_EXTENSIONS | PDF_EXTENSIONS | WORD_EXTENSIONS


@dataclass(frozen=True)
class IngestReport:
    original_path: Path
    imported_path: Path
    source_format: str


def _source_format(suffix: str) -> str:
    if suffix in MARKDOWN_EXTENSIONS:
        return "markdown"
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in WORD_EXTENSIONS:
        return "word"
    raise ValueError(f"不支持的文件类型: {suffix or '(无扩展名)'}")


def _unique_destination(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _write_markdown_import(source: Path, destination: Path, text: str) -> None:
    destination.write_text(f"# {source.stem}\n\n{text.strip()}\n", encoding="utf-8")


def _extract_pdf_text(source: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 PDF 解析库 pypdf，请先安装依赖后再导入 PDF。") from exc

    reader = PdfReader(str(source))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def _extract_docx_text(source: Path) -> str:
    try:
        with zipfile.ZipFile(source) as archive:
            xml_bytes = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError(f"无法读取 Word 正文: {source}") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError(f"不是有效的 docx 文件: {source}") from exc

    root = ElementTree.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        pieces = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def ingest_document(settings: Settings, source_path: Path | str) -> IngestReport:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"文件不存在: {source}")
    if not source.is_file():
        raise ValueError(f"请选择一个文件: {source}")

    suffix = source.suffix.lower()
    source_format = _source_format(suffix)
    import_dir = settings.project_root / "knowledge_base" / "05_reference" / "imported"
    import_dir.mkdir(parents=True, exist_ok=True)

    if source_format == "text":
        destination = _unique_destination(import_dir, f"{source.stem}.md")
        text = source.read_text(encoding="utf-8", errors="ignore")
        _write_markdown_import(source, destination, text)
    elif source_format == "pdf":
        destination = _unique_destination(import_dir, f"{source.stem}.md")
        _write_markdown_import(source, destination, _extract_pdf_text(source))
    elif source_format == "word":
        destination = _unique_destination(import_dir, f"{source.stem}.md")
        _write_markdown_import(source, destination, _extract_docx_text(source))
    else:
        destination = _unique_destination(import_dir, source.name)
        shutil.copy2(source, destination)

    return IngestReport(
        original_path=source,
        imported_path=destination,
        source_format=source_format,
    )
