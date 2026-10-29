from __future__ import annotations

import os
import re
from pathlib import Path


IMAGE_PATH_RE = re.compile(
    r"[`\"]?((?:[A-Za-z0-9_. -]+[\\/])*(?:(?:images|res)[\\/])?"
    r"[A-Za-z0-9_. -]+\.(?:png|jpg|jpeg|gif|svg))[`\"]?",
    re.IGNORECASE,
)
IMAGE_PATH_PREFIXES = (
    "waveda_docs/helphtml/helphtml/",
    "waveda_docs/helphtml/",
    "knowledge_base/assets/images/",
    "assets/images/",
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg")


def normalize_image_key(value: str) -> str:
    key = value.strip().strip("`\"'<>|,;").replace("\\", "/")
    key = re.sub(r"^\./+", "", key).lstrip("/")
    lower = key.lower()
    for prefix in IMAGE_PATH_PREFIXES:
        if lower.startswith(prefix):
            key = key[len(prefix) :]
            lower = key.lower()
            break
    marker = "helphtml/helphtml/"
    marker_index = lower.find(marker)
    if marker_index >= 0:
        key = key[marker_index + len(marker) :]
    return key.lower()


class ImageIndex:
    def __init__(
        self,
        project_root: Path,
        *,
        waveda_help_root: Path | None = None,
        waveda_root: Path | None = None,
        waveda_example_root: Path | None = None,
    ) -> None:
        self.project_root = project_root
        self.waveda_help_root = waveda_help_root
        self.waveda_root = waveda_root
        self.waveda_example_root = waveda_example_root
        self.paths: dict[str, str] = {}

    def build(self) -> None:
        self.paths.clear()
        roots: list[tuple[Path, str]] = [
            (self.project_root / "knowledge_base" / "assets" / "images", ""),
            (self.project_root / "assets" / "images", ""),
            (self.project_root / "wavEDA_docs" / "helpHtml" / "helpHtml", ""),
        ]
        if self.waveda_help_root:
            roots.append((self.waveda_help_root, ""))
        if self.waveda_root:
            roots.extend(
                [
                    (self.waveda_root / "Example", "Example"),
                    (self.waveda_root / "documentation" / "helpHtml", ""),
                    (self.waveda_root / "helpHtml", ""),
                    (self.waveda_root / "helpHtml" / "helpHtml", ""),
                ]
            )
        if self.waveda_example_root:
            roots.append((self.waveda_example_root, "Example"))

        for root, prefix in roots:
            if root.exists():
                self.add_root(root, prefix)

    def add_root(self, root: Path, key_prefix: str = "") -> None:
        resolved_root = root.resolve()
        for image_path in resolved_root.rglob("*"):
            if (
                not image_path.is_file()
                or image_path.suffix.lower() not in IMAGE_EXTENSIONS
            ):
                continue
            absolute_path = str(image_path)
            relative_key = normalize_image_key(
                image_path.relative_to(resolved_root).as_posix()
            )
            self.paths.setdefault(relative_key, absolute_path)
            if key_prefix:
                prefixed = normalize_image_key(f"{key_prefix}/{relative_key}")
                self.paths.setdefault(prefixed, absolute_path)
            self.paths.setdefault(image_path.name.lower(), absolute_path)

    def extract_from_sources(
        self,
        sources: list,
        min_score: float = 0.45,
    ) -> list[tuple[str, str]]:
        return extract_images_from_sources(sources, self.paths, min_score)


def extract_images_from_sources(
    sources: list,
    image_index: dict[str, str],
    min_score: float = 0.45,
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for source in sources:
        if source.score < min_score:
            continue
        for match in IMAGE_PATH_RE.finditer(source.chunk.content):
            raw_reference = match.group(1)
            candidates = [
                normalize_image_key(raw_reference),
                os.path.basename(raw_reference).lower(),
            ]
            if candidates[0].startswith("example/"):
                candidates.append(candidates[0][len("example/") :])
            image_path = next(
                (image_index[key] for key in candidates if key in image_index),
                "",
            )
            if not image_path or image_path in seen:
                continue
            seen.add(image_path)
            results.append((image_path, source.chunk.title))
    return results
