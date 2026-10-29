from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


@dataclass(frozen=True)
class _CacheEntry:
    modified_ns: int
    file_size: int
    data_uri: str


class ImageDataUriCache:
    def __init__(self, max_entries: int = 128, max_bytes: int = 64 * 1024 * 1024) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._encoded_bytes = 0

    def get(self, filepath: str | Path) -> str:
        path = Path(filepath)
        key = str(path.resolve())
        try:
            stat = path.stat()
        except OSError:
            self._discard(key)
            return ""

        cached = self._entries.get(key)
        if cached and cached.modified_ns == stat.st_mtime_ns and cached.file_size == stat.st_size:
            self._entries.move_to_end(key)
            return cached.data_uri

        self._discard(key)
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        mime = MIME_TYPES.get(path.suffix.lower(), "image/png")
        data_uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        if len(data_uri) <= self.max_bytes:
            self._entries[key] = _CacheEntry(stat.st_mtime_ns, stat.st_size, data_uri)
            self._encoded_bytes += len(data_uri)
            self._evict()
        return data_uri

    def _discard(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry:
            self._encoded_bytes -= len(entry.data_uri)

    def _evict(self) -> None:
        while self._entries and (
            len(self._entries) > self.max_entries or self._encoded_bytes > self.max_bytes
        ):
            _, entry = self._entries.popitem(last=False)
            self._encoded_bytes -= len(entry.data_uri)
