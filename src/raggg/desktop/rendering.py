from __future__ import annotations

import html
import os
import re

from raggg.config import application_root
from raggg.desktop.image_cache import ImageDataUriCache
from raggg.theme import get_colors


COLORS = get_colors()
IMAGE_MD_RE = re.compile(
    r">?\s*[^:\n]{0,16}:\s*`?\.?/([^`)]+\.(?:png|jpg|jpeg|gif|svg))`?",
    re.IGNORECASE,
)
INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ORDERED_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
UNORDERED_RE = re.compile(r"^\s*[-*]\s+(.+)$")
INLINE_MATH_RE = re.compile(r"\\\((.+?)\\\)")
DISPLAY_MATH_RE = re.compile(r"\\\[(.+?)\\\]|\$\$(.+?)\$\$", re.DOTALL)
FRAC_RE = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
CITATION_RE = re.compile(r"(?<![\w/])\[(\d+)\](?!\s*\()")

WEBVIEW_BG = "transparent"
WEBVIEW_TEXT = COLORS["text"]

_data_uri_cache = ImageDataUriCache()


def path_to_data_uri(filepath: str) -> str:
    return _data_uri_cache.get(filepath)


def latex_formula_to_html(formula: str) -> str:
    replacements = {
        r"\partial": "∂",
        r"\nabla": "∇",
        r"\cdot": "·",
        r"\times": "×",
        r"\oiint": "∯",
        r"\iiint": "∭",
        r"\iint": "∬",
        r"\oint": "∮",
        r"\int": "∫",
        r"\rho": "ρ",
        r"\mu": "μ",
        r"\epsilon": "ε",
        r"\omega": "ω",
        r"\alpha": "α",
        r"\beta": "β",
        r"\theta": "θ",
        r"\phi": "φ",
        r"\mathbf": "",
        r"\mathrm": "",
        r"\left": "",
        r"\right": "",
        r"\,": " ",
    }

    converted = formula
    while True:
        updated = FRAC_RE.sub(r"(\1)/(\2)", converted)
        if updated == converted:
            break
        converted = updated
    for source, target in replacements.items():
        converted = converted.replace(source, target)
    converted = re.sub(r"\{([^{}]+)\}", r"\1", converted)
    converted = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", converted)
    converted = re.sub(r"_([A-Za-z0-9])", r"<sub>\1</sub>", converted)
    converted = converted.replace("\\", "").replace(",", " ")
    converted = re.sub(r"\s+", " ", converted).strip()
    converted = re.sub(r"∂\s+([A-Za-z一-龥])", r"∂\1", converted)
    converted = re.sub(r"∇\s+", "∇", converted)
    converted = converted.replace("· ", " · ")
    converted = re.sub(r"\s+", " ", converted).strip()
    return (
        html.escape(converted, quote=False)
        .replace("&lt;sub&gt;", "<sub>")
        .replace("&lt;/sub&gt;", "</sub>")
    )


def latex_to_readable(text: str) -> str:
    def formula_span(rendered: str) -> str:
        style = (
            "background:#0b1e2e;"
            f"border:1px solid {COLORS['border']};"
            "border-radius:6px;"
            "padding:2px 6px;"
            "font-family:'Cambria Math','Times New Roman','Consolas';"
            "font-size:14px;"
            f"color:{COLORS['text']};"
            "white-space:nowrap;"
        )
        return f'<span style="{style}">{rendered}</span>'

    def inline_repl(match: re.Match[str]) -> str:
        return formula_span(latex_formula_to_html(match.group(1)))

    def display_repl(match: re.Match[str]) -> str:
        return formula_span(latex_formula_to_html(match.group(1) or match.group(2) or ""))

    text = DISPLAY_MATH_RE.sub(display_repl, text)
    return INLINE_MATH_RE.sub(inline_repl, text)


def render_citations(text: str, *, clickable: bool = True) -> str:
    def replace(match: re.Match[str]) -> str:
        rank = match.group(1)
        if not clickable:
            return f'<sup class="citation">[{rank}]</sup>'
        return (
            '<sup class="citation"><a href="#" '
            f"onclick=\"console.log('RAGGG_CITATION:{rank}');return false;\">"
            f"[{rank}]</a></sup>"
        )

    return CITATION_RE.sub(replace, text)


def render_inline_markdown(
    text: str,
    *,
    citations_clickable: bool = True,
) -> str:
    escaped = html.escape(latex_to_readable(text), quote=False)
    escaped = re.sub(r'&lt;span style="(.+?)"&gt;', r'<span style="\1">', escaped)
    escaped = re.sub(r"&lt;span style=&quot;(.+?)&quot;&gt;", r'<span style="\1">', escaped)
    escaped = escaped.replace("&lt;/span&gt;", "</span>")
    escaped = escaped.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    escaped = render_citations(escaped, clickable=citations_clickable)
    return INLINE_BOLD_RE.sub(r"<strong>\1</strong>", escaped)


def markdown_to_html(
    text: str,
    *,
    citations_clickable: bool = True,
) -> str:
    lines = text.strip().splitlines()
    output: list[str] = []
    list_mode: str | None = None
    list_prefix = ""
    last_ordered_number = 0

    def close_list() -> None:
        nonlocal list_mode, list_prefix
        if list_mode:
            output.append(f"</{list_mode}>")
        list_mode = None
        list_prefix = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            list_prefix += "<div style='height:4px;'></div>"
            continue

        ordered = ORDERED_RE.match(line)
        unordered = UNORDERED_RE.match(line)
        if ordered:
            ordered_number = int(ordered.group(1))
            if list_mode != "ol":
                close_list()
                start = (
                    f' start="{last_ordered_number + 1}"'
                    if last_ordered_number > 0
                    else ""
                )
                output.append(f"{list_prefix}<ol{start}>")
                list_prefix = ""
                list_mode = "ol"
            last_ordered_number = ordered_number
            output.append(
                f"<li>{render_inline_markdown(ordered.group(2), citations_clickable=citations_clickable)}</li>"
            )
            continue
        if unordered:
            if list_mode == "ol":
                if output and output[-1].endswith("</li>"):
                    output[-1] = (
                        output[-1][:-5]
                        + "<br>"
                        + render_inline_markdown(
                            unordered.group(1),
                            citations_clickable=citations_clickable,
                        )
                        + "</li>"
                    )
                continue
            if list_mode != "ul":
                close_list()
                last_ordered_number = 0
                output.append(list_prefix + "<ul>")
                list_prefix = ""
                list_mode = "ul"
            output.append(
                f"<li>{render_inline_markdown(unordered.group(1), citations_clickable=citations_clickable)}</li>"
            )
            continue

        close_list()
        if list_prefix:
            output.append(list_prefix)
            list_prefix = ""
        if line.startswith(">"):
            output.append(
                f"<blockquote>{render_inline_markdown(line.lstrip('> ').strip(), citations_clickable=citations_clickable)}</blockquote>"
            )
        elif line.startswith("#"):
            last_ordered_number = 0
            heading = line.lstrip("#").strip()
            output.append(
                f"<div style='margin:12px 0 6px 0;color:{COLORS['accent']};"
                f"font-weight:700;'>{render_inline_markdown(heading, citations_clickable=citations_clickable)}</div>"
            )
        else:
            output.append(
                f"<p style='margin:7px 0;line-height:1.58;'>"
                f"{render_inline_markdown(line, citations_clickable=citations_clickable)}</p>"
            )

    close_list()
    if list_prefix:
        output.append(list_prefix)
    result = "\n".join(output)
    result = re.sub(
        r'</ol>(<div[^>]*></div>)<ol start="\d+">',
        r"\1",
        result,
    )
    return convert_image_refs(result)


def convert_image_refs(html_text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        image_relative = match.group(1)
        help_base = application_root() / "wavEDA_docs" / "helpHtml" / "helpHtml"
        for root, directories, _files in os.walk(help_base):
            if "images" not in directories:
                continue
            candidate = os.path.join(root, image_relative.replace("/", os.sep))
            if not os.path.exists(candidate):
                continue
            data_uri = path_to_data_uri(candidate)
            if not data_uri:
                return match.group(0)
            return (
                f'<p style="margin:8px 0;"><img src="{data_uri}" '
                f'style="max-width:100%;border-radius:8px;'
                f'border:1px solid {COLORS["border"]};" alt="Diagram"></p>'
            )
        return match.group(0)

    return IMAGE_MD_RE.sub(replace, html_text)


def web_wrapper(body_html: str, extra_css: str = "") -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
body {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 14px;
    background: {WEBVIEW_BG};
    color: {WEBVIEW_TEXT};
    margin: 0;
    padding: 0;
    overflow-x: hidden;
}}
p {{ margin: 7px 0; line-height: 1.58; }}
ol {{ margin: 8px 0; padding-left: 24px; }}
ol li {{ margin: 4px 0; }}
ul {{ margin: 8px 0; padding-left: 24px; }}
ul li {{ margin: 4px 0; }}
strong {{ color: {COLORS["accent"]}; }}
blockquote {{ margin: 8px 0; padding: 8px 12px; border-left: 3px solid {COLORS["accent"]}; color: {COLORS["muted"]}; }}
a {{ color: {COLORS["accent2"]}; }}
.answer-actions {{ opacity: 0.3; transition: opacity 0.18s; margin-top: 8px; }}
.answer-block:hover .answer-actions {{ opacity: 1; }}
.citation {{ margin-left:2px; font-size:.78em; vertical-align:super; }}
.citation a {{ text-decoration:none; font-weight:700; cursor:pointer; }}
{extra_css}
</style></head><body>{body_html}</body></html>"""
