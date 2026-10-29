from __future__ import annotations

import hashlib
import re

from raggg.models import Chunk, Document
from raggg.preprocessing.cleaner import clean_text


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
FORMULA_MARKERS = ("$$", "\\nabla", "\\partial", "\\cdot", "\\times", "∇", "∮", "∫")
TRANSPARENT_HEADINGS = {"正文抽取", "案例教程抽取"}
MAINTENANCE_SECTION_HEADINGS = {"待补图片清单", "页内/相关链接", "后续图片补充"}
MAINTENANCE_NOTE_RE = re.compile(
    r"^>?\s*(?:图示要点|图片说明)[：:].*(?:后续审查|再补图|后续补图)"
)


def _chunk_id(source_type: str, relative_path: str, index: int, content: str) -> str:
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    return f"{source_type}:{relative_path}:{index}:{digest}"


def _paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    paragraphs: list[str] = []
    for part in parts:
        lines = [line.strip() for line in part.splitlines() if line.strip()]
        paragraphs.extend(lines)
    return paragraphs


def _prepare_index_text(text: str) -> str:
    """Remove editorial scaffolding while preserving the source Markdown."""
    kept_lines: list[str] = []
    skipped_section_level: int | None = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        heading = HEADING_RE.match(stripped)

        if skipped_section_level is not None:
            if not heading or len(heading.group(1)) > skipped_section_level:
                continue
            skipped_section_level = None

        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if title in MAINTENANCE_SECTION_HEADINGS:
                skipped_section_level = level
                continue
            if title in TRANSPARENT_HEADINGS:
                continue

        if MAINTENANCE_NOTE_RE.match(stripped):
            continue
        kept_lines.append(raw_line)

    return "\n".join(kept_lines)


def chunk_document(document: Document, target_chars: int = 800) -> list[Chunk]:
    text = clean_text(_prepare_index_text(document.text))
    paragraphs = _paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[Chunk] = []
    current: list[str] = []
    current_section = document.title

    def flush() -> None:
        if not current:
            return
        if all(HEADING_RE.match(item) for item in current):
            current.clear()
            return
        content = "\n\n".join(current).strip()
        index = len(chunks)
        metadata = dict(document.metadata)
        metadata["has_formula"] = any(marker in content for marker in FORMULA_MARKERS)
        metadata["has_wikilink"] = "[[" in content and "]]" in content
        chunks.append(
            Chunk(
                id=_chunk_id(document.source_type, document.relative_path, index, content),
                source_type=document.source_type,
                source_path=str(document.source_path),
                relative_path=document.relative_path,
                title=document.title,
                section=current_section,
                content=content,
                links=list(document.links),
                images=list(document.images),
                metadata=metadata,
            )
        )
        current.clear()

    for paragraph in paragraphs:
        heading = HEADING_RE.match(paragraph)
        if heading:
            flush()
            current_section = heading.group(2).strip()
            current.append(paragraph)
            continue

        current_len = sum(len(item) for item in current)
        current_text = "\n".join(current)
        formula_nearby = "$$" in current_text or "$$" in paragraph
        if current and current_len + len(paragraph) > target_chars and not formula_nearby:
            flush()
        current.append(paragraph)

    flush()
    return chunks


def chunk_documents(documents: list[Document], target_chars: int = 800) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, target_chars=target_chars))
    return chunks
