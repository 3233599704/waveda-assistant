from __future__ import annotations

import re
from pathlib import Path

from raggg.models import Document


WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
KNOWLEDGE_LAYER_METADATA = {
    "01_team_tutorials": (5, "team_tutorial"),
    "02_software_manual": (4, "software_manual"),
    "03_examples": (4, "worked_example"),
    "04_error_cases": (3, "error_reference"),
    "05_reference": (2, "reference"),
    "06_theory_notes": (1, "theory_note"),
}


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _title_from_markdown(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def knowledge_path_metadata(relative_path: str) -> dict[str, int | str]:
    top_level = relative_path.split("/", 1)[0]
    priority, knowledge_layer = KNOWLEDGE_LAYER_METADATA.get(top_level, (3, "uncategorized"))
    return {"priority": priority, "knowledge_layer": knowledge_layer}


def infer_physics_domain(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lower()
    if any(token in normalized for token in ("photonics", "光子", "光波导")):
        return "photonics"
    if any(token in normalized for token in ("multi-physics", "multiphysics", "多物理场")):
        return "multiphysics"
    if any(token in normalized for token in ("thermal", "热学", "热传导")):
        return "thermal"
    if any(token in normalized for token in ("acoustic", "声学", "弹性波", "压电")):
        return "acoustic_piezoelectric"
    if any(token in normalized for token in ("/mech/", "mechanical", "结构力学", "力学模块")):
        return "mechanical"
    if any(token in normalized for token in ("circuit", "电路")):
        return "circuit"
    if any(token in normalized for token in ("layout", "版图", "封装")):
        return "layout_packaging"
    if any(token in normalized for token in ("em_project", "/em/", "电磁", "射频")):
        return "em_rf"
    return "common"


def _frontmatter_values(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text.replace("\r\n", "\n").replace("\r", "\n"))
    if not match:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def _frontmatter_bool(values: dict[str, str], key: str, default: bool = True) -> bool:
    value = values.get(key)
    if value is None:
        return default
    return value.strip().lower() not in {"false", "no", "0", "off"}


def load_markdown_document(path: Path, root: Path) -> Document:
    text = path.read_text(encoding="utf-8", errors="ignore")
    links = WIKILINK_RE.findall(text)
    has_formula = any(token in text for token in ("$$", "\\nabla", "\\partial", "∇", "∮", "∫"))
    relative_path = _relative(path, root)
    frontmatter = _frontmatter_values(text)
    path_metadata = knowledge_path_metadata(relative_path)
    try:
        declared_priority = int(frontmatter.get("priority", ""))
    except ValueError:
        declared_priority = int(path_metadata["priority"])
    if 1 <= declared_priority <= 5:
        path_metadata["priority"] = declared_priority
    return Document(
        source_type="obsidian_note",
        source_path=path,
        relative_path=relative_path,
        title=_title_from_markdown(text, path.stem),
        text=text,
        links=links,
        images=re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text),
        metadata={
            "domain": "multiphysics",
            "content_type": frontmatter.get("content_kind", "note"),
            "indexing": _frontmatter_bool(frontmatter, "indexing"),
            "physics_domain": frontmatter.get(
                "physics_domain", infer_physics_domain(relative_path)
            ),
            "waveda_module": frontmatter.get("waveda_module", ""),
            "software_version": frontmatter.get("software_version", ""),
            "status": frontmatter.get("status", ""),
            "has_formula": has_formula,
            "has_wikilink": bool(links),
            **path_metadata,
        },
    )


def iter_markdown_documents(root: Path) -> list[Document]:
    if not root.exists():
        return []
    docs: list[Document] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        docs.append(load_markdown_document(path, root))
    return docs
