"""
主题系统 — 浅色/深色双主题，持久化到 config/.env (RAG_THEME=light/dark)
"""
from __future__ import annotations

from pathlib import Path

from raggg.config import config_env_path

THEMES: dict[str, dict] = {
    "light": {
        "colors": {
            "bg": "#eef7fb",
            "surface": "rgba(255, 255, 255, 0.48)",
            "surface2": "rgba(255, 255, 255, 0.68)",
            "surface3": "rgba(255, 255, 255, 0.78)",
            "border": "rgba(255, 255, 255, 0.72)",
            "text": "#10202d",
            "muted": "#587082",
            "subtle": "#7d93a1",
            "accent": "#5f93d6",
            "accent2": "#6eaec4",
            "warning": "#c89032",
            "danger": "#d75959",
            "input": "rgba(255, 255, 255, 0.64)",
        },
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f3e1ea, stop:0.34 #e9ecea, stop:0.66 #c8ecf1, stop:1 #78c2ef)",
        "sidebar_bg": "rgba(255, 255, 255, 0.58)",
        "sidebar_border": "rgba(255, 255, 255, 0.78)",
        "composer_bg": "rgba(232, 248, 255, 0.64)",
        "composer_border": "rgba(255, 255, 255, 0.88)",
        "btn_bg": "rgba(255, 255, 255, 0.56)",
        "btn_hover_bg": "rgba(255, 255, 255, 0.78)",
        "btn_hover_border": "rgba(112, 168, 214, 0.55)",
        "btn_primary_bg": "rgba(154, 209, 247, 0.82)",
        "btn_primary_hover_bg": "rgba(176, 221, 251, 0.96)",
        "btn_primary_text": "#193047",
        "btn_disabled_bg": "rgba(255, 255, 255, 0.36)",
        "mini_pill_bg": "rgba(232, 248, 255, 0.52)",
        "mini_pill_text": "#5b86b5",
        "mini_pill_border": "rgba(255, 255, 255, 0.72)",
        "chat_user_bg": "#eef5fd",
        "chat_user_border": "rgba(165, 202, 228, 0.55)",
        "chat_assistant_bg": "rgba(241, 253, 253, 0.72)",
        "chat_assistant_border": "rgba(131, 202, 190, 0.42)",
    },
    "dark": {
        "colors": {
            "bg": "#0b1119",
            "surface": "rgba(22, 33, 51, 0.58)",
            "surface2": "rgba(28, 42, 62, 0.74)",
            "surface3": "rgba(35, 52, 75, 0.82)",
            "border": "rgba(55, 78, 108, 0.65)",
            "text": "#dce5f0",
            "muted": "#8899b0",
            "subtle": "#5a6d82",
            "accent": "#6db3e8",
            "accent2": "#7dd3fc",
            "warning": "#e2b155",
            "danger": "#f07171",
            "input": "rgba(18, 28, 42, 0.72)",
        },
        "gradient": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1428, stop:0.34 #0f2433, stop:0.66 #0e2d30, stop:1 #0a3048)",
        "sidebar_bg": "rgba(18, 30, 48, 0.72)",
        "sidebar_border": "rgba(45, 65, 92, 0.65)",
        "composer_bg": "rgba(18, 29, 45, 0.78)",
        "composer_border": "rgba(45, 68, 98, 0.70)",
        "btn_bg": "rgba(30, 48, 72, 0.68)",
        "btn_hover_bg": "rgba(40, 62, 92, 0.82)",
        "btn_hover_border": "rgba(80, 130, 190, 0.45)",
        "btn_primary_bg": "rgba(56, 128, 188, 0.75)",
        "btn_primary_hover_bg": "rgba(72, 152, 216, 0.88)",
        "btn_primary_text": "#e8f4ff",
        "btn_disabled_bg": "rgba(22, 36, 56, 0.45)",
        "mini_pill_bg": "rgba(20, 38, 58, 0.65)",
        "mini_pill_text": "#7db8e0",
        "mini_pill_border": "rgba(45, 72, 105, 0.60)",
        "chat_user_bg": "#1c3a5c",
        "chat_user_border": "rgba(85, 155, 230, 0.65)",
        "chat_assistant_bg": "#152636",
        "chat_assistant_border": "rgba(65, 155, 165, 0.60)",
    },
}

_current_theme: str = "light"


def get_theme() -> str:
    return _current_theme


def set_theme(name: str) -> None:
    global _current_theme
    if name in THEMES:
        _current_theme = name
        _save_theme(name)
        apply_application_style()


def get_colors() -> dict:
    return THEMES.get(_current_theme, THEMES["light"])["colors"]


def build_style() -> str:
    t = THEMES.get(_current_theme, THEMES["light"])
    c = t["colors"]
    menu_bg = "#f7fbfd" if _current_theme == "light" else "#23344b"
    menu_selected_bg = "#dcecf8" if _current_theme == "light" else "#324b69"
    menu_selected_text = "#10202d" if _current_theme == "light" else "#f2f7fc"
    menu_disabled_text = "#8da0ad" if _current_theme == "light" else "#71839a"
    menu_separator = "#c5d3dc" if _current_theme == "light" else "#4b6078"
    return f"""
QWidget {{
    background: transparent;
    color: {c["text"]};
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}}
QMenu {{
    background: {menu_bg};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    background: transparent;
    color: {c["text"]};
    border-radius: 5px;
    padding: 6px 28px 6px 10px;
}}
QMenu::item:selected {{
    background: {menu_selected_bg};
    color: {menu_selected_text};
}}
QMenu::item:disabled {{
    color: {menu_disabled_text};
}}
QMenu::separator {{
    background: {menu_separator};
    height: 1px;
    margin: 4px 8px;
}}
QWidget#gradientRoot {{
    background: {t["gradient"]};
}}
QFrame#panel {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 18px;
}}
QFrame#metricCard, QFrame#sourceCard {{
    background: {c["surface2"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
}}
QFrame#sidebar {{
    background: {t["sidebar_bg"]};
    border: 1px solid {t["sidebar_border"]};
    border-radius: 22px;
}}
QFrame#composer {{
    background: {t["composer_bg"]};
    border: 1px solid {t["composer_border"]};
    border-radius: 20px;
}}
QWebEngineView#chatCanvas, QWebEngineView#sourcesCanvas {{
    background: transparent;
    border: 0;
}}
QLabel#title {{
    color: {c["text"]};
    font-size: 24px;
    font-weight: 700;
}}
QLabel#subtitle, QLabel#muted {{
    color: {c["muted"]};
}}
QLabel#section {{
    color: {c["text"]};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#metricLabel {{
    color: {c["muted"]};
    font-size: 12px;
}}
QLabel#metricValue {{
    color: {c["accent"]};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#badge {{
    background: {"#103430" if _current_theme == "light" else "#0d2826"};
    color: {c["accent"]};
    border: 1px solid {"#1f6b5e" if _current_theme == "light" else "#184a42"};
    border-radius: 12px;
    padding: 8px 14px;
    font-weight: 700;
}}
QPushButton {{
    background: {t["btn_bg"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
    padding: 10px 12px;
}}
QPushButton:hover {{
    background: {t["btn_hover_bg"]};
    border-color: {t["btn_hover_border"]};
}}
QPushButton#primary {{
    background: {t["btn_primary_bg"]};
    color: {t["btn_primary_text"]};
    border: 0;
    font-weight: 700;
}}
QPushButton#primary:hover {{
    background: {t["btn_primary_hover_bg"]};
}}
QPushButton#iconButton {{
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 0;
    font-size: 15px;
    font-weight: 700;
}}
QPushButton#sendButton {{
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    border-radius: 16px;
    padding: 0;
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#plusButton {{
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    border-radius: 17px;
    padding: 0;
    font-size: 16px;
}}
QPushButton:disabled {{
    background: {t["btn_disabled_bg"]};
    color: {c["subtle"]};
}}
QLineEdit {{
    background: transparent;
    color: {c["text"]};
    border: 0;
    padding: 9px 8px;
    selection-background-color: {c["accent"]};
}}
QLabel#miniPill {{
    background: {t["mini_pill_bg"]};
    color: {t["mini_pill_text"]};
    border: 1px solid {t["mini_pill_border"]};
    border-radius: 11px;
    padding: 3px 10px;
    font-size: 11px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {"#26364c" if _current_theme == "light" else "#3a5070"};
    border-radius: 5px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QComboBox {{
    background: {c["surface3"]};
    color: {c["text"]};
    border: 1.5px solid {c["subtle"]};
    border-radius: 10px;
    padding: 8px 12px;
}}
QComboBox:hover {{
    border-color: {c["accent"]};
}}
QComboBox::drop-down {{
    border: 0;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {c["surface3"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    outline: none;
    selection-background-color: {c["accent"]};
    selection-color: {"#193047" if _current_theme == "light" else "#e8f4ff"};
}}
QTabWidget::pane {{
    border: 1px solid {c["border"]};
    border-radius: 10px;
    background: {c["surface"]};
}}
QTabBar::tab {{
    background: {c["surface2"]};
    color: {c["muted"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 8px 16px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    background: {c["accent"]};
    color: {"#193047" if _current_theme == "light" else "#e8f4ff"};
    border-color: {c["accent"]};
}}
QTabBar::tab:hover:!selected {{
    color: {c["text"]};
}}
QDialog {{
    background: {c["bg"]};
    color: {c["text"]};
}}
QDialog QLabel {{
    color: {c["text"]};
}}
QDialog QLabel#muted, QDialog QLabel[styleSheet*="muted"] {{
    color: {c["muted"]};
}}
QMessageBox {{
    background: {c["surface2"]};
    color: {c["text"]};
}}
QMessageBox QLabel {{
    color: {c["text"]};
}}
QTextEdit {{
    background: {c["surface2"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
    padding: 10px;
}}
QScrollArea {{
    background: transparent;
    border: 0;
}}"""


def apply_application_style(app=None) -> str:
    """Apply the active theme to every Qt top-level window and popup."""
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    style = build_style()
    if app is not None:
        app.setStyleSheet(style)
    return style


def get_chat_bubble_colors() -> dict:
    """返回聊天气泡颜色，用于生成 HTML 内联样式"""
    t = THEMES.get(_current_theme, THEMES["light"])
    c = t["colors"]
    return {
        "user_bg": t["chat_user_bg"],
        "user_border": t["chat_user_border"],
        "assistant_bg": t["chat_assistant_bg"],
        "assistant_border": t["chat_assistant_border"],
        "text": c["text"],
        "muted": c["muted"],
        "accent": c["accent"],
        "accent2": c["accent2"],
        "warning": c["warning"],
        "surface2": c["surface2"],
        "border": c["border"],
        "subtle": c["subtle"],
    }


def _theme_env_path() -> Path:
    return config_env_path()


def _load_theme() -> str:
    env_path = _theme_env_path()
    if not env_path.exists():
        return "light"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("RAG_THEME="):
            name = line.split("=", 1)[1].strip().strip('"').strip("'")
            if name in THEMES:
                return name
    return "light"


def _save_theme(name: str) -> None:
    env_path = _theme_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith("RAG_THEME="):
            new_lines.append(f"RAG_THEME={name}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"RAG_THEME={name}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── 模块导入时自动加载 ──
_current_theme = _load_theme()
