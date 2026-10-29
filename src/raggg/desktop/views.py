from __future__ import annotations

import html
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QRectF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient, QShortcut
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from raggg.config import Settings, application_root, config_env_path, load_settings
from raggg.desktop.image_cache import ImageDataUriCache
from raggg.desktop.session_manager import MAX_HISTORY_TURNS, SessionManager
from raggg.i18n import get_text, get_language, set_language, get_welcome_text
from raggg.pipeline.builder import BuildProgress, BuildReport, build_knowledge_base
from raggg.pipeline.ingestion import IngestReport, ingest_document
from raggg.pipeline.knowledge_import import mark_imports_indexed
from raggg.pipeline.rag_pipeline import RAGAnswer, RAGPipeline
from raggg.pipeline.source_watch import SourceSnapshot, scan_source_tree, snapshot_changed
from raggg.retrieval.retriever import SearchResult
from raggg.theme import get_theme, set_theme, get_colors, get_chat_bubble_colors, THEMES
from raggg.text_language import contains_han

# ── 动态主题 ──
COLORS = get_colors()


from raggg.desktop.workers import AskResult, CancellationToken, WorkerSignals, Worker



IMAGE_MD_RE = re.compile(r">?\s*[^:\n]{0,16}:\s*`?\.?/([^`)]+\.(?:png|jpg|jpeg|gif|svg))`?", re.IGNORECASE)
INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ORDERED_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
UNORDERED_RE = re.compile(r"^\s*[-*]\s+(.+)$")
INLINE_MATH_RE = re.compile(r"\\\((.+?)\\\)")
DISPLAY_MATH_RE = re.compile(r"\\\[(.+?)\\\]|\$\$(.+?)\$\$", re.DOTALL)
FRAC_RE = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")


def normalize_favorite_search_text(text: object) -> str:
    return "".join(str(text).casefold().split())


def favorite_matches(favorite: dict, query: str) -> bool:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return True
    searchable_text = str(favorite.get("question", "")).casefold()
    searchable_compact = normalize_favorite_search_text(searchable_text)
    keywords = normalized_query.split()
    query_compact = normalize_favorite_search_text(query)
    return (
        all(kw in searchable_text for kw in keywords)
        or query_compact in searchable_compact
    )


def favorite_score(favorite: dict, query: str) -> int:
    """多关键词命中次数，用于排序"""
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return 0
    keywords = normalized_query.split()
    searchable_text = str(favorite.get("question", "")).casefold()
    score = sum(searchable_text.count(kw) for kw in keywords)
    query_compact = normalize_favorite_search_text(query)
    searchable_compact = normalize_favorite_search_text(searchable_text)
    if query_compact:
        score += searchable_compact.count(query_compact) * 2
    return score


def highlight_keywords(html_text: str, query: str) -> str:
    """在 HTML 文本中高亮关键词"""
    if not query.strip():
        return html_text
    result = html_text
    for kw in query.strip().split():
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        result = pattern.sub(
            f'<mark style="background:#5f93d6;color:#fff;padding:1px 3px;border-radius:3px;">{kw}</mark>',
            result,
        )
    return result


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
    for src, dst in replacements.items():
        converted = converted.replace(src, dst)
    converted = re.sub(r"\{([^{}]+)\}", r"\1", converted)
    converted = re.sub(r"_\{([^{}]+)\}", r"<sub>\1</sub>", converted)
    converted = re.sub(r"_([A-Za-z0-9])", r"<sub>\1</sub>", converted)
    converted = converted.replace("\\", "")
    converted = converted.replace(",", " ")
    converted = re.sub(r"\s+", " ", converted).strip()
    converted = re.sub(r"∂\s+([A-Za-z一-鿿])", r"∂\1", converted)
    converted = re.sub(r"∇\s+", "∇", converted)
    converted = converted.replace("· ", " · ")
    converted = re.sub(r"\s+", " ", converted).strip()
    return html.escape(converted, quote=False).replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")


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
        return f"<span style=\"{style}\">{rendered}</span>"

    def inline_repl(match: re.Match[str]) -> str:
        return formula_span(latex_formula_to_html(match.group(1)))

    def display_repl(match: re.Match[str]) -> str:
        return formula_span(latex_formula_to_html(match.group(1) or match.group(2) or ""))

    text = DISPLAY_MATH_RE.sub(display_repl, text)
    return INLINE_MATH_RE.sub(inline_repl, text)


def render_inline_markdown(text: str) -> str:
    escaped = html.escape(latex_to_readable(text), quote=False)
    escaped = re.sub(r"&lt;span style=\"(.+?)\"&gt;", r'<span style="\1">', escaped)
    escaped = re.sub(r"&lt;span style=&quot;(.+?)&quot;&gt;", r'<span style="\1">', escaped)
    escaped = escaped.replace("&lt;/span&gt;", "</span>")
    escaped = escaped.replace("&lt;sub&gt;", "<sub>").replace("&lt;/sub&gt;", "</sub>")
    return INLINE_BOLD_RE.sub(r"<strong>\1</strong>", escaped)


def _action_buttons_html(bubbles: dict, *, include_correction: bool = True) -> str:
    """复制 / 收藏 / 纠错 按钮 HTML，hover 时通过 CSS 淡入"""
    buttons = (
        f"<button onclick=\"var p=this.parentElement.previousElementSibling;"
        f"var t=document.createElement('textarea');t.value=p.innerText;"
        f"document.body.appendChild(t);t.select();document.execCommand('copy');"
        f"document.body.removeChild(t);var s=this.innerHTML;"
        f"this.innerHTML='{get_text('btn_copied')}';"
        f"setTimeout(function(){{this.innerHTML=s;}}.bind(this),1000)\""
        f" style='background:transparent;color:{bubbles['muted']};"
        f"border:1px solid {bubbles['border']};border-radius:8px;"
        f"padding:2px 9px;font-size:11px;cursor:pointer;'"
        f" onmouseover=\"this.style.color='{bubbles['accent']}';"
        f"this.style.borderColor='{bubbles['accent']}'\""
        f" onmouseout=\"this.style.color='{bubbles['muted']}';"
        f"this.style.borderColor='{bubbles['border']}'\">"
        f"{get_text('btn_copy')}</button>"
        f"<button onclick=\"console.log('RAGGG_FAV');"
        f"this.innerHTML='{get_text('btn_faved')}';"
        f"this.style.color='{bubbles['accent']}';"
        f"setTimeout(function(){{this.innerHTML='{get_text('btn_fav')}';"
        f"this.style.color='{bubbles['muted']}'}}.bind(this),1500)\""
        f" style='background:transparent;color:{bubbles['muted']};"
        f"border:1px solid {bubbles['border']};border-radius:8px;"
        f"padding:2px 9px;font-size:11px;cursor:pointer;'"
        f" onmouseover=\"this.style.color='{bubbles['accent']}';"
        f"this.style.borderColor='{bubbles['accent']}'\""
        f" onmouseout=\"this.style.color='{bubbles['muted']}';"
        f"this.style.borderColor='{bubbles['border']}'\">"
        f"{get_text('btn_fav')}</button>"
    )
    if not include_correction:
        return buttons
    return buttons + (
        f"<button onclick=\"console.log('RAGGG_FIX')\""
        f" style='background:transparent;color:{bubbles['muted']};"
        f"border:1px solid {bubbles['border']};border-radius:8px;"
        f"padding:2px 9px;font-size:11px;cursor:pointer;'"
        f" onmouseover=\"this.style.color='{bubbles['accent']}';"
        f"this.style.borderColor='{bubbles['accent']}'\""
        f" onmouseout=\"this.style.color='{bubbles['muted']}';"
        f"this.style.borderColor='{bubbles['border']}'\">"
        f"{get_text('btn_fix')}</button>"
    )


def markdown_to_html(text: str) -> str:
    lines = text.strip().splitlines()
    output: list[str] = []
    list_mode: str | None = None
    list_prefix: str = ""  # 缓存列表项间空白

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
            if list_mode != "ol":
                close_list()
                output.append(list_prefix + "<ol>")
                list_prefix = ""
                list_mode = "ol"
            output.append(f"<li>{render_inline_markdown(ordered.group(2))}</li>")
            continue
        if unordered:
            if list_mode == "ol":
                # 有序列表内不嵌套无序列表，当作文本追加到上一个<li>
                if output:
                    last = output[-1]
                    if last.endswith("</li>"):
                        output[-1] = last[:-5] + "<br>" + render_inline_markdown(unordered.group(1)) + "</li>"
                continue
            if list_mode != "ul":
                close_list()
                output.append(list_prefix + "<ul>")
                list_prefix = ""
                list_mode = "ul"
            output.append(f"<li>{render_inline_markdown(unordered.group(1))}</li>")
            continue

        close_list()
        if list_prefix:
            output.append(list_prefix)
            list_prefix = ""
        if line.startswith(">"):
            output.append(
                f"<blockquote style='margin:8px 0;padding:8px 12px;border-left:3px solid {COLORS['accent']};color:{COLORS['muted']};'>"
                f"{render_inline_markdown(line.lstrip('> ').strip())}</blockquote>"
            )
        elif line.startswith("#"):
            heading = line.lstrip("#").strip()
            output.append(
                f"<div style='margin:12px 0 6px 0;color:{COLORS['accent']};font-weight:700;'>"
                f"{render_inline_markdown(heading)}</div>"
            )
        else:
            output.append(f"<p style='margin:7px 0;line-height:1.58;'>{render_inline_markdown(line)}</p>")

    close_list()
    if list_prefix:
        output.append(list_prefix)
    result = "\n".join(output)
    # Merge broken ordered lists: </ol>...<ol> -> nothing
    result = re.sub(r"</ol>(<div[^>]*></div>)<ol>", r"\1", result)
    # Convert image markdown to actual <img> tags pointing to helpHtml
    result = _convert_image_refs(result)
    return result


IMAGE_PATH_RE = re.compile(
    r"[`\"]?((?:[A-Za-z0-9_. -]+[\\/])*(?:(?:images|res)[\\/])?[A-Za-z0-9_. -]+\.(?:png|jpg|jpeg|gif|svg))[`\"]?",
    re.IGNORECASE,
)
IMAGE_PATH_PREFIXES = (
    "waveda_docs/helphtml/helphtml/",
    "waveda_docs/helphtml/",
    "knowledge_base/assets/images/",
    "assets/images/",
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg")

_data_uri_cache = ImageDataUriCache()


def _path_to_data_uri(filepath: str) -> str:
    """将本地图片文件转为带容量限制的缓存 data URI。"""
    return _data_uri_cache.get(filepath)



def _normalize_image_key(value: str) -> str:
    key = value.strip().strip("`\"'<>|,;").replace("\\", "/")
    key = re.sub(r"^\./+", "", key)
    key = key.lstrip("/")
    lower = key.lower()
    for prefix in IMAGE_PATH_PREFIXES:
        if lower.startswith(prefix):
            key = key[len(prefix):]
            lower = key.lower()
            break
    marker = "helphtml/helphtml/"
    marker_index = lower.find(marker)
    if marker_index >= 0:
        key = key[marker_index + len(marker):]
    return key.lower()


def _extract_images_from_sources(sources: list, image_index: dict[str, str],
                                  min_score: float = 0.45) -> list[tuple[str, str]]:
    """从检索到的来源chunk中提取图片路径, 过滤低分来源, 返回 [(绝对路径, 标题), ...]"""
    seen = set()
    results = []
    for src in sources:
        if src.score < min_score:
            continue
        content = src.chunk.content
        title = src.chunk.title
        for match in IMAGE_PATH_RE.finditer(content):
            raw_ref = match.group(1)
            candidates = [
                _normalize_image_key(raw_ref),
                os.path.basename(raw_ref).lower(),
            ]
            normalized = candidates[0]
            if normalized.startswith("example/"):
                candidates.append(normalized[len("example/"):])
            img_path = next((image_index[key] for key in candidates if key in image_index), "")
            if not img_path or img_path in seen:
                continue
            seen.add(img_path)
            results.append((img_path, title))
    return results


def _convert_image_refs(html_text: str) -> str:
    """把 图片: `./images/xxx.png` 换成实际可显示的 <img> 标签"""
    def _img_repl(match: re.Match[str]) -> str:
        img_rel = match.group(1)  # images/xxx.png
        # Find actual image in helpHtml
        project_root = application_root()
        help_base = project_root / "wavEDA_docs" / "helpHtml" / "helpHtml"
        # Search recursively for the image
        for root, dirs, files in os.walk(help_base):
            if "images" in dirs:
                candidate = os.path.join(root, img_rel.replace("/", os.sep))
                if os.path.exists(candidate):
                    data_uri = _path_to_data_uri(candidate)
                    if data_uri:
                        return f'<p style="margin:8px 0;"><img src="{data_uri}" style="max-width:100%;border-radius:8px;border:1px solid {COLORS["border"]};" alt="Diagram"></p>'
                    return match.group(0)
        return match.group(0)  # fallback: leave as text
    return IMAGE_MD_RE.sub(_img_repl, html_text)


WEBVIEW_BG = "transparent"
WEBVIEW_TEXT = COLORS["text"]


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
ol {{ margin: 8px 0; padding-left: 24px; list-style: none; }}
ol li {{ margin: 4px 0; counter-increment: ordered-item; }}
ol li::before {{ content: counter(ordered-item) ". "; color: {COLORS["accent"]}; font-weight: 600; }}
ul {{ margin: 8px 0; padding-left: 24px; }}
ul li {{ margin: 4px 0; }}
ul {{ margin: 8px 0; padding-left: 24px; }}
ul li {{ margin: 4px 0; }}
strong {{ color: {COLORS["accent"]}; }}
blockquote {{ margin: 8px 0; padding: 8px 12px; border-left: 3px solid {COLORS["accent"]}; color: {COLORS["muted"]}; }}
a {{ color: {COLORS["accent2"]}; }}
{extra_css}
</style></head><body>{body_html}</body></html>"""

from raggg.desktop.image_index import (
    ImageIndex,
    extract_images_from_sources as _extract_images_from_sources,
)
from raggg.desktop.favorites import (
    favorite_matches,
    favorite_score,
    highlight_keywords,
    normalize_favorite_search_text,
)
from raggg.desktop.rendering import (
    markdown_to_html,
    path_to_data_uri as _path_to_data_uri,
    render_inline_markdown,
    web_wrapper,
)
from raggg.desktop.sessions import SessionPanel
from raggg.desktop.widgets import MetricCard, AILoaderOverlay

from raggg.desktop.settings_dialog import LLM_PROVIDERS, VISION_MODELS, SettingsDialog
from raggg.desktop.script_generator_dialog import ScriptGeneratorDialog

from raggg.desktop.source_viewer import SourceViewer

class WorkbenchViewsMixin(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.pipeline: RAGPipeline | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers: list[Worker] = []
        self.is_busy = False
        self._last_qa: tuple[str, str] = ("", "")  # (question, answer)
        self._turn_qa_pairs: dict[int, tuple[str, str]] = {}
        self._conversation_history: list[tuple[str, str]] = []
        self._session_manager = SessionManager(settings.data_dir)
        self._temp_attachments: list[tuple[Path, str]] = []
        self._stream_message_counter = 0
        self._generation_token: CancellationToken | None = None
        self._chat_turn_counter = 0
        self._active_turn_dom_id = ""
        self._selected_turn_indices: set[int] = set()
        self._fav_file = settings.data_dir / "favorites.json"
        self._project_root = settings.project_root
        self._source_snapshot: SourceSnapshot = {}
        self._source_paths: dict[int, str] = {}
        self._watch_pending_snapshot: SourceSnapshot | None = None
        self._watch_rebuild_requested = False
        self.setWindowTitle("WavEDA Knowledge Workbench")
        icon_path = self._project_root / "wavEDA_docs" / "helpHtml" / "image" / "waveda.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1360, 840)
        self.setMinimumSize(1120, 720)
        self._image_index: dict[str, str] = {}  # filename -> absolute_path
        self._build_image_index()
        self._build_ui()
        self._setup_shortcuts()
        self._show_loader("正在载入", full_window=True)
        self._load_pipeline_if_ready()
        self._new_session()
        QTimer.singleShot(700, self._hide_loader)
        if self.settings.can_manage_knowledge:
            self._start_source_watcher()
        # 图片按需编码，避免启动时把整个帮助目录载入内存。
        self._preload_images()

    def _preload_images(self) -> None:
        """Compatibility hook: image data is now encoded lazily by the bounded cache."""

    def _build_image_index(self) -> None:
        """Build image index with project assets first, then user WavEDA paths."""
        self.image_index = ImageIndex(
            self._project_root,
            waveda_help_root=self.settings.waveda_help_root,
            waveda_root=self.settings.waveda_root,
            waveda_example_root=self.settings.waveda_example_root,
        )
        self.image_index.build()
        self._image_index = self.image_index.paths
        print(
            f"Image index: {len(set(self._image_index.values()))} files, "
            f"{len(self._image_index)} keys loaded"
        )

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("gradientRoot")
        self.setCentralWidget(root)

        shell = QGridLayout(root)
        shell.setContentsMargins(14, 14, 14, 12)
        shell.setHorizontalSpacing(12)
        shell.setVerticalSpacing(0)
        shell.setColumnStretch(0, 0)
        shell.setColumnStretch(1, 1)
        shell.setColumnStretch(2, 0)
        shell.setRowStretch(0, 1)

        self.main_workspace = QWidget(root)
        main = QVBoxLayout(self.main_workspace)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch(1)
        self.session_toggle_btn = QPushButton("☰")
        self.session_toggle_btn.setObjectName("iconButton")
        self.session_toggle_btn.setToolTip(get_text("session_toggle"))
        self.session_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.session_toggle_btn.clicked.connect(self._toggle_session_panel)
        top_bar.addWidget(self.session_toggle_btn)
        self.sidebar_toggle_button = QPushButton("◧")
        self.sidebar_toggle_button.setObjectName("iconButton")
        self.sidebar_toggle_button.setToolTip(f"{get_text('sidebar_toggle_tooltip')} (Ctrl+B)")
        self.sidebar_toggle_button.setCursor(Qt.PointingHandCursor)
        self.sidebar_toggle_button.clicked.connect(self._toggle_sidebar)
        top_bar.addWidget(self.sidebar_toggle_button)
        main.addLayout(top_bar)

        self.chat = QWebEngineView()
        self.chat.setObjectName("chatCanvas")
        self.chat.setStyleSheet("background: transparent; border: 0;")
        self.chat.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.chat.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)

        wb_ref = self

        class _FavPage(QWebEnginePage):
            def javaScriptConsoleMessage(self2, level, msg, line, source):
                wb_ref._on_console_msg(level, msg, line, source)

        self.chat.setPage(_FavPage(self.chat))
        self.chat.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.chat.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat.customContextMenuRequested.connect(self._show_chat_context_menu)
        chunks_path = self.settings.data_dir / "index" / "chunks.json"
        chunk_count = "-"
        if chunks_path.exists():
            try:
                chunk_count = str(len(json.loads(chunks_path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                pass
        model_name = self.settings.llm_model if self.settings.llm_api_key else get_text("model_local")
        self.chat.setHtml(self._welcome_html(chunk_count=chunk_count, model_name=model_name))
        main.addWidget(self.chat, stretch=1)

        bottom = QVBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(6)

        pill_row = QHBoxLayout()
        pill_row.addStretch(1)
        self.activity_label = QLabel(get_text("status_ready"))
        self.activity_label.setObjectName("miniPill")
        self.activity_label.hide()
        pill_row.addWidget(self.activity_label)
        pill_row.addStretch(1)
        bottom.addLayout(pill_row)

        # ── 临时附件卡片 ──
        self.attachment_scroll = QScrollArea()
        self.attachment_scroll.setObjectName("attachmentScroll")
        self.attachment_scroll.setWidgetResizable(False)
        self.attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_scroll.setFrameShape(QFrame.NoFrame)
        self.attachment_scroll.setFixedHeight(84)
        self.attachment_scroll.setMaximumWidth(680)
        self.attachment_scroll.hide()

        self.attachment_cards_widget = QWidget()
        self.attachment_cards_layout = QHBoxLayout(self.attachment_cards_widget)
        self.attachment_cards_layout.setContentsMargins(2, 4, 2, 4)
        self.attachment_cards_layout.setSpacing(8)
        self.attachment_scroll.setWidget(self.attachment_cards_widget)

        attach_row = QHBoxLayout()
        attach_row.setContentsMargins(0, 0, 0, 0)
        attach_row.addStretch(1)
        attach_row.addWidget(self.attachment_scroll)
        attach_row.addStretch(1)

        composer_frame = QFrame()
        composer_frame.setObjectName("composer")
        composer_frame.setMinimumWidth(480)
        composer_frame.setMaximumWidth(680)
        composer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        composer_layout = QHBoxLayout(composer_frame)
        composer_layout.setContentsMargins(9, 5, 5, 5)
        composer_layout.setSpacing(6)

        self.import_button = QPushButton("+")
        self.import_button.setObjectName("plusButton")
        self.import_button.setToolTip(get_text("upload_tooltip"))
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.clicked.connect(self._import_document)

        self.question = QLineEdit()
        self.question.setPlaceholderText(get_text("placeholder_input"))
        self.question.setToolTip("Ctrl+L")
        self.question.setContextMenuPolicy(Qt.CustomContextMenu)
        self.question.customContextMenuRequested.connect(
            self._show_question_context_menu
        )
        self.question.returnPressed.connect(self._ask)

        self.ask_button = QPushButton("↑")
        self.ask_button.setObjectName("sendButton")
        self.ask_button.setToolTip(get_text("btn_ask"))
        self.ask_button.setCursor(Qt.PointingHandCursor)
        self.ask_button.clicked.connect(self._on_ask_button_clicked)

        composer_layout.addWidget(self.import_button)
        composer_layout.addWidget(self.question, stretch=1)
        composer_layout.addWidget(self.ask_button)

        composer_row = QHBoxLayout()
        composer_row.addStretch(1)
        composer_row.addWidget(composer_frame)
        composer_row.addStretch(1)
        bottom.addLayout(attach_row)
        bottom.addLayout(composer_row)
        main.addLayout(bottom)

        self.sidebar_container = self._sidebar_panel()
        self.sidebar_container.hide()

        self.session_panel = self._build_session_panel()
        shell.addWidget(self.session_panel, 0, 0)
        shell.addWidget(self.main_workspace, 0, 1)
        shell.addWidget(self.sidebar_container, 0, 2)
        self.loader_overlay = AILoaderOverlay(root, text="正在载入")
        self._loader_full_window = True
        self.loader_overlay.setGeometry(root.rect())
        self.loader_overlay.raise_()
        root.installEventFilter(self)
        self.main_workspace.installEventFilter(self)

    def _header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        titles = QVBoxLayout()
        title_row = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(QPixmap(str(self._project_root / "wavEDA_docs" / "helpHtml" / "image" / "waveda.png"))
                             .scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon_label.setFixedSize(42, 42)
        title_row.addWidget(icon_label)
        title = QLabel("WavEDA Knowledge Workbench")
        title.setObjectName("title")
        title_row.addWidget(title, stretch=1)
        titles.addLayout(title_row)
        subtitle = QLabel(get_text("app_subtitle"))
        subtitle.setObjectName("subtitle")
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        badge = QLabel(get_text("badge_waveda_first"))
        badge.setObjectName("badge")
        header.addWidget(badge, alignment=Qt.AlignRight | Qt.AlignVCenter)
        return header

    def _left_panel(self) -> QFrame:
        panel = self._panel(270)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        section = QLabel(get_text("sidebar_status"))
        section.setObjectName("section")
        layout.addWidget(section)

        self.status_card = MetricCard(get_text("card_knowledge_base"), get_text("status_loading_index"))
        self.chunk_card = MetricCard(get_text("card_chunks"), "-", COLORS["warning"])
        self.model_card = MetricCard(get_text("card_model"), self.settings.llm_model if self.settings.llm_api_key else get_text("model_local"))
        layout.addWidget(self.status_card)
        layout.addWidget(self.chunk_card)
        layout.addWidget(self.model_card)
        self.watch_card = MetricCard(get_text("watch_label"), get_text("watch_starting"), COLORS["accent2"])
        if self.settings.can_manage_knowledge:
            layout.addWidget(self.watch_card)

        self.import_button = self._button(get_text("import_button"), primary=True)
        self.import_button.clicked.connect(self._import_document)
        layout.addWidget(self.import_button)

        self.script_gen_button = self._button(get_text("btn_script_gen"), primary=True)
        self.script_gen_button.clicked.connect(self._open_script_generator)
        layout.addWidget(self.script_gen_button)

        self.api_button = self._button(get_text("btn_api_settings"))
        self.api_button.clicked.connect(self._open_api_settings)
        layout.addWidget(self.api_button)

        self.fav_button = self._button(get_text("btn_favorites"))
        self.fav_button.clicked.connect(self._open_favorites)
        layout.addWidget(self.fav_button)

        prompt_label = QLabel(get_text("quick_questions_label"))
        prompt_label.setObjectName("section")
        layout.addSpacing(10)
        layout.addWidget(prompt_label)
        for key in ("quick_q1", "quick_q2", "quick_q3"):
            prompt = get_text(key)
            button = self._button(prompt)
            button.clicked.connect(lambda _checked=False, text=prompt: self._ask(text))
            layout.addWidget(button)

        note = QLabel(get_text("search_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(note)
        return panel

    def _chat_panel(self) -> QFrame:
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        section = QLabel(get_text("section_qa"))
        section.setObjectName("section")
        self.activity_label = QLabel(get_text("status_ready"))
        self.activity_label.setStyleSheet(f"color: {COLORS['accent']};")
        top.addWidget(section)
        top.addStretch(1)
        top.addWidget(self.activity_label)
        layout.addLayout(top)

        self.chat = QWebEngineView()
        self.chat.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.chat.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)

        # 自定义页面：拦截 console.log 消息
        wb_ref = self
        class _FavPage(QWebEnginePage):
            def javaScriptConsoleMessage(self2, level, msg, line, source):
                wb_ref._on_console_msg(level, msg, line, source)
        self.chat.setPage(_FavPage(self.chat))
        self.chat.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat.customContextMenuRequested.connect(self._show_chat_context_menu)

        # 读取实际的 chunk 数量和模型名
        chunks_path = self.settings.data_dir / "index" / "chunks.json"
        chunk_count_str = "-"
        if chunks_path.exists():
            try:
                import json
                data = json.loads(chunks_path.read_text(encoding="utf-8"))
                chunk_count_str = str(len(data))
            except Exception:
                pass
        model_name_str = self.settings.llm_model if self.settings.llm_api_key else get_text("model_local")
        self.chat.setHtml(self._welcome_html(chunk_count=chunk_count_str, model_name=model_name_str))
        self.chat.setMinimumHeight(300)
        layout.addWidget(self.chat, stretch=1)

        composer = QHBoxLayout()
        composer.setSpacing(10)
        self.question = QLineEdit()
        self.question.setPlaceholderText(get_text("placeholder_input"))
        self.question.returnPressed.connect(self._ask)
        self.ask_button = self._button(get_text("btn_ask"), primary=True)
        self.ask_button.clicked.connect(self._on_ask_button_clicked)
        composer.addWidget(self.question, stretch=1)
        composer.addWidget(self.ask_button)
        layout.addLayout(composer)
        return panel

    def _source_panel(self) -> QFrame:
        panel = self._panel(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel(get_text("section_sources"))
        title.setObjectName("section")
        subtitle = QLabel(get_text("sources_subtitle"))
        subtitle.setObjectName("muted")
        self._source_list_html = self._empty_sources_html()
        self.sources = QWebEngineView()
        self.sources.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.sources.page().urlChanged.connect(self._on_src_url)
        self.sources.setHtml(self._source_list_html)
        src_nav = QHBoxLayout()
        src_nav.setSpacing(6)
        back_btn = QPushButton(get_text("btn_back_to_sources"))
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.sources.setHtml(self._source_list_html))
        src_nav.addWidget(back_btn)
        src_nav.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(src_nav)
        layout.addWidget(self.sources, stretch=1)
        return panel

    def _sidebar_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setFixedWidth(388)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel(get_text("section_data_status"))
        title.setObjectName("section")
        close_button = QPushButton("◧")
        close_button.setObjectName("iconButton")
        close_button.setToolTip(get_text("sidebar_hide_tooltip"))
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self._toggle_sidebar)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_button)
        layout.addLayout(header)

        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(8)
        status_grid.setVerticalSpacing(8)
        self.status_card = MetricCard(get_text("card_knowledge_base"), get_text("status_loading_index"))
        self.chunk_card = MetricCard(get_text("card_chunks"), "-", COLORS["warning"])
        self.model_card = MetricCard(
            get_text("card_model"),
            self.settings.llm_model if self.settings.llm_api_key else get_text("model_local"),
        )
        self.watch_card = MetricCard(get_text("watch_label"), get_text("watch_starting"), COLORS["accent2"])
        status_grid.addWidget(self.status_card, 0, 0)
        status_grid.addWidget(self.chunk_card, 0, 1)
        status_grid.addWidget(self.model_card, 1, 0)
        if self.settings.can_manage_knowledge:
            status_grid.addWidget(self.watch_card, 1, 1)
        layout.addLayout(status_grid)

        self.rebuild_index_button = self._button(get_text("btn_rebuild_index"), primary=True)
        self.rebuild_index_button.clicked.connect(self._rebuild_async)
        if self.settings.can_manage_knowledge:
            layout.addWidget(self.rebuild_index_button)

        self.script_gen_button = self._button(get_text("btn_script_gen"), primary=True)
        self.script_gen_button.clicked.connect(self._open_script_generator)
        layout.addWidget(self.script_gen_button)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.api_button = self._button(get_text("btn_api_settings"))
        self.api_button.clicked.connect(self._open_api_settings)
        self.fav_button = self._button(get_text("btn_favorites"))
        self.fav_button.clicked.connect(self._open_favorites)
        actions.addWidget(self.api_button)
        actions.addWidget(self.fav_button)
        layout.addLayout(actions)

        prompt_label = QLabel(get_text("quick_questions_label"))
        prompt_label.setObjectName("section")
        layout.addWidget(prompt_label)
        for key in ("quick_q1", "quick_q2", "quick_q3"):
            prompt = get_text(key)
            button = self._button(prompt)
            button.clicked.connect(lambda _checked=False, text=prompt: self._ask(text))
            layout.addWidget(button)

        source_title = QLabel(get_text("section_sources"))
        source_title.setObjectName("section")
        source_subtitle = QLabel(get_text("sources_subtitle"))
        source_subtitle.setObjectName("muted")
        source_subtitle.setWordWrap(True)
        layout.addWidget(source_title)
        layout.addWidget(source_subtitle)

        self._source_list_html = self._empty_sources_html()
        self.sources = QWebEngineView()
        self.sources.setObjectName("sourcesCanvas")
        self.sources.setStyleSheet("background: transparent; border: 0;")
        self.sources.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.sources.page().urlChanged.connect(self._on_src_url)

        wb_ref = self
        class _SrcPage(QWebEnginePage):
            def javaScriptConsoleMessage(self2, level, msg, line, source):
                wb_ref._on_console_msg(level, msg, line, source)
        self.sources.setPage(_SrcPage(self.sources))
        self.sources.page().setBackgroundColor(QColor(COLORS["bg"]))
        self.sources.setHtml(self._source_list_html)

        src_nav = QHBoxLayout()
        back_btn = QPushButton(get_text("btn_back_to_sources"))
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.sources.setHtml(self._source_list_html))
        src_nav.addWidget(back_btn)
        src_nav.addStretch(1)
        layout.addLayout(src_nav)
        layout.addWidget(self.sources, stretch=1)
        return panel

    def _panel(self, fixed_width: int | None = None) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        if fixed_width:
            panel.setFixedWidth(fixed_width)
        else:
            panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return panel

    def _button(self, text: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _toggle_sidebar(self) -> None:
        self.sidebar_container.setHidden(not self.sidebar_container.isHidden())

    def _setup_shortcuts(self) -> None:
        self.focus_question_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.focus_question_shortcut.setObjectName("focusQuestionShortcut")
        self.focus_question_shortcut.setContext(Qt.WindowShortcut)
        self.focus_question_shortcut.activated.connect(self._focus_question_input)

        self.new_session_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.new_session_shortcut.setObjectName("newSessionShortcut")
        self.new_session_shortcut.setContext(Qt.WindowShortcut)
        self.new_session_shortcut.activated.connect(self._new_session_from_shortcut)

        self.toggle_sidebar_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.toggle_sidebar_shortcut.setObjectName("toggleSidebarShortcut")
        self.toggle_sidebar_shortcut.setContext(Qt.WindowShortcut)
        self.toggle_sidebar_shortcut.activated.connect(self._toggle_sidebar)

    def _focus_question_input(self) -> None:
        self.question.setFocus(Qt.ShortcutFocusReason)
        self.question.selectAll()

    def _new_session_from_shortcut(self) -> None:
        if self.is_busy:
            return
        self._new_session()
        self._focus_question_input()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Move, QEvent.Resize) and hasattr(self, "loader_overlay"):
            self.loader_overlay.setGeometry(self._loader_geometry())
            self.loader_overlay.raise_()
        return super().eventFilter(watched, event)

    def _loader_geometry(self):
        if not self._loader_full_window:
            return self.main_workspace.geometry()
        return self.centralWidget().rect()

    def _show_loader(self, text: str, *, full_window: bool = False) -> None:
        self._loader_full_window = full_window
        self.loader_overlay.set_text(text)
        self.loader_overlay.setGeometry(self._loader_geometry())
        self.loader_overlay.raise_()
        self.loader_overlay.show()

    def _hide_loader(self, *, force: bool = False) -> None:
        if force or not self.is_busy:
            self.loader_overlay.set_progress_text("")
            self.loader_overlay.hide()

    def _load_pipeline_if_ready(self) -> None:
        index_dir = self.settings.data_dir / "index"
        if not (index_dir / "chunks.json").exists() or not (index_dir / "vectors.npy").exists():
            self.pipeline = None
            self.status_card.set_value(get_text("kb_not_built"), COLORS["danger"])
            self.chunk_card.set_value("-", COLORS["warning"])
            self.sources.setHtml(self._empty_sources_html(get_text("sources_not_built")))
            return
        self.pipeline = RAGPipeline(self.settings)
        self.status_card.set_value(get_text("kb_loaded"), COLORS["accent"])
        self.chunk_card.set_value(str(len(self.pipeline.store.chunks)), COLORS["warning"])
        model_name = self.settings.llm_model if self.settings.llm_api_key else get_text("model_local")
        model_color = COLORS["accent"] if self.settings.llm_api_key else COLORS["warning"]
        self.model_card.set_value(model_name, model_color)
        self.sources.setHtml(self._empty_sources_html())
        self._refresh_session_list()

    def _on_src_url(self, url: QUrl) -> None:
        """拦截 #srcN 锚点链接，在新窗口显示原始知识文档"""
        fragment = url.fragment()  # e.g. "src1"
        if not fragment.startswith("src"):
            return
        try:
            index = int(fragment[3:])
            source_path = self._source_paths.get(index)
            if not source_path:
                return
        except (ValueError, KeyError):
            return

        file_path = Path(source_path)
        if not file_path.exists():
            QMessageBox.warning(self, get_text("source_file_not_found"),
                                f"{file_path.name}")
            return

        suffix = file_path.suffix.lower()
        if suffix == ".md":
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            html_body = markdown_to_html(text)
            html_content = web_wrapper(html_body)
        elif suffix in (".html", ".htm"):
            with open(file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            img_base = str(file_path.parent / "images").replace(os.sep, "/")
            css_base = str(self._project_root / "wavEDA_docs" / "helpHtml" / "helpHtml" / "css").replace(os.sep, "/")
            html_content = re.sub(r'src="\.?/?images/', f'src="file:///{img_base}/', html_content)
            html_content = re.sub(r'href="\.\./css/', f'href="file:///{css_base}/', html_content)
        else:
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
                html_content = web_wrapper(
                    f"<pre style='white-space:pre-wrap;font-size:13px;line-height:1.6;'>{html.escape(text)}</pre>"
                )
            except Exception:
                QMessageBox.warning(self, get_text("source_file_not_found"),
                                    f"{file_path.name}")
                return

        viewer = SourceViewer(
            file_path.stem,
            html_content,
            self,
            file_path=file_path,
            read_only=not self.settings.can_manage_knowledge,
        )
        if self.settings.can_manage_knowledge:
            viewer.knowledge_changed.connect(self._check_source_changes)
        viewer.show()

    def _on_console_msg(self, level, msg: str, line: int, source: str) -> None:
        if msg.startswith("RAGGG_CITATION:") or msg.startswith("RAGGG_SOURCE:"):
            try:
                rank = int(msg.partition(":")[2])
            except ValueError:
                return
            self._focus_source(rank)
        elif msg.startswith("RAGGG_FAV"):
            turn_idx = -1
            if ":" in msg:
                try:
                    turn_idx = int(msg.split(":", 1)[1])
                except ValueError:
                    pass
            self._do_fav(turn_idx)
        elif msg.startswith("RAGGG_FIX"):
            turn_idx = -1
            if ":" in msg:
                try:
                    turn_idx = int(msg.split(":", 1)[1])
                except ValueError:
                    pass
            self._do_fix_answer(turn_idx)
        elif msg.startswith("RAGGG_QUICK:"):
            question = msg.partition(":")[2].strip()
            if question:
                QTimer.singleShot(0, lambda current=question: self._ask(current))
        elif msg.startswith("RAGGG_FAVDEL:"):
            # Not used here; favorites dialog uses Qt buttons now
            pass

    def _focus_source(self, rank: int) -> None:
        source_path = self._source_paths.get(rank)
        if not source_path:
            return
        file_path = Path(source_path)
        if not file_path.exists():
            QMessageBox.warning(self, get_text("source_file_not_found"), file_path.name)
            return

        suffix = file_path.suffix.lower()
        if suffix == ".md":
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            html_content = web_wrapper(markdown_to_html(text))
        elif suffix in (".html", ".htm"):
            html_content = file_path.read_text(encoding="utf-8", errors="ignore")
            img_base = str(file_path.parent / "images").replace(os.sep, "/")
            css_base = str(
                self._project_root / "wavEDA_docs" / "helpHtml" / "helpHtml" / "css"
            ).replace(os.sep, "/")
            html_content = re.sub(
                r'src="\.?/?images/',
                f'src="file:///{img_base}/',
                html_content,
            )
            html_content = re.sub(
                r'href="\.\./css/',
                f'href="file:///{css_base}/',
                html_content,
            )
        else:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            html_content = web_wrapper(
                "<pre style='white-space:pre-wrap;font-size:13px;line-height:1.6;'>"
                f"{html.escape(text)}</pre>"
            )

        viewer = SourceViewer(
            file_path.stem,
            html_content,
            self,
            file_path=file_path,
            read_only=not self.settings.can_manage_knowledge,
        )
        if self.settings.can_manage_knowledge:
            viewer.knowledge_changed.connect(self._check_source_changes)
        viewer.show()

    def _do_fav(self, turn_idx: int = -1) -> None:
        q, a = self._resolve_qa(turn_idx)
        if q and a:
            favs = self._load_favs()
            favs.append({"question": q, "answer": a, "time": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")})
            with open(self._fav_file, "w", encoding="utf-8") as f:
                import json as _json; _json.dump(favs, f, ensure_ascii=False, indent=2)
            self.status_card.set_value(get_text("favorites_saved"), COLORS["accent"])

    def _resolve_qa(self, turn_idx: int = -1) -> tuple[str, str]:
        if turn_idx >= 0 and turn_idx in self._turn_qa_pairs:
            return self._turn_qa_pairs[turn_idx]
        return self._last_qa

    def _do_fix_answer(self, turn_idx: int = -1) -> None:
        """多轮纠错 → 审核队列（不再直接写知识库）"""
        if not self.settings.can_manage_knowledge:
            return
        q, a = self._resolve_qa(turn_idx)
        if not q or not a:
            return

        from raggg.desktop.correction_review import CorrectionDialog, submit_correction
        from raggg.generation.llm_client import OpenAICompatibleClient

        client = None
        if self.settings.llm_api_key:
            try:
                client = OpenAICompatibleClient(
                    self.settings.llm_base_url,
                    self.settings.llm_api_key,
                    self.settings.llm_model,
                )
            except Exception:
                pass

        dlg = CorrectionDialog(q, a, client, self)
        if dlg.exec() != QDialog.Accepted:
            return

        submit_correction(
            self._project_root, q, a,
            dlg.refined_content, dlg.notes,
        )
        QMessageBox.information(
            self, get_text("fix_dialog_title"),
            "纠错内容已提交到审核队列。\n"
            "请前往 设置 → 纠错审核 标签页进行审批。",
        )

    def _load_favs(self) -> list:
        import json as _json
        if not self._fav_file.exists():
            return []
        try:
            with open(self._fav_file, "r", encoding="utf-8") as f:
                value = _json.load(f)
        except (OSError, UnicodeDecodeError, _json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []


    def _open_favorites(self) -> None:
        favs = self._load_favs()
        if not favs:
            QMessageBox.information(self, get_text("favorites_title"), get_text("msg_favorites_empty"))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(get_text("favorites_title"))
        dialog.resize(780, 600)
        dialog.setStyleSheet(f"QDialog {{ background: {COLORS['bg']}; }}")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        # ── 搜索栏 ──
        search_row = QHBoxLayout()
        search_icon = QLabel("🔍")
        search_icon.setStyleSheet(f"font-size:16px;")
        search_row.addWidget(search_icon)
        search_input = QLineEdit()
        search_input.setObjectName("favoritesSearchInput")
        search_input.setPlaceholderText(get_text("favorites_search_placeholder"))
        search_input.setStyleSheet(f"""
            QLineEdit {{ background: {COLORS['surface2']}; color: {COLORS['text']};
                border: 1px solid {COLORS['border']}; border-radius: 12px;
                padding: 10px 14px; font-size: 13px; }}
            QLineEdit:focus {{ border-color: {COLORS['accent']}; }}
        """)
        search_row.addWidget(search_input, stretch=1)
        layout.addLayout(search_row)

        # ── 结果计数 ──
        self._fav_count_label = QLabel(f"{len(favs)} 条收藏")
        self._fav_count_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        layout.addWidget(self._fav_count_label)

        # ── 卡片列表（点击展开） ──
        from PySide6.QtWidgets import QScrollArea
        scroll = QWidget()
        scroll_layout = QVBoxLayout(scroll)
        scroll_layout.setSpacing(8)

        favorite_items: list[dict] = []
        for i, f_item in enumerate(reversed(favs)):
            real_idx = len(favs) - 1 - i

            # 折叠卡片
            card = QFrame()
            card.setObjectName("metricCard")
            card.setCursor(Qt.PointingHandCursor)
            card.setStyleSheet(f"""
                QFrame#metricCard {{ background: {COLORS['surface2']}; border-radius: 12px;
                    border: 1px solid {COLORS['border']}; }}
                QFrame#metricCard:hover {{ border-color: {COLORS['accent']}; }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(4)

            # 简略行：Q badge + 问题前60字 + 时间 + 删除
            brief_row = QHBoxLayout()
            q_badge = QLabel("Q")
            q_badge.setFixedSize(20, 20)
            q_badge.setAlignment(Qt.AlignCenter)
            q_badge.setStyleSheet(f"background:{COLORS['accent']};color:#fff;font-weight:700;font-size:10px;border-radius:10px;")
            brief_row.addWidget(q_badge)
            q_preview = QLabel(html.escape(f_item.get('question', '')[:80]))
            q_preview.setStyleSheet(f"color:{COLORS['text']};font-size:13px;")
            brief_row.addWidget(q_preview, stretch=1)
            time_lbl = QLabel(f_item.get('time', ''))
            time_lbl.setStyleSheet(f"color:{COLORS['subtle']};font-size:10px;")
            brief_row.addWidget(time_lbl)

            expand_arrow = QLabel("▸")
            expand_arrow.setStyleSheet(f"color:{COLORS['muted']};font-size:12px;")
            brief_row.addWidget(expand_arrow)

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(20, 20)
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {COLORS['subtle']}; border: 0; font-size: 11px; border-radius: 10px; }}
                QPushButton:hover {{ background: {COLORS['danger']}; color: #fff; }}
            """)
            del_btn.clicked.connect(lambda ch=False, idx=real_idx: self._do_fav_del(idx, dialog))
            brief_row.addWidget(del_btn)
            card_layout.addLayout(brief_row)

            # 展开区域（默认隐藏）
            from PySide6.QtWidgets import QTextEdit
            detail_widget = QWidget()
            detail_layout = QVBoxLayout(detail_widget)
            detail_layout.setContentsMargins(0, 4, 0, 0)
            q_full = QLabel(f"<b style='color:{COLORS['accent']};'>Q:</b> {html.escape(f_item.get('question', ''))}")
            q_full.setWordWrap(True)
            q_full.setStyleSheet(f"color:{COLORS['text']};font-size:12px;")
            detail_layout.addWidget(q_full)

            a_text = QTextEdit()
            a_text.setReadOnly(True)
            raw = f_item.get('answer', '')
            a_text.setHtml(f"<div style='color:{COLORS['text']};line-height:1.55;'>{markdown_to_html(raw)}</div>")
            a_text.setMaximumHeight(300)
            a_text.setStyleSheet(f"background:{COLORS['surface']};border:0;border-radius:8px;padding:4px;")
            detail_layout.addWidget(a_text)
            detail_widget.hide()
            card_layout.addWidget(detail_widget)

            # 点击切换展开
            info = {
                "card": card, "arrow": expand_arrow, "detail": detail_widget,
                "f_item": f_item, "a_text": a_text,
            }
            favorite_items.append(info)

            def make_toggle(d=detail_widget, a=expand_arrow):
                def handler(_ev=None):
                    d.setVisible(not d.isVisible())
                    a.setText("▾" if d.isVisible() else "▸")
                return handler

            card.mousePressEvent = make_toggle()

            scroll_layout.addWidget(card)

        no_results = QLabel(get_text("favorites_no_results"))
        no_results.setObjectName("favoritesNoResults")
        no_results.setStyleSheet(f"color:{COLORS['muted']};font-size:14px;padding:40px;")
        no_results.setAlignment(Qt.AlignCenter)
        no_results.hide()
        scroll_layout.addWidget(no_results)
        scroll_layout.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(scroll)
        area.setStyleSheet(f"QScrollArea {{ background: transparent; border: 0; }}")
        layout.addWidget(area, stretch=1)

        # ── 搜索逻辑 ──
        def filter_cards(query: str) -> None:
            if not query.strip():
                for item in favorite_items:
                    item["card"].setVisible(True)
                    # 收起所有展开
                    item["detail"].hide()
                    item["arrow"].setText("▸")
                no_results.hide()
                self._fav_count_label.setText(f"{len(favs)} 条收藏")
                return

            scored = []
            for item in favorite_items:
                f_item = item["f_item"]
                if favorite_matches(f_item, query):
                    score = favorite_score(f_item, query)
                    scored.append((score, item))
                else:
                    item["card"].setVisible(False)

            scored.sort(key=lambda x: -x[0])

            for rank, (score, item) in enumerate(scored):
                item["card"].setVisible(True)
                # 自动展开匹配项
                item["detail"].setVisible(True)
                item["arrow"].setText("▾")
                # 移到顶部
                scroll_layout.removeWidget(item["card"])
                scroll_layout.insertWidget(rank, item["card"])
                # 高亮
                raw = item["f_item"].get('answer', '')
                rendered = markdown_to_html(raw)
                highlighted = highlight_keywords(rendered, query)
                item["a_text"].setHtml(f"<div style='color:{COLORS['text']};line-height:1.55;'>{highlighted}</div>")

            visible = len(scored)
            no_results.setVisible(visible == 0)
            self._fav_count_label.setText(f"{visible}/{len(favs)} 条匹配")

        search_input.textChanged.connect(filter_cards)
        dialog.exec()

    def _do_fav_del(self, idx: int, dialog: QDialog) -> None:
        favs = self._load_favs()
        if 0 <= idx < len(favs):
            del favs[idx]
            with open(self._fav_file, "w", encoding="utf-8") as f:
                import json as _json; _json.dump(favs, f, ensure_ascii=False, indent=2)
        dialog.accept()
        self._open_favorites()

    def _open_api_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        dialog.knowledge_changed.connect(self._on_external_knowledge_change)
        if dialog.exec() == QDialog.Accepted:
            self.settings = load_settings()
            self._load_pipeline_if_ready()
            self._refresh_ui_language()
            QMessageBox.information(self, get_text("settings_title"), get_text("msg_api_saved"))

    def _on_external_knowledge_change(self) -> None:
        if self.settings.can_manage_knowledge:
            self._check_source_changes()
        else:
            self._load_pipeline_if_ready()

    def _open_script_generator(self) -> None:
        dialog = ScriptGeneratorDialog(self.settings, self)
        dialog.exec()

    def _refresh_ui_language(self) -> None:
        """刷新所有 UI 文本以反映当前语言设置"""
        lang = get_language()
        # 侧边栏按钮
        self.api_button.setText(get_text("btn_api_settings"))
        self.fav_button.setText(get_text("btn_favorites"))
        self.rebuild_index_button.setText(get_text("btn_rebuild_index"))

    def _import_document(self) -> None:
        """上传文件附加到当前会话，复制到会话附件目录持久化"""
        if self.is_busy:
            return
        current_model = self.settings.llm_model
        is_vision = current_model in VISION_MODELS

        filters = "Documents (*.pdf *.pptx *.docx *.md *.txt *.html)"
        if is_vision:
            filters += ";;Images (*.png *.jpg *.jpeg *.gif *.bmp)"

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            get_text("upload_dialog_title"),
            str(self._project_root),
            filters,
        )
        if not paths:
            return

        session = self._session_manager.current
        if session is None:
            return
        store_dir = self._session_manager.attachments_dir(session.id)
        store_dir.mkdir(parents=True, exist_ok=True)

        added_images = False
        existing_names = {path.name for path, _text in self._temp_attachments}
        for path in paths:
            filepath = Path(path)
            if filepath.name in existing_names:
                continue
            try:
                text, is_image = self._extract_temporary_attachment(filepath, is_vision)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, get_text("import_failed"), str(error))
                continue
            if text is None:
                continue

            # 复制到会话附件目录
            import shutil
            stored = store_dir / filepath.name
            # 避免同名覆盖
            counter = 1
            while stored.exists():
                stem = filepath.stem
                stored = store_dir / f"{stem}_{counter}{filepath.suffix}"
                counter += 1
            shutil.copy2(filepath, stored)

            self._temp_attachments.append((stored, text))
            session.attachment_paths.append(str(stored))
            existing_names.add(filepath.name)
            added_images = added_images or is_image

        self._session_manager._save()

        if added_images:
            QMessageBox.information(
                self,
                get_text("upload_image_title"),
                get_text("upload_image_hint"),
            )
        self._refresh_attachment_ui()

    def _extract_temporary_attachment(
        self,
        filepath: Path,
        is_vision: bool,
    ) -> tuple[str | None, bool]:
        """Extract one temporary attachment and report whether it is an image."""
        suffix = filepath.suffix.lower()
        text = ""
        is_image = suffix in (".png", ".jpg", ".jpeg", ".gif", ".bmp")

        # 图片：转 base64
        if is_image:
            if not is_vision:
                QMessageBox.information(
                    self,
                    get_text("upload_image_title"),
                    get_text("upload_image_no_vision"),
                )
                return None, False
            import base64 as _b64
            data = filepath.read_bytes()
            b64 = _b64.b64encode(data).decode()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                       ".gif": "image/gif", ".bmp": "image/bmp"}
            mime = mime_map.get(suffix, "image/png")
            text = f"[IMAGE: {filepath.name}]\ndata:{mime};base64,{b64}"
        elif suffix == ".pdf":
            try:
                from raggg.pipeline.ingestion import _extract_pdf_text
                text = _extract_pdf_text(filepath)
            except Exception:
                text = f"[PDF: {filepath.name}]"
        elif suffix == ".pptx":
            from raggg.pipeline.knowledge_import import extract_pptx_text
            text = extract_pptx_text(filepath)
        elif suffix == ".docx":
            try:
                from raggg.pipeline.ingestion import _extract_docx_text
                text = _extract_docx_text(filepath)
            except Exception:
                text = f"[DOCX: {filepath.name}]"
        elif suffix in (".md", ".txt", ".html", ".htm"):
            text = filepath.read_text(encoding="utf-8", errors="ignore")

        if not text.strip():
            QMessageBox.warning(self, get_text("import_failed"), get_text("kbm_import_empty"))
            return None, False

        return text, is_image

    def _refresh_attachment_ui(self) -> None:
        while self.attachment_cards_layout.count():
            item = self.attachment_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not self._temp_attachments:
            self.attachment_scroll.hide()
            self.question.setPlaceholderText(get_text("placeholder_input"))
            return

        for filepath, _text in self._temp_attachments:
            self.attachment_cards_layout.addWidget(
                self._build_attachment_card(filepath)
            )
        card_width = 300
        content_width = (
            len(self._temp_attachments) * card_width
            + max(0, len(self._temp_attachments) - 1) * 8
            + 4
        )
        self.attachment_cards_widget.setFixedSize(content_width, 68)
        self.attachment_scroll.show()
        self.question.setPlaceholderText(get_text("placeholder_input"))

    def _build_attachment_card(self, filepath: Path) -> QFrame:
        card = QFrame()
        card.setObjectName("attachmentCard")
        card.setFixedSize(300, 60)
        card.setCursor(Qt.PointingHandCursor)
        card.setToolTip(f"双击打开 {filepath.name}\n点击类型徽标查看提取文本")
        card.setStyleSheet(
            "QFrame#attachmentCard {"
            f"background:{COLORS['surface2']};"
            f"border:1px solid {COLORS['border']};"
            "border-radius:8px;"
            "}"
            "QFrame#attachmentCard:hover {"
            f"border-color:{COLORS['accent2']};"
            "}"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 7, 7, 7)
        layout.setSpacing(9)

        suffix = filepath.suffix.lstrip(".").upper() or "FILE"
        badge_colors = {
            "PDF": "#d95757",
            "PPTX": "#b96b45",
            "DOCX": "#3976b8",
            "PNG": "#2f8f83",
            "JPG": "#2f8f83",
            "JPEG": "#2f8f83",
        }
        badge = QLabel(suffix[:4])
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(42, 42)
        badge.setCursor(Qt.PointingHandCursor)
        badge.setStyleSheet(
            f"background:{badge_colors.get(suffix, COLORS['accent2'])};"
            "color:white;border:0;border-radius:6px;"
            "font-size:9px;font-weight:700;"
        )
        badge.setToolTip(suffix)
        layout.addWidget(badge)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 1, 0, 1)
        text_column.setSpacing(2)
        visible_name = filepath.name
        if len(visible_name) > 25:
            visible_name = visible_name[:22].rstrip() + "..."
        name_label = QLabel(visible_name)
        name_label.setToolTip(filepath.name)
        name_label.setStyleSheet(
            f"color:{COLORS['text']};font-size:12px;font-weight:600;border:0;"
        )
        type_label = QLabel(suffix)
        type_label.setStyleSheet(
            f"color:{COLORS['muted']};font-size:10px;border:0;"
        )
        text_column.addWidget(name_label)
        text_column.addWidget(type_label)
        layout.addLayout(text_column, stretch=1)

        close_button = QPushButton("×")
        close_button.setObjectName("attachmentCloseButton")
        close_button.setFixedSize(24, 24)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setToolTip(
            get_text("upload_remove_named").replace("{name}", filepath.name)
        )
        close_button.setStyleSheet(
            "QPushButton#attachmentCloseButton {"
            f"background:{COLORS['surface3']};color:{COLORS['text']};"
            "border:0;border-radius:12px;padding:0;font-size:15px;"
            "}"
            "QPushButton#attachmentCloseButton:hover {"
            f"background:{COLORS['danger']};color:white;"
            "}"
        )
        close_button.clicked.connect(
            lambda _checked=False, target=filepath: self._remove_attachment(target)
        )
        layout.addWidget(close_button, alignment=Qt.AlignTop)

        # 双击打开文件
        def _open_attachment(p: Path = filepath) -> None:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

        card.mouseDoubleClickEvent = lambda _event, p=filepath: _open_attachment(p)

        pass  # badge 仅作类型标识，无点击行为

        return card

    def _open_attachment_text(self, filepath: Path) -> None:
        """点击徽标查看提取文本"""
        text = ""
        for stored, extracted in self._temp_attachments:
            if stored == filepath:
                text = extracted
                break
        if not text:
            text = self._read_stored_attachment_text(filepath)
        from PySide6.QtWidgets import QTextEdit as QTE
        dlg = QDialog(self)
        dlg.setWindowTitle(f"提取文本 — {filepath.name}")
        dlg.resize(600, 450)
        lay = QVBoxLayout(dlg)
        prev = QTE()
        prev.setReadOnly(True)
        prev.setPlainText(text)
        prev.setStyleSheet(
            f"QTextEdit {{ background:{COLORS['surface3']}; color:{COLORS['text']}; "
            f"border:1px solid {COLORS['border']}; border-radius:6px; padding:10px; "
            f"font-size:13px; }}"
        )
        lay.addWidget(prev)
        cls = QPushButton("关闭")
        cls.clicked.connect(dlg.accept)
        lay.addWidget(cls)
        dlg.exec()

    def _remove_attachment(self, filepath: Path) -> None:
        self._temp_attachments = [
            attachment
            for attachment in self._temp_attachments
            if attachment[0] != filepath
        ]
        # 同步删除存储文件和会话引用
        session = self._session_manager.current
        if session:
            stored_str = str(filepath)
            if stored_str in session.attachment_paths:
                session.attachment_paths.remove(stored_str)
                self._session_manager._save()
        try:
            if filepath.exists():
                filepath.unlink()
        except OSError:
            pass
        self._refresh_attachment_ui()

    def _clear_attachment(self) -> None:
        """清除全部临时附件。"""
        self._temp_attachments.clear()
        self._refresh_attachment_ui()

    def _clear_attachment_cards(self) -> None:
        """仅隐藏输入区附件卡片，不删除数据。"""
        while self.attachment_cards_layout.count():
            item = self.attachment_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.attachment_scroll.hide()

    def _load_session_attachments(self) -> None:
        """从当前会话加载附件（切换会话时调用）"""
        self._temp_attachments.clear()
        session = self._session_manager.current
        if session is None:
            self._refresh_attachment_ui()
            return
        # 清理不存在的文件引用
        valid_paths = []
        for stored_str in session.attachment_paths:
            stored = Path(stored_str)
            if stored.exists():
                # 重新提取文本（简单读取，不重新解析复杂格式）
                text = self._read_stored_attachment_text(stored)
                self._temp_attachments.append((stored, text))
                valid_paths.append(stored_str)
        if len(valid_paths) != len(session.attachment_paths):
            session.attachment_paths = valid_paths
            self._session_manager._save()
        self._refresh_attachment_ui()

    @staticmethod
    def _read_stored_attachment_text(filepath: Path) -> str:
        """读取已存储附件的基础文本"""
        suffix = filepath.suffix.lower()
        try:
            if suffix in (".md", ".txt", ".html", ".htm"):
                return filepath.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".pdf":
                try:
                    from raggg.pipeline.ingestion import _extract_pdf_text
                    return _extract_pdf_text(filepath)
                except Exception:
                    pass
            return f"[{suffix.upper().lstrip('.')}: {filepath.name}]"
        except Exception:
            return f"[{filepath.name}]"

    def _build_attachment_context(self) -> str:
        sections = []
        for filepath, attachment_text in self._temp_attachments:
            sections.append(
                f"=== {get_text('kbm_preview_file')}: {filepath.name} ===\n"
                f"{attachment_text[:3000]}\n"
                "==="
            )
        joined_sections = "\n\n".join(sections)
        return (
            f"{get_text('upload_attached_count').replace('{count}', str(len(sections)))}\n\n"
            f"{joined_sections}"
        )

    # ─── 多会话 ──────────────────────────────────
    def _build_session_panel(self) -> QFrame:
        panel = SessionPanel()
        panel.setObjectName("panel")
        panel.setFixedWidth(210)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(get_text("session_panel_title"))
        title.setStyleSheet(f"color:{COLORS['text']};font-weight:700;font-size:12px;")
        header.addWidget(title, stretch=1)
        new_btn = QPushButton("+")
        new_btn.setObjectName("iconButton")
        new_btn.setToolTip(f"{get_text('session_new')} (Ctrl+N)")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._new_session)
        header.addWidget(new_btn)
        layout.addLayout(header)

        from PySide6.QtWidgets import QListWidget
        self.session_list = QListWidget()
        self.session_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: 0; }}
            QListWidget::item {{ padding: 7px 10px; border-radius: 8px; margin: 1px 0;
                color: {COLORS['muted']}; font-size: 11px; }}
            QListWidget::item:hover {{ background: {COLORS['surface2']}; color: {COLORS['text']}; }}
            QListWidget::item:selected {{ background: {COLORS['surface2']}; color: {COLORS['accent']}; font-weight: 600; }}
        """)
        self.session_list.currentRowChanged.connect(self._on_session_switched)
        layout.addWidget(self.session_list, stretch=1)

        del_btn = QPushButton(get_text("session_delete"))
        del_btn.clicked.connect(self._delete_session)
        del_btn.setStyleSheet(f"""
            QPushButton {{ font-size:10px; padding:4px; border-radius:6px;
                background: transparent; color: {COLORS['subtle']}; border: 1px solid {COLORS['border']}; }}
            QPushButton:hover {{ color: {COLORS['danger']}; }}
        """)
        layout.addWidget(del_btn)
        return panel

    def _refresh_session_list(self) -> None:
        self.session_list.blockSignals(True)
        self.session_list.clear()
        sessions = sorted(self._session_manager.sessions.values(),
                         key=lambda s: s.created_at, reverse=True)
        for s in sessions:
            prefix = "● " if s.id == self._session_manager.current_id else "○ "
            from PySide6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(f"{prefix}{s.title}")
            item.setData(Qt.UserRole, s.id)
            self.session_list.addItem(item)
            if s.id == self._session_manager.current_id:
                self.session_list.setCurrentItem(item)
        self.session_list.blockSignals(False)

    def _new_session(self) -> None:
        self._session_manager.new_session()
        self._conversation_history = []
        self._temp_attachments.clear()
        self._refresh_attachment_ui()
        self.chat.setHtml(self._welcome_html(
            chunk_count=str(len(self.pipeline.store.chunks)) if self.pipeline else "-",
            model_name=self.settings.llm_model if self.settings.llm_api_key else get_text("model_local"),
        ))
        self._refresh_session_list()

    def _on_session_switched(self, _row: int) -> None:
        item = self.session_list.currentItem()
        if not item:
            return
        sid = item.data(Qt.UserRole)
        if sid == self._session_manager.current_id:
            return
        self._session_manager.switch_to(sid)
        history = self._session_manager.get_history()
        self._conversation_history = history
        # 加载该会话的附件
        self._load_session_attachments()
        if history:
            self._show_session_content(history)
        else:
            self.chat.setHtml(self._welcome_html(
                chunk_count=str(len(self.pipeline.store.chunks)) if self.pipeline else "-",
                model_name=self.settings.llm_model if self.settings.llm_api_key else get_text("model_local"),
            ))
        self._refresh_session_list()

    def _show_session_content(self, history: list[tuple[str, str]]) -> None:
        """一次性渲染：欢迎语 + 全部历史消息"""
        parts = []
        # 构建欢迎区（纯 HTML，不用 web_wrapper 包）
        model_name = self.settings.llm_model if self.settings.llm_api_key else get_text("model_local")
        chunk_count = str(len(self.pipeline.store.chunks)) if self.pipeline else "-"
        bubbles = get_chat_bubble_colors()
        parts.append(f"""<div style="max-width:760px;margin:52px auto 36px auto;padding:0 24px;">
          <div style="text-align:center;padding:60px 20px;">
          <div style="font-size:22px;font-weight:700;color:{COLORS['accent']};margin-bottom:12px;">WavEDA Knowledge Workbench</div>
          <div style="color:{COLORS['muted']};margin-bottom:24px;">{get_text('startup_brand_subtitle')}</div>
          <div style="display:flex;justify-content:center;gap:12px;flex-wrap:wrap;">
            <div style="background:{COLORS['surface2']};border-radius:10px;padding:14px 18px;text-align:center;min-width:100px;">
              <div style="font-size:20px;font-weight:700;color:{COLORS['accent']};">{chunk_count}</div>
              <div style="color:{COLORS['muted']};font-size:12px;">{get_text('startup_chunks_label')}</div>
            </div>
            <div style="background:{COLORS['surface2']};border-radius:10px;padding:14px 18px;text-align:center;min-width:100px;">
              <div style="font-size:20px;font-weight:700;color:{COLORS['accent2']};">{get_text('badge_waveda_first')}</div>
              <div style="color:{COLORS['muted']};font-size:12px;">{get_text('startup_strategy_label')}</div>
            </div>
            <div style="background:{COLORS['surface2']};border-radius:10px;padding:14px 18px;text-align:center;min-width:100px;">
              <div style="font-size:20px;font-weight:700;color:{COLORS['warning']};">{model_name}</div>
              <div style="color:{COLORS['muted']};font-size:12px;">{get_text('startup_llm_label')}</div>
            </div>
          </div>
          <div style="margin-top:28px;color:{COLORS['subtle']};font-size:13px;">{get_text('startup_hint')}</div>
          </div></div>""")

        # 逐条追加历史
        for q, a in history:
            parts.append(f"""<div style="margin:10px 26px 6px 26px;display:flex;justify-content:flex-end;">
              <div style="max-width:76%;padding:12px 15px;border-radius:18px 18px 4px 18px;background:{bubbles['user_bg']};border:1px solid {bubbles['user_border']};color:{bubbles['text']};line-height:1.58;">
                {html.escape(q)}
              </div>
            </div>""")
            rendered = markdown_to_html(a)
            parts.append(f"""<div style="margin:8px 26px 14px 26px;display:flex;justify-content:flex-start;">
              <div style="max-width:82%;">
              <div style="display:flex;align-items:center;gap:8px;margin-left:2px;margin-bottom:6px;">
                <button onclick="var p=this.parentElement.nextElementSibling;var t=document.createElement('textarea');t.value=p.innerText;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);var s=this.innerHTML;this.innerHTML='{html.escape(get_text("btn_copied"))}';setTimeout(function(){{this.innerHTML=s;}}.bind(this),1000)"
                  style="background:{bubbles['surface2']};color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:10px;padding:3px 10px;font-size:11px;cursor:pointer;"
                  onmouseover="this.style.color='{bubbles['accent']}'" onmouseout="this.style.color='{bubbles['muted']}'">{html.escape(get_text("btn_copy"))}</button>
                <button onclick="console.log('RAGGG_FAV');this.innerHTML='{html.escape(get_text("btn_faved"))}';this.style.color='{bubbles['accent']}';setTimeout(function(){{this.innerHTML='{html.escape(get_text("btn_fav"))}';this.style.color='{bubbles['muted']}'}}.bind(this),1500)"
                  style="background:{bubbles['surface2']};color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:10px;padding:3px 10px;font-size:11px;cursor:pointer;"
                  onmouseover="this.style.color='{bubbles['accent']}'" onmouseout="this.style.color='{bubbles['muted']}'">{html.escape(get_text("btn_fav"))}</button>
                <button onclick="console.log('RAGGG_FIX')"
                  style="background:{bubbles['surface2']};color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:10px;padding:3px 10px;font-size:11px;cursor:pointer;"
                  onmouseover="this.style.color='{bubbles['accent']}'" onmouseout="this.style.color='{bubbles['muted']}'">{html.escape(get_text("btn_fix"))}</button>
              </div>
              <div style="padding:15px 17px;border-radius:18px 18px 18px 4px;background:{bubbles['assistant_bg']};border:1px solid {bubbles['assistant_border']};color:{bubbles['text']};line-height:1.6;">
                {rendered}
              </div>
              </div>
            </div>""")

        self.chat.setHtml(web_wrapper("\n".join(parts)))

    def _delete_session(self) -> None:
        name = self._session_manager.current.title if self._session_manager.current else ""
        reply = QMessageBox.question(
            self, get_text("session_delete_confirm"),
            get_text("session_delete_msg").replace("{name}", name),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        sid = self._session_manager.current_id
        if self._session_manager.delete(sid):
            self._conversation_history = self._session_manager.get_history()
            self._temp_attachments.clear()
            self._refresh_attachment_ui()
            self.chat.setHtml(self._welcome_html(
                chunk_count=str(len(self.pipeline.store.chunks)) if self.pipeline else "-",
                model_name=self.settings.llm_model if self.settings.llm_api_key else get_text("model_local"),
            ))
            self._refresh_session_list()
            # 清理附件文件
            import shutil
            att_dir = self._session_manager.attachments_dir(sid)
            try:
                shutil.rmtree(att_dir, ignore_errors=True)
            except Exception:
                pass

    def _toggle_session_panel(self) -> None:
        self.session_panel.setVisible(not self.session_panel.isVisible())

    def _rebuild_async(self) -> None:
        if not self.settings.can_manage_knowledge:
            return
        if self.is_busy:
            return
        self._set_busy(True, get_text("status_building"))

        def rebuild() -> BuildReport:
            return build_knowledge_base(
                self.settings,
                on_progress=worker.signals.progress.emit,
            )

        worker = Worker(rebuild)
        worker.signals.progress.connect(self._on_build_progress)
        worker.signals.result.connect(self._on_rebuild_done)
        worker.signals.error.connect(lambda message: self._show_error(get_text("error_rebuild_title"), message))
        worker.signals.finished.connect(lambda: self._set_busy(False, get_text("status_ready")))
        self._start_worker(worker)

    def _on_rebuild_done(self, report: BuildReport) -> None:
        self.chunk_card.set_value(str(report.chunk_count), COLORS["warning"])
        mark_imports_indexed(self.settings.obsidian_vault_root)
        self._load_pipeline_if_ready()
        self._sync_watch_snapshot()

    def _on_build_progress(self, progress: BuildProgress) -> None:
        suffix = ""
        if progress.current is not None and progress.total:
            suffix = f" ({progress.current}/{progress.total})"
        self.loader_overlay.set_progress_text(progress.message + suffix)

    def _start_source_watcher(self) -> None:
        if not self.settings.can_manage_knowledge:
            return
        self._sync_watch_snapshot()
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(5000)
        self._watch_timer.timeout.connect(self._check_source_changes)
        self._watch_timer.start()

        self._watch_debounce_timer = QTimer(self)
        self._watch_debounce_timer.setSingleShot(True)
        self._watch_debounce_timer.setInterval(2000)
        self._watch_debounce_timer.timeout.connect(self._trigger_watch_rebuild)

    def _sync_watch_snapshot(self) -> None:
        self._source_snapshot = scan_source_tree(self.settings.obsidian_vault_root)
        self._watch_pending_snapshot = None
        self._watch_rebuild_requested = False
        if hasattr(self, "watch_card"):
            self.watch_card.set_value(get_text("watch_active"), COLORS["accent2"])

    def _check_source_changes(self) -> None:
        if not self.settings.can_manage_knowledge:
            return
        current = scan_source_tree(self.settings.obsidian_vault_root)
        if not snapshot_changed(self._source_snapshot, current):
            return
        self._watch_pending_snapshot = current
        self.watch_card.set_value(get_text("watch_changed"), COLORS["warning"])
        if not self.is_busy:
            self.activity_label.show()
            self.activity_label.setText(get_text("watch_waiting_stable"))
            self.activity_label.setStyleSheet(f"color: {COLORS['warning']};")
        self._watch_debounce_timer.start()

    def _trigger_watch_rebuild(self) -> None:
        if self._watch_pending_snapshot is None:
            return
        if self.is_busy:
            self._watch_rebuild_requested = True
            self.watch_card.set_value(get_text("watch_idle"), COLORS["warning"])
            return

        snapshot_after_change = self._watch_pending_snapshot
        self._set_busy(True, get_text("watch_busy_msg"))
        self.watch_card.set_value(get_text("watch_rebuilding"), COLORS["warning"])

        def rebuild() -> BuildReport:
            return build_knowledge_base(
                self.settings,
                on_progress=worker.signals.progress.emit,
            )

        worker = Worker(rebuild)
        worker.signals.progress.connect(self._on_build_progress)
        worker.signals.result.connect(lambda report: self._on_watch_rebuild_done(report, snapshot_after_change))
        worker.signals.error.connect(lambda message: self._show_error(get_text("watch_rebuild_error"), message))
        worker.signals.finished.connect(lambda: self._set_busy(False, get_text("status_ready")))
        self._start_worker(worker)

    def _on_watch_rebuild_done(self, report: BuildReport, snapshot_after_change: SourceSnapshot) -> None:
        self.chunk_card.set_value(str(report.chunk_count), COLORS["warning"])
        mark_imports_indexed(self.settings.obsidian_vault_root)
        self._load_pipeline_if_ready()
        self._source_snapshot = snapshot_after_change
        self._watch_pending_snapshot = None
        self._watch_rebuild_requested = False
        self.watch_card.set_value(get_text("watch_active"), COLORS["accent2"])

    def _ask(self, question: str | None = None) -> None:
        if self.is_busy:
            return
        user_question = (question or self.question.text()).strip()
        if not user_question:
            return
        if self.pipeline is None:
            QMessageBox.information(self, get_text("error_no_kb_title"), get_text("error_no_kb_msg"))
            return
        attachment_context = None
        if self._temp_attachments:
            attachment_context = self._build_attachment_context()
            # 发送后隐藏输入区附件卡片，数据保留在 _temp_attachments 维持会话记忆
            self._clear_attachment_cards()
        self.question.clear()
        self._append_user(
            user_question[:500] + ("..." if len(user_question) > 500 else "")
        )
        token = CancellationToken()
        self._generation_token = token
        self._set_busy(True, get_text("status_searching"))
        conversation_history = self._session_manager.get_history()
        stream_id = self._begin_streaming_assistant()

        def ask_with_streaming() -> AskResult:
            assert self.pipeline is not None
            answer = self.pipeline.ask(
                user_question,
                conversation_history=conversation_history,
                on_chunk=lambda chunk: worker.signals.progress.emit(chunk),
                should_cancel=token.is_cancelled,
                additional_context=attachment_context,
            )
            return AskResult(user_question, answer)

        worker = Worker(ask_with_streaming)
        worker.signals.progress.connect(
            lambda chunk, current_id=stream_id: self._append_stream_chunk(current_id, str(chunk))
        )
        worker.signals.result.connect(
            lambda result, current_id=stream_id: self._on_answer_done(result, current_id)
        )
        worker.signals.error.connect(
            lambda message, current_id=stream_id: self._on_generation_error(
                current_id, user_question, str(message), token
            )
        )
        worker.signals.finished.connect(lambda: self._on_generation_finished(token))
        self._start_worker(worker)

    def _on_ask_button_clicked(self, _checked: bool = False) -> None:
        if self.is_busy and self._generation_token is not None:
            self._cancel_generation()
            return
        self._ask()

    def _cancel_generation(self) -> None:
        token = self._generation_token
        if token is None or token.is_cancelled():
            return
        token.cancel()
        if self.pipeline is not None:
            self.pipeline.cancel_active_request()
        self.ask_button.setDisabled(True)
        text = get_text("status_stopping_generation")
        self.activity_label.setText(text)
        self.activity_label.setVisible(True)

    def _on_generation_finished(self, token: CancellationToken) -> None:
        if self._generation_token is token:
            self._generation_token = None
        self._set_busy(False, get_text("status_ready"))

    def _on_generation_error(
        self,
        stream_id: str,
        _question: str,
        message: str,
        token: CancellationToken,
    ) -> None:
        if token.is_cancelled():
            self._show_cancelled_status(stream_id)
            self._last_qa = ("", "")
            return
        self._on_stream_error(stream_id, message)

    def _start_worker(self, worker: Worker) -> None:
        self._active_workers.append(worker)
        worker.signals.finished.connect(lambda: self._forget_worker(worker))
        self.thread_pool.start(worker)

    def _forget_worker(self, worker: Worker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    def _on_answer_done(self, result: AskResult, stream_id: str | None = None) -> None:
        display_answer = result.answer.answer.strip()
        if result.answer.cancelled:
            self._show_cancelled_status(stream_id)
            self._last_qa = ("", "")
            self._source_list_html = self._sources_html([])
            self.sources.setHtml(self._source_list_html)
            return
        if stream_id is None:
            self._append_assistant(display_answer)
        else:
            self._finish_streaming_assistant(stream_id, display_answer)
        self._remember_turn(result.question, display_answer)
        if result.answer.warning:
            previous_last_qa = self._last_qa
            self._append_assistant(f"> ⚠️ {result.answer.warning}")
            self._last_qa = previous_last_qa
        all_images = _extract_images_from_sources(result.answer.sources, self._image_index)
        if all_images:
            answer_language = RAGPipeline._detect_answer_language(result.question)
            img_html = '<div style="margin:12px 0 8px 0;"><div style="color:' + COLORS["accent2"] + ';font-weight:700;margin-bottom:8px;">' + get_text("screenshot_label", answer_language) + '</div>'
            for index, (img_path, title) in enumerate(all_images[:6], start=1):
                abs_path = img_path.replace(os.sep, "/")
                data_uri = _path_to_data_uri(abs_path)
                if not data_uri:
                    continue
                if answer_language == "en" and contains_han(title):
                    title = f"Reference image {index}"
                safe_title = html.escape(title)
                img_html += f'<p style="margin:6px 0;"><span style="color:{COLORS["muted"]};font-size:12px;">{safe_title}</span><br><img src="{data_uri}" alt="Reference image {index}" style="max-width:100%;max-height:400px;border-radius:8px;border:1px solid {COLORS["border"]};margin-top:4px;"></p>'
            img_html += '</div>'
            self._append_html_to_active_turn(web_wrapper(img_html))
        self._source_list_html = self._sources_html(result.answer.sources)
        self.sources.setHtml(self._source_list_html)

    def _set_busy(self, busy: bool, text: str) -> None:
        self.is_busy = busy
        if busy:
            if self._generation_token is not None:
                # The streaming bubble is the generation indicator. Keeping the
                # overlay here would cover the composer and its stop button.
                self._hide_loader(force=True)
            else:
                self._show_loader(text)
        else:
            self._hide_loader()
        self.activity_label.setText(text)
        self.activity_label.setVisible(busy)
        self.activity_label.setStyleSheet(f"color: {COLORS['warning' if busy else 'accent']};")
        for button in (self.import_button, self.rebuild_index_button, self.script_gen_button):
            button.setDisabled(busy)
        if busy and self._generation_token is not None:
            self.ask_button.setText("■")
            self.ask_button.setToolTip(get_text("btn_stop_generation"))
            self.ask_button.setDisabled(self._generation_token.is_cancelled())
        elif busy:
            self.ask_button.setDisabled(True)
        else:
            self.ask_button.setText("↑")
            self.ask_button.setToolTip(get_text("btn_ask"))
            self.ask_button.setDisabled(False)
        if not busy and self._watch_rebuild_requested and self._watch_pending_snapshot is not None:
            self._watch_rebuild_requested = False
            QTimer.singleShot(0, self._trigger_watch_rebuild)

    def _remember_turn(self, question: str, answer: str) -> None:
        self._session_manager.add_message(question, answer)
        self._conversation_history = self._session_manager.get_history()
        self._finalize_active_turn(len(self._conversation_history))
        # AI 自动标题
        if self._session_manager.current and self._session_manager.current.title == "新对话":
            self._generate_session_title(question, answer)

    def _generate_session_title(self, question: str, answer: str) -> None:
        """AI 生成标题，根据语言切换中英文"""
        lang = get_language()
        if lang == "en":
            prompt = f"Summarize this conversation in 6 words or fewer as a title. Answer with ONLY the title.\nUser: {question[:200]}\nAssistant: {answer[:200]}"
            fallback = question[:30] + ("..." if len(question) > 30 else "")
            max_title_len = 40
        else:
            prompt = f"将以下对话总结为8个字以内的标题，只回答标题不要解释。\n用户：{question[:200]}\n助手：{answer[:200]}"
            fallback = question[:20] + ("..." if len(question) > 20 else "")
            max_title_len = 20

        if self.settings.llm_api_key:
            try:
                from raggg.generation.llm_client import OpenAICompatibleClient
                client = OpenAICompatibleClient(
                    self.settings.llm_base_url, self.settings.llm_api_key, self.settings.llm_model)
                title = client.complete(prompt).strip().strip("\"'《》「」。. ")
                if title and len(title) <= max_title_len:
                    self._session_manager.set_title(title)
                    self._refresh_session_list()
                    return
            except Exception:
                pass
        self._session_manager.set_title(fallback)
        self._refresh_session_list()

    def _append_user(self, question: str) -> None:
        self._last_qa = (question, "")  # 记住问题，等回答来了配对
        self._clear_chat_turn_selection()
        self._chat_turn_counter += 1
        self._active_turn_dom_id = f"rag-turn-{self._chat_turn_counter}"
        pending_index = min(
            len(self._session_manager.get_history()),
            MAX_HISTORY_TURNS - 1,
        )
        bubbles = get_chat_bubble_colors()
        # 附件徽标
        attachment_html = ""
        if self._temp_attachments:
            pills = []
            for stored_path, _text in self._temp_attachments:
                suffix = stored_path.suffix.lstrip(".").upper()[:4]
                pills.append(
                    f"<span style='background:{bubbles['surface2']};color:{bubbles['muted']};"
                    f"border:1px solid {bubbles['border']};border-radius:6px;"
                    f"padding:2px 8px;font-size:10px;margin-right:4px;'>"
                    f"📎 {html.escape(stored_path.name[:30])}</span>"
                )
            attachment_html = (
                f"<div style='margin-top:8px;display:flex;flex-wrap:wrap;gap:4px;'>"
                f"{''.join(pills)}</div>"
            )
        msg_html = web_wrapper(
            f"""<section id="{self._active_turn_dom_id}" data-rag-turn="1" data-turn-index="{pending_index}" style="margin:4px 10px;padding:2px;border-radius:12px;outline:2px solid transparent;">
            <div style="margin:10px 26px 6px 26px;display:flex;justify-content:flex-end;">
              <div style="max-width:76%;padding:12px 15px;border-radius:18px 18px 4px 18px;background:{bubbles['user_bg']};border:1px solid {bubbles['user_border']};box-shadow:0 12px 36px rgba(74,141,180,.10);color:{bubbles['text']};line-height:1.58;">
                {html.escape(question)}{attachment_html}
              </div>
            </div></section>"""
        )
        self._append_html(msg_html)

    def _append_assistant(self, answer: str) -> None:
        self._last_qa = (self._last_qa[0], answer)
        self._turn_qa_pairs[self._chat_turn_counter] = self._last_qa
        rendered = markdown_to_html(answer)
        bubbles = get_chat_bubble_colors()
        btns = _action_buttons_html(
            bubbles,
            include_correction=self.settings.can_manage_knowledge,
        )
        btns = btns.replace("RAGGG_FAV'", f"RAGGG_FAV:{self._chat_turn_counter}'")
        btns = btns.replace("RAGGG_FIX'", f"RAGGG_FIX:{self._chat_turn_counter}'")
        msg_html = web_wrapper(
            f"""<div class="answer-block" style="margin:8px 26px 14px 26px;display:flex;justify-content:flex-start;counter-reset:ordered-item 0;">
              <div style="max-width:82%;">
              <div style="padding:15px 17px;border-radius:18px 18px 18px 4px;background:{bubbles['assistant_bg']};border:1px solid {bubbles['assistant_border']};box-shadow:0 14px 42px rgba(80,150,185,.12);color:{bubbles['text']};line-height:1.6;">
                {rendered}
              </div>
              <div class="answer-actions" style="display:flex;align-items:center;gap:6px;margin-left:2px;">
                {btns}
              </div>
              </div>
            </div>"""
        )
        self._append_html_to_active_turn(msg_html)

    def _begin_streaming_assistant(self) -> str:
        self._stream_message_counter += 1
        stream_id = f"rag-stream-{self._stream_message_counter}"
        actions_id = f"{stream_id}-actions"
        content_id = f"{stream_id}-content"
        bubbles = get_chat_bubble_colors()
        btns = _action_buttons_html(
            bubbles,
            include_correction=self.settings.can_manage_knowledge,
        )
        btns = btns.replace("RAGGG_FAV'", f"RAGGG_FAV:{self._chat_turn_counter}'")
        btns = btns.replace("RAGGG_FIX'", f"RAGGG_FIX:{self._chat_turn_counter}'")
        msg_html = web_wrapper(
            f"""<div id="{stream_id}" class="answer-block" style="margin:8px 26px 14px 26px;display:flex;justify-content:flex-start;">
              <div style="max-width:82%;">
              <div id="{content_id}" style="padding:15px 17px;border-radius:18px 18px 18px 4px;background:{bubbles['assistant_bg']};border:1px solid {bubbles['assistant_border']};box-shadow:0 14px 42px rgba(80,150,185,.12);color:{bubbles['text']};line-height:1.6;white-space:pre-wrap;"><span data-stream-cursor style="color:{bubbles['accent']};">▌</span></div>
              <div id="{actions_id}" class="answer-actions" style="display:none;align-items:center;gap:6px;margin-left:2px;">
                {btns}
              </div>
              </div>
            </div>"""
        )
        self._append_html_to_active_turn(msg_html)
        return stream_id

    def _append_stream_chunk(self, stream_id: str, chunk: str) -> None:
        # Once text starts arriving, reveal the chat instead of covering it
        # with the loading overlay. Busy state still disables user actions.
        self.loader_overlay.hide()
        content_id = json.dumps(f"{stream_id}-content")
        chunk_json = json.dumps(chunk, ensure_ascii=False)
        self.chat.page().runJavaScript(
            f"""var content=document.getElementById({content_id});
if(content){{
  var cursor=content.querySelector('[data-stream-cursor]');
  if(cursor){{cursor.insertAdjacentText('beforebegin', {chunk_json});}}
  window.scrollTo(0, document.body.scrollHeight);
}}"""
        )

    def _finish_streaming_assistant(self, stream_id: str, answer: str) -> None:
        self._last_qa = (self._last_qa[0], answer)
        self._turn_qa_pairs[self._chat_turn_counter] = self._last_qa
        content_id = json.dumps(f"{stream_id}-content")
        actions_id = json.dumps(f"{stream_id}-actions")
        rendered_json = json.dumps(markdown_to_html(answer), ensure_ascii=False)
        self.chat.page().runJavaScript(
            f"""var content=document.getElementById({content_id});
if(content){{content.innerHTML={rendered_json};content.style.whiteSpace='normal';}}
var actions=document.getElementById({actions_id});
if(actions){{actions.style.display='flex';}}
window.scrollTo(0, document.body.scrollHeight);"""
        )

    def _on_stream_error(self, stream_id: str, message: str) -> None:
        self._finish_streaming_assistant(stream_id, get_text("msg_generation_failed") + message)

    def _append_html(self, html_content: str) -> None:
        """Append HTML content to the chat WebView, preserving existing content."""
        html_json = json.dumps(html_content, ensure_ascii=False)
        self.chat.page().runJavaScript(
            f"""var div=document.createElement('div');
            div.innerHTML={html_json};
            document.body.appendChild(div);
            window.scrollTo(0, document.body.scrollHeight);
"""
        )

    def _append_html_to_active_turn(self, html_content: str) -> None:
        """Append content to the active Q&A group so it is deleted as one turn."""
        if not self._active_turn_dom_id:
            self._append_html(html_content)
            return
        turn_id = json.dumps(self._active_turn_dom_id)
        html_json = json.dumps(html_content, ensure_ascii=False)
        self.chat.page().runJavaScript(
            f"""var host=document.getElementById({turn_id});
var div=document.createElement('div');
div.innerHTML={html_json};
if(host){{while(div.firstChild){{host.appendChild(div.firstChild);}}}}
else{{document.body.appendChild(div);}}
window.scrollTo(0, document.body.scrollHeight);"""
        )

    def _show_cancelled_status(self, stream_id: str | None) -> None:
        """Replace an interrupted answer with a compact, non-persistent status."""
        stopped = get_text("generation_stopped")
        if stream_id is None:
            bubbles = get_chat_bubble_colors()
            status_html = web_wrapper(
                f"""<div style="margin:4px 26px 10px;color:{bubbles['muted']};font-size:12px;">
                {html.escape(stopped)}</div>"""
            )
            self._append_html_to_active_turn(status_html)
            return
        stream_json = json.dumps(stream_id)
        content_id = json.dumps(f"{stream_id}-content")
        actions_id = json.dumps(f"{stream_id}-actions")
        stopped_json = json.dumps(stopped, ensure_ascii=False)
        muted_json = json.dumps(get_chat_bubble_colors()["muted"])
        self.chat.page().runJavaScript(
            f"""var stream=document.getElementById({stream_json});
var content=document.getElementById({content_id});
var actions=document.getElementById({actions_id});
if(actions){{actions.style.display='none';}}
if(stream){{stream.style.margin='4px 26px 10px 26px';}}
if(content){{
  content.textContent={stopped_json};
  content.style.display='inline-block';
  content.style.padding='2px 4px';
  content.style.background='transparent';
  content.style.border='0';
  content.style.boxShadow='none';
  content.style.color={muted_json};
  content.style.fontSize='12px';
  content.style.whiteSpace='normal';
}}
window.scrollTo(0, document.body.scrollHeight);"""
        )

    def _finalize_active_turn(self, history_count: int) -> None:
        """Drop capped-out DOM turns and align remaining indices with persistence."""
        if not self._active_turn_dom_id:
            return
        self.chat.page().runJavaScript(
            f"""var turns=Array.from(document.querySelectorAll('[data-rag-turn="1"]'));
while(turns.length>{history_count}){{var old=turns.shift();old.remove();}}
turns.forEach(function(turn,index){{turn.dataset.turnIndex=String(index);}});"""
        )

    def _sources_html(self, sources: list[SearchResult]) -> str:
        self._source_paths.clear()
        cards: list[str] = []
        top_score = sources[0].score if sources else 1.0
        for rank, result in enumerate(sources[:10], start=1):
            chunk = result.chunk
            score_pct = min(1.0, result.score / max(top_score, 0.001))
            color = COLORS["accent"] if score_pct > 0.8 else (COLORS["warning"] if score_pct > 0.5 else COLORS["muted"])
            if chunk.source_type == "waveda_help":
                badge_label, badge_color = get_text("badge_waveda_help"), "#103430"
            elif chunk.source_type == "user_tutorial":
                badge_label, badge_color = get_text("badge_team_tutorial"), "#1f472b"
            else:
                badge_label, badge_color = get_text("badge_theory_notes"), "#1f2937"

            # Store source_path for click-to-view, make all sources clickable
            self._source_paths[rank] = chunk.source_path
            source_link = f"<a href=\"#\" onclick=\"console.log('RAGGG_SOURCE:{rank}');return false;\" style='color:{COLORS['accent2']};cursor:pointer;text-decoration:none;'>{html.escape(chunk.relative_path)}</a>"

            cards.append(
                f"""<div id="source-{rank}" style="background:{COLORS['surface2']};border:1px solid {COLORS['border']};border-radius:8px;padding:10px 12px;margin-bottom:8px;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <span style="font-weight:700;color:{COLORS['text']};">[{rank}] {html.escape(chunk.title)}</span>
                    <span style="background:{badge_color};color:{color};border-radius:8px;padding:2px 10px;font-size:11px;font-weight:600;">{badge_label}</span>
                  </div>
                  <div style="color:{COLORS['muted']};font-size:11px;margin-bottom:4px;">{source_link}</div>
                  <div style="color:{color};font-size:11px;">{get_text("match_score")} {score_pct:.1%}</div>
                </div>"""
            )
        return web_wrapper(
            "\n".join(cards),
            ".citation-target { outline:2px solid "
            f"{COLORS['accent2']}; box-shadow:0 0 0 4px rgba(110,174,196,.18); }}"
        )

    def _welcome_html(self, chunk_count: str = "-", model_name: str = "DeepSeek") -> str:
        bubbles = get_chat_bubble_colors()
        examples = [get_text(f"welcome_example_{index}") for index in range(1, 4)]
        example_buttons = []
        for example in examples:
            question_json = json.dumps(example, ensure_ascii=False)
            example_buttons.append(
                f"""<button onclick='console.log("RAGGG_QUICK:" + {question_json})'
                  style="display:block;width:100%;text-align:left;margin:8px 0;padding:11px 14px;
                         border:1px solid {bubbles['border']};border-radius:12px;
                         background:{bubbles['surface2']};color:{bubbles['text']};
                         font-family:inherit;font-size:13px;line-height:1.5;cursor:pointer;"
                  onmouseover="this.style.borderColor='{bubbles['accent']}';this.style.color='{bubbles['accent']}'"
                  onmouseout="this.style.borderColor='{bubbles['border']}';this.style.color='{bubbles['text']}'">{html.escape(example)}</button>"""
            )

        status_parts = []
        if chunk_count != "-":
            status_parts.append(f"{get_text('startup_chunks_label')} {html.escape(chunk_count)}")
        if model_name:
            status_parts.append(f"{get_text('startup_llm_label')} {html.escape(model_name)}")
        status_html = " · ".join(status_parts)

        return web_wrapper(
            f"""<div style="max-width:760px;margin:52px auto 36px auto;padding:0 24px;">
              <div style="padding:22px 24px;border-radius:18px 18px 18px 4px;
                          background:{bubbles['assistant_bg']};border:1px solid {bubbles['assistant_border']};
                          box-shadow:0 14px 42px rgba(80,150,185,.12);color:{bubbles['text']};">
                <div style="font-size:21px;font-weight:700;color:{bubbles['accent']};margin-bottom:12px;">
                  {html.escape(get_welcome_text('welcome_title'))}
                </div>
                <p style="margin:0 0 9px 0;line-height:1.7;">{html.escape(get_welcome_text('welcome_intro'))}</p>
                <p style="margin:0;line-height:1.7;color:{bubbles['muted']};">{html.escape(get_welcome_text('welcome_detail'))}</p>
              </div>
              <div style="margin-top:22px;">
                <div style="font-size:14px;font-weight:700;color:{bubbles['text']};margin-bottom:8px;">
                  {html.escape(get_text('welcome_examples_title'))}
                </div>
                {''.join(example_buttons)}
                <div style="margin-top:10px;text-align:center;color:{bubbles['muted']};font-size:11px;">
                  {html.escape(get_text('welcome_click_hint'))}
                  {(' · ' + status_html) if status_html else ''}
                </div>
              </div>
            </div>"""
        )

    def _empty_sources_html(self, message: str | None = None) -> str:
        if message is None:
            message = get_text("sources_empty")
        return web_wrapper(
            f"""<div style="text-align:center;padding:40px 16px;">
            <div style="color:{COLORS['subtle']};font-size:13px;">{html.escape(message)}</div>
          </div>"""
        )

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
