from __future__ import annotations

import re


TEMPLATE_LINES = {
    "提示：所有绿色注释下面的区域是替换的部分",
    "下面是标题",
    "下面是类型、时间、参与编辑人数",
}


def clean_text(text: str) -> str:
    text = re.sub(r"\A---\s*\n.*?\n---\s*\n?", "", text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in TEMPLATE_LINES or stripped.startswith("<!--"):
            continue
        stripped = re.sub(r"[ \t\u3000]+", " ", stripped)
        cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines).strip()
