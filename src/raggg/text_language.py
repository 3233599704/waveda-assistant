from __future__ import annotations

import re


HAN_RE = re.compile(
    "["
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uf900-\ufaff"
    "\U00020000-\U000323af"
    "]"
)


def contains_han(text: str) -> bool:
    return HAN_RE.search(text) is not None
