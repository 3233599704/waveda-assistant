from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from raggg.loaders.markdown_loader import infer_physics_domain
from raggg.models import Document


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self.images: list[str] = []
        self._tag_stack: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style"}:
            self._skip_depth += 1
        if tag == "a" and attr_map.get("href"):
            self.links.append(attr_map["href"])
        if tag == "img":
            alt = attr_map.get("alt", "").strip()
            src = attr_map.get("src", "").strip()
            self.images.append(alt or src)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.text_parts.append("\n")
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self.title_parts.append(cleaned)
        self.text_parts.append(cleaned)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_html_document(path: Path, root: Path) -> Document:
    parser = _ReadableHtmlParser()
    content = path.read_text(encoding="utf-8", errors="ignore")
    parser.feed(content)
    title = " ".join(parser.title_parts).strip() or path.stem
    text = "\n".join(part.strip() for part in parser.text_parts if part.strip())
    return Document(
        source_type="waveda_help",
        source_path=path,
        relative_path=_relative(path, root),
        title=title,
        text=text,
        links=parser.links,
        images=[item for item in parser.images if item],
        metadata={
            "domain": "waveda",
            "content_type": "help_page",
            "priority": 3,
            "knowledge_layer": "official_help",
            "physics_domain": infer_physics_domain(_relative(path, root)),
            "has_formula": any(token in text for token in ("\\", "$$", "∇", "积分")),
            "has_wikilink": False,
        },
    )


def iter_html_documents(root: Path) -> list[Document]:
    if not root.exists():
        return []
    docs: list[Document] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}:
            docs.append(load_html_document(path, root))
    return docs
