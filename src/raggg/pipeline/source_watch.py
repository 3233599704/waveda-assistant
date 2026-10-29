from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


WATCHED_SOURCE_SUFFIXES = {
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".txt",
    ".pdf",
    ".docx",
}


@dataclass(frozen=True)
class FileFingerprint:
    size: int
    modified_ns: int


SourceSnapshot = dict[str, FileFingerprint]


def scan_source_tree(root: Path | str) -> SourceSnapshot:
    root_path = Path(root)
    if not root_path.exists():
        return {}

    snapshot: SourceSnapshot = {}
    for path in sorted(root_path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in WATCHED_SOURCE_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path.relative_to(root_path).as_posix()] = FileFingerprint(
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )
    return snapshot


def snapshot_changed(previous: SourceSnapshot, current: SourceSnapshot) -> bool:
    return previous != current
