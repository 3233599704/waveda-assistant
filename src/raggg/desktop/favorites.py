from __future__ import annotations

import re

import html
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from raggg.desktop.rendering import markdown_to_html
from raggg.i18n import get_text
from raggg.theme import get_colors


COLORS = get_colors()

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
        all(keyword in searchable_text for keyword in keywords)
        or query_compact in searchable_compact
    )


def favorite_score(favorite: dict, query: str) -> int:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return 0
    keywords = normalized_query.split()
    searchable_text = str(favorite.get("question", "")).casefold()
    score = sum(searchable_text.count(keyword) for keyword in keywords)
    query_compact = normalize_favorite_search_text(query)
    searchable_compact = normalize_favorite_search_text(searchable_text)
    if query_compact:
        score += searchable_compact.count(query_compact) * 2
    return score


def highlight_keywords(html_text: str, query: str) -> str:
    if not query.strip():
        return html_text
    result = html_text
    for keyword in query.strip().split():
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        result = pattern.sub(
            '<mark style="background:#5f93d6;color:#fff;padding:1px 3px;'
            f'border-radius:3px;">{keyword}</mark>',
            result,
        )
    return result


class FavoritesMixin:
    """Favorite behavior boundary used by the desktop coordinator."""

    def _load_favs(self) -> list:
        if not self._fav_file.exists():
            return []
        try:
            with self._fav_file.open("r", encoding="utf-8") as file:
                value = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def _save_favs(self, favorites: list) -> None:
        self._fav_file.parent.mkdir(parents=True, exist_ok=True)
        with self._fav_file.open("w", encoding="utf-8") as file:
            json.dump(favorites, file, ensure_ascii=False, indent=2)

    def _open_favorites(self) -> None:
        favorites = self._load_favs()
        if not favorites:
            QMessageBox.information(
                self,
                get_text("favorites_title"),
                get_text("msg_favorites_empty"),
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(get_text("favorites_title"))
        dialog.resize(780, 600)
        dialog.setStyleSheet(f"QDialog {{ background: {COLORS['bg']}; }}")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_icon = QLabel("⌕")
        search_icon.setStyleSheet(f"color:{COLORS['muted']};font-size:14px;")
        search_row.addWidget(search_icon)
        search_input = QLineEdit()
        search_input.setObjectName("favoritesSearchInput")
        search_input.setPlaceholderText(get_text("favorites_search_placeholder"))
        search_input.setStyleSheet(
            f"QLineEdit {{ background:{COLORS['surface3']};color:{COLORS['text']};"
            f"border:1px solid {COLORS['border']};border-radius:12px;"
            "padding:10px 14px;font-size:13px;}"
            f"QLineEdit:focus {{ border-color: {COLORS['accent']}; }}"
        )
        search_row.addWidget(search_input, stretch=1)
        layout.addLayout(search_row)

        count_label = QLabel(f"{len(favorites)} 条收藏")
        count_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
        layout.addWidget(count_label)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet(f"background: transparent;")
        cards_layout = QVBoxLayout(scroll_widget)
        cards_layout.setSpacing(8)
        card_items: list[tuple[dict, QFrame, QWidget, QLabel, QTextEdit]] = []

        for reverse_index, favorite in enumerate(reversed(favorites)):
            stored_index = len(favorites) - reverse_index - 1
            card = QFrame()
            card.setObjectName("metricCard")
            card.setStyleSheet(
                f"QFrame#metricCard {{"
                f"background:{COLORS['surface3']};"
                f"border:1px solid {COLORS['border']};"
                f"border-radius:12px; }}"
            )
            card_layout = QVBoxLayout(card)
            header = QHBoxLayout()
            question = QLabel(html.escape(str(favorite.get("question", ""))[:80]))
            question.setStyleSheet(f"color:{COLORS['text']};font-size:13px;")
            header.addWidget(question, stretch=1)
            time_label = QLabel(str(favorite.get("time", "")))
            time_label.setStyleSheet(f"color:{COLORS['muted']};font-size:11px;")
            header.addWidget(time_label)
            arrow = QLabel("▸")
            arrow.setStyleSheet(f"color:{COLORS['muted']};font-size:14px;")
            header.addWidget(arrow)
            delete_button = QPushButton("×")
            delete_button.setFixedSize(24, 24)
            delete_button.setCursor(Qt.PointingHandCursor)
            delete_button.setStyleSheet(
                f"QPushButton {{ background:transparent;color:{COLORS['muted']};"
                f"border:none;font-size:16px;font-weight:700; }}"
                f"QPushButton:hover {{ color:{COLORS['danger']}; }}"
            )
            delete_button.clicked.connect(
                lambda _checked=False, index=stored_index: self._do_fav_del(
                    index,
                    dialog,
                )
            )
            header.addWidget(delete_button)
            card_layout.addLayout(header)

            detail = QWidget()
            detail.setStyleSheet("background: transparent;")
            detail_layout = QVBoxLayout(detail)
            full_question = QLabel(
                f"<b style='color:{COLORS['accent']};'>Q:</b> "
                f"<span style='color:{COLORS['text']};'>{html.escape(str(favorite.get('question', '')))}</span>"
            )
            full_question.setWordWrap(True)
            detail_layout.addWidget(full_question)
            answer = QTextEdit()
            answer.setReadOnly(True)
            answer.setMaximumHeight(300)
            answer.setStyleSheet(
                f"QTextEdit {{ background:{COLORS['surface3']};color:{COLORS['text']};"
                f"border:1px solid {COLORS['border']};border-radius:8px;"
                f"padding:10px;font-size:13px; }}"
            )
            answer.setHtml(markdown_to_html(str(favorite.get("answer", ""))))
            detail_layout.addWidget(answer)
            detail.hide()
            card_layout.addWidget(detail)

            def toggle(_event=None, panel=detail, indicator=arrow) -> None:
                panel.setVisible(not panel.isVisible())
                indicator.setText("▾" if panel.isVisible() else "▸")

            card.mousePressEvent = toggle
            cards_layout.addWidget(card)
            card_items.append((favorite, card, detail, arrow, answer))

        no_results = QLabel(get_text("favorites_no_results"))
        no_results.setObjectName("favoritesNoResults")
        no_results.setAlignment(Qt.AlignCenter)
        no_results.setStyleSheet(f"color:{COLORS['muted']};font-size:13px;padding:20px;")
        no_results.hide()
        cards_layout.addWidget(no_results)
        cards_layout.addStretch(1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(scroll_widget)
        area.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {COLORS['surface']}; width: 8px; border-radius: 4px; }}"
            f"QScrollBar::handle:vertical {{ background: {COLORS['muted']}; border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        layout.addWidget(area, stretch=1)

        def filter_cards(query: str) -> None:
            matches = 0
            for favorite, card, detail, arrow, answer in card_items:
                matched = favorite_matches(favorite, query)
                card.setVisible(matched)
                if not query.strip():
                    detail.hide()
                    arrow.setText("▸")
                elif matched:
                    detail.show()
                    arrow.setText("▾")
                    rendered = markdown_to_html(str(favorite.get("answer", "")))
                    answer.setHtml(highlight_keywords(rendered, query))
                matches += int(matched)
            no_results.setVisible(matches == 0)
            count_label.setText(f"{matches}/{len(favorites)} 条匹配")

        search_input.textChanged.connect(filter_cards)
        dialog.exec()

    def _do_fav_del(self, index: int, dialog: QDialog) -> None:
        favorites = self._load_favs()
        if 0 <= index < len(favorites):
            del favorites[index]
            self._save_favs(favorites)
        dialog.accept()
        self._open_favorites()
