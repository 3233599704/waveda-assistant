from __future__ import annotations

import html
import json
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QMessageBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from raggg.desktop.rendering import markdown_to_html, web_wrapper
from raggg.i18n import get_text
from raggg.theme import get_chat_bubble_colors, get_colors, get_theme


COLORS = get_colors()
SESSION_SCROLLBAR_COLORS = {
    "light": ("#b7bdc5", "#a2a9b2"),
    "dark": ("#65707c", "#7a8591"),
}
QUESTION_CONTEXT_MENU_COLORS = {
    "light": {
        "background": "#f5f6f8",
        "text": "#26323d",
        "selected": "#e2e8ef",
        "disabled": "#9aa2aa",
        "border": "#cfd4da",
    },
    "dark": {
        "background": "#1b2635",
        "text": "#e2e8f0",
        "selected": "#2f4258",
        "disabled": "#77869a",
        "border": "#405069",
    },
}


class SessionListItemWidget(QWidget):
    activated = Signal(str)
    rename_requested = Signal(str)
    pin_requested = Signal(str, bool)
    delete_requested = Signal(str)

    def __init__(
        self,
        session_id: str,
        title: str,
        is_pinned: bool,
        can_delete: bool,
        is_current: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sessionListItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.session_id = session_id
        self.is_pinned = is_pinned
        self.can_delete = can_delete
        self.is_current = is_current
        self._menu_open = False
        self._full_title = title

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 4, 2)
        self.pin_label = QLabel("📌" if is_pinned else "")
        self.pin_label.setFixedWidth(18 if is_pinned else 0)
        layout.addWidget(self.pin_label)
        self.title_label = QLabel()
        self.title_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.title_label.installEventFilter(self)
        self.title_label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        self.title_label.setToolTip(title)
        layout.addWidget(self.title_label, stretch=1)

        self.actions_button = QPushButton("⋯")
        self.actions_button.setObjectName("sessionActionsButton")
        self.actions_button.setFixedSize(26, 26)
        self.actions_button.setCursor(Qt.PointingHandCursor)
        self.actions_button.setStyleSheet(
            "QPushButton#sessionActionsButton {"
            "background:transparent;border:none;border-radius:13px;padding:0;"
            f"color:{COLORS['muted']};font-size:18px;font-weight:600;"
            "}"
            "QPushButton#sessionActionsButton:hover {"
            f"background:{COLORS['surface2']};color:{COLORS['text']};"
            "}"
        )
        self.actions_button.hide()
        self.actions_button.clicked.connect(self._show_actions_menu)
        layout.addWidget(self.actions_button)
        self._apply_row_style(False)

    def enterEvent(self, event) -> None:
        self.actions_button.show()
        self._apply_row_style(True)

    def leaveEvent(self, event) -> None:
        if not self._menu_open:
            self.actions_button.hide()
            self._apply_row_style(False)

    def _apply_row_style(self, hovered: bool) -> None:
        background = COLORS["surface2"] if hovered or self.is_current else "transparent"
        title_color = COLORS["accent"] if self.is_current else COLORS["muted"]
        self.setStyleSheet(
            "QWidget#sessionListItem {"
            f"background:{background};border-radius:8px;"
            "}"
        )
        self.title_label.setStyleSheet(f"color:{title_color};")

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is getattr(self, "title_label", None)
            and event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
        ):
            self.activated.emit(self.session_id)
            return True
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.session_id)
        super().mouseReleaseEvent(event)

    def _build_actions_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setWindowFlag(Qt.FramelessWindowHint, True)
        menu.setStyleSheet(
            "QMenu {"
            f"background:{COLORS['surface3']};"
            f"color:{COLORS['text']};"
            f"border:1px solid {COLORS['border']};"
            "border-radius:10px;padding:5px;"
            "}"
            "QMenu::item {"
            "background:transparent;border-radius:6px;padding:7px 24px;"
            "}"
            "QMenu::item:selected {"
            f"background:{COLORS['surface2']};color:{COLORS['text']};"
            "}"
        )
        rename_action = menu.addAction(get_text("session_rename"))
        rename_action.setObjectName("sessionRenameAction")
        pin_action = menu.addAction(
            get_text("session_unpin") if self.is_pinned else get_text("session_pin")
        )
        pin_action.setObjectName("sessionPinAction")
        delete_action = QWidgetAction(menu)
        delete_action.setObjectName("sessionDeleteAction")
        delete_action.setText(get_text("session_delete_menu"))
        delete_button = QPushButton(get_text("session_delete_menu"))
        delete_button.setObjectName("sessionDeleteMenuButton")
        delete_button.setFlat(True)
        delete_button.setStyleSheet(
            "QPushButton#sessionDeleteMenuButton {"
            "background:transparent;border:none;border-radius:6px;"
            f"text-align:left;padding:7px 24px;color:{COLORS['danger']};"
            "}"
            "QPushButton#sessionDeleteMenuButton:hover {"
            f"background:{COLORS['surface2']};"
            "}"
            "QPushButton#sessionDeleteMenuButton:disabled {"
            f"background:transparent;color:{COLORS['subtle']};"
            "}"
        )
        delete_button.setEnabled(self.can_delete)
        delete_action.setEnabled(self.can_delete)
        delete_button.clicked.connect(delete_action.trigger)
        delete_action.setDefaultWidget(delete_button)
        menu.addAction(delete_action)

        rename_action.triggered.connect(
            lambda: self.rename_requested.emit(self.session_id)
        )
        pin_action.triggered.connect(
            lambda: self.pin_requested.emit(self.session_id, not self.is_pinned)
        )
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.session_id)
        )
        delete_action.triggered.connect(menu.close)
        return menu

    def _show_actions_menu(self) -> None:
        menu = self._build_actions_menu()
        self._menu_open = True
        menu.aboutToHide.connect(self._on_menu_hidden)
        menu.exec(
            self.actions_button.mapToGlobal(self.actions_button.rect().bottomLeft())
        )

    def _on_menu_hidden(self) -> None:
        self._menu_open = False
        if not self.underMouse():
            self.actions_button.hide()
            self._apply_row_style(False)

    def set_current(self, is_current: bool) -> None:
        self.is_current = is_current
        self._apply_row_style(self.underMouse() or self._menu_open)

    def resizeEvent(self, event) -> None:
        available = max(0, self.title_label.width() - 4)
        self.title_label.setText(
            self.title_label.fontMetrics().elidedText(
                self._full_title,
                Qt.ElideRight,
                available,
            )
        )
        super().resizeEvent(event)


class SessionPanel(QFrame):
    """Dedicated widget type for the desktop session sidebar."""

    new_requested = Signal()
    switched = Signal(int)
    rename_requested = Signal(str)
    pin_requested = Signal(str, bool)
    delete_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(get_text("session_panel_title"))
        title.setStyleSheet(
            f"color:{COLORS['text']};font-weight:700;font-size:12px;"
        )
        header.addWidget(title, stretch=1)
        new_button = QPushButton("+")
        new_button.setObjectName("iconButton")
        new_button.setToolTip(f"{get_text('session_new')} (Ctrl+N)")
        new_button.clicked.connect(self.new_requested.emit)
        header.addWidget(new_button)
        layout.addLayout(header)

        scrollbar_handle, scrollbar_hover = SESSION_SCROLLBAR_COLORS.get(
            get_theme(),
            SESSION_SCROLLBAR_COLORS["light"],
        )
        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setStyleSheet(
            "QListWidget#sessionList { background:transparent;border:0; }"
            "QListWidget#sessionList::item { padding:0;margin:1px 0; }"
            f"QListWidget#sessionList::item:selected {{ color:{COLORS['accent']};font-weight:600; }}"
            "QListWidget#sessionList QScrollBar:vertical { background:transparent;width:10px; }"
            f"QListWidget#sessionList QScrollBar::handle:vertical {{ background:{scrollbar_handle};border-radius:5px; }}"
            f"QListWidget#sessionList QScrollBar::handle:vertical:hover {{ background:{scrollbar_hover}; }}"
            "QListWidget#sessionList QScrollBar::add-line:vertical,"
            "QListWidget#sessionList QScrollBar::sub-line:vertical { height:0; }"
        )
        self.session_list.currentRowChanged.connect(self.switched.emit)
        layout.addWidget(self.session_list, stretch=1)

    def set_sessions(
        self,
        sessions: Sequence[object],
        current_id: str,
    ) -> None:
        self.session_list.blockSignals(True)
        self.session_list.clear()
        can_delete = len(sessions) > 1
        title_counts: dict[str, int] = {}
        for session in sessions:
            title_counts[session.title] = title_counts.get(session.title, 0) + 1
        for session in sessions:
            display_title = session.title
            if title_counts[session.title] > 1:
                time_label = session.created_at[11:16] if len(session.created_at) >= 16 else ""
                display_title = f"{session.title} · {time_label or session.id[-4:]}"
            item = QListWidgetItem()
            item.setData(Qt.UserRole, session.id)
            row = SessionListItemWidget(
                session.id,
                display_title,
                bool(session.pinned_at),
                can_delete,
                is_current=session.id == current_id,
                parent=self.session_list,
            )
            row.rename_requested.connect(self.rename_requested.emit)
            row.pin_requested.connect(self.pin_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            row.activated.connect(self._select_session)
            item.setSizeHint(QSize(0, 34))
            self.session_list.addItem(item)
            self.session_list.setItemWidget(item, row)
            if session.id == current_id:
                self.session_list.setCurrentItem(item)
        self.session_list.blockSignals(False)

    def _select_session(self, session_id: str) -> None:
        for row in range(self.session_list.count()):
            item = self.session_list.item(row)
            if item.data(Qt.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                for index in range(self.session_list.count()):
                    row_widget = self.session_list.itemWidget(
                        self.session_list.item(index)
                    )
                    row_widget.set_current(index == row)
                return


class SessionsMixin:
    def _clear_sources_for_session_change(self) -> None:
        self._source_paths.clear()
        self.sources.setHtml(
            self._empty_sources_html(get_text("sources_empty"))
        )

    def _build_session_panel(self) -> QFrame:
        panel = SessionPanel(self)
        self.session_list = panel.session_list
        panel.new_requested.connect(self._new_session)
        panel.switched.connect(self._on_session_switched)
        panel.rename_requested.connect(self._rename_session)
        panel.pin_requested.connect(self._set_session_pinned)
        panel.delete_requested.connect(self._delete_session)
        return panel

    def _refresh_session_list(self) -> None:
        self.session_panel.set_sessions(
            self._session_manager.sorted_sessions(),
            self._session_manager.current_id,
        )

    def _rename_session(self, session_id: str) -> None:
        session = self._session_manager.sessions.get(session_id)
        if session is None:
            self._refresh_session_list()
            return
        title, accepted = QInputDialog.getText(
            self,
            get_text("session_rename"),
            get_text("session_rename"),
            text=session.title,
        )
        if not accepted:
            return
        if not title.strip():
            QMessageBox.information(
                self,
                get_text("session_rename"),
                get_text("session_invalid_title"),
            )
            return
        try:
            self._session_manager.rename(session_id, title)
        except OSError as error:
            QMessageBox.warning(self, get_text("session_save_error"), str(error))
        self._refresh_session_list()

    def _set_session_pinned(self, session_id: str, pinned: bool) -> None:
        try:
            self._session_manager.set_pinned(session_id, pinned)
        except OSError as error:
            QMessageBox.warning(self, get_text("session_save_error"), str(error))
        self._refresh_session_list()

    def _new_session(self) -> None:
        self._session_manager.new_session()
        self._conversation_history = []
        self._selected_turn_indices.clear()
        self._active_turn_dom_id = ""
        self._clear_sources_for_session_change()
        self.chat.setHtml(
            self._welcome_html(
                chunk_count=(
                    str(len(self.pipeline.store.chunks)) if self.pipeline else "-"
                ),
                model_name=(
                    self.settings.llm_model
                    if self.settings.llm_api_key
                    else get_text("model_local")
                ),
            )
        )
        self._refresh_session_list()

    def _on_session_switched(self, _row: int) -> None:
        item = self.session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.UserRole)
        if session_id == self._session_manager.current_id:
            return
        if self._session_manager.switch_to(session_id) is None:
            return
        self._show_current_session()

    def _show_current_session(self) -> None:
        history = self._session_manager.get_history()
        self._conversation_history = history
        self._selected_turn_indices.clear()
        self._active_turn_dom_id = ""
        self._clear_sources_for_session_change()
        if history:
            self._show_session_content(history)
        else:
            self.chat.setHtml(self._welcome_html())

    def _show_session_content(self, history: list[tuple[str, str]]) -> None:
        bubbles = get_chat_bubble_colors()
        parts = []
        self._selected_turn_indices.clear()
        self._active_turn_dom_id = ""
        for turn_index, (question, answer) in enumerate(history):
            parts.append(
                f"<section data-rag-turn='1' data-turn-index='{turn_index}' "
                "style='margin:4px 10px;padding:2px;border-radius:12px;"
                "outline:2px solid transparent;'>"
            )
            parts.append(
                "<div style='margin:16px 26px;display:flex;justify-content:flex-end;'>"
                f"<div style='max-width:76%;padding:12px 15px;border-radius:18px;"
                f"background:{bubbles['user_bg']};color:{bubbles['text']};'>"
                f"{html.escape(question)}</div></div>"
            )
            parts.append(
                "<div class='answer-block' style='margin:16px 26px;display:flex;justify-content:flex-start;'>"
                f"<div style='max-width:82%;'>"
                f"<div style='padding:15px 17px;border-radius:18px 18px 18px 4px;"
                f"background:{bubbles['assistant_bg']};border:1px solid {bubbles['assistant_border']};"
                f"box-shadow:0 14px 42px rgba(80,150,185,.12);color:{bubbles['text']};line-height:1.6;'>"
                f"{markdown_to_html(answer, citations_clickable=False)}</div>"
                f"<div class='answer-actions' style='display:flex;align-items:center;gap:6px;margin-left:2px;'>"
                f"<button onclick=\"var p=this.parentElement.previousElementSibling;var t=document.createElement('textarea');t.value=p.innerText;document.body.appendChild(t);t.select();document.execCommand('copy');document.body.removeChild(t);var s=this.innerHTML;this.innerHTML='{html.escape(get_text('btn_copied'))}';setTimeout(function(){{this.innerHTML=s;}}.bind(this),1000)\""
                f" style='background:transparent;color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:8px;padding:2px 9px;font-size:11px;cursor:pointer;'"
                f" onmouseover=\"this.style.color='{bubbles['accent']}';this.style.borderColor='{bubbles['accent']}'\" onmouseout=\"this.style.color='{bubbles['muted']}';this.style.borderColor='{bubbles['border']}'\">{html.escape(get_text('btn_copy'))}</button>"
                f"<button onclick=\"console.log('RAGGG_FAV:{turn_index}');this.innerHTML='{html.escape(get_text('btn_faved'))}';this.style.color='{bubbles['accent']}';setTimeout(function(){{this.innerHTML='{html.escape(get_text('btn_fav'))}';this.style.color='{bubbles['muted']}'}}.bind(this),1500)\""
                f" style='background:transparent;color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:8px;padding:2px 9px;font-size:11px;cursor:pointer;'"
                f" onmouseover=\"this.style.color='{bubbles['accent']}';this.style.borderColor='{bubbles['accent']}'\" onmouseout=\"this.style.color='{bubbles['muted']}';this.style.borderColor='{bubbles['border']}'\">{html.escape(get_text('btn_fav'))}</button>"
                f"<button onclick=\"console.log('RAGGG_FIX:{turn_index}')\""
                f" style='background:transparent;color:{bubbles['muted']};border:1px solid {bubbles['border']};border-radius:8px;padding:2px 9px;font-size:11px;cursor:pointer;'"
                f" onmouseover=\"this.style.color='{bubbles['accent']}';this.style.borderColor='{bubbles['accent']}'\" onmouseout=\"this.style.color='{bubbles['muted']}';this.style.borderColor='{bubbles['border']}'\">{html.escape(get_text('btn_fix'))}</button>"
                f"</div>"
                f"</div></div>"
            )
            parts.append("</section>")
        # 填充 turn_qa_pairs 以便纠错/收藏按钮能定位到正确的问答对
        if hasattr(self, "_turn_qa_pairs"):
            for turn_index, (question, answer) in enumerate(history):
                self._turn_qa_pairs[turn_index] = (question, answer)
        self.chat.setHtml(web_wrapper("\n".join(parts)))

    def _create_question_context_menu(self) -> QMenu:
        menu = self.question.createStandardContextMenu()
        menu.setObjectName("questionContextMenu")
        colors = QUESTION_CONTEXT_MENU_COLORS.get(
            get_theme(),
            QUESTION_CONTEXT_MENU_COLORS["light"],
        )
        menu.setStyleSheet(
            "QMenu#questionContextMenu {"
            f"background:{colors['background']};color:{colors['text']};"
            f"border:1px solid {colors['border']};border-radius:8px;padding:5px;"
            "}"
            "QMenu#questionContextMenu::item {"
            f"background:transparent;color:{colors['text']};"
            "border-radius:5px;padding:6px 28px 6px 24px;"
            "}"
            "QMenu#questionContextMenu::item:selected {"
            f"background:{colors['selected']};color:{colors['text']};"
            "}"
            "QMenu#questionContextMenu::item:disabled {"
            f"color:{colors['disabled']};"
            "}"
            "QMenu#questionContextMenu::separator {"
            f"background:{colors['border']};height:1px;margin:4px 8px;"
            "}"
        )
        return menu

    def _show_question_context_menu(self, pos) -> None:
        menu = self._create_question_context_menu()
        menu.exec(self.question.mapToGlobal(pos))
        menu.deleteLater()

    def _show_chat_context_menu(self, pos) -> None:
        """Replace the browser menu with Q&A turn actions."""
        if self.is_busy:
            return
        global_pos = self.chat.mapToGlobal(pos)
        script = (
            "(function(){"
            f"var node=document.elementFromPoint({pos.x()},{pos.y()});"
            "var turn=node&&node.closest('[data-rag-turn=\"1\"]');"
            "return JSON.stringify({"
            "turnIndex:turn?Number(turn.dataset.turnIndex):-1,"
            "selectedText:String(window.getSelection()||'')"
            "});"
            "})()"
        )

        def show_for_turn(value) -> None:
            try:
                payload = json.loads(value) if isinstance(value, str) else value
                turn_index = int(payload.get("turnIndex", -1))
                selected_text = str(payload.get("selectedText", "")).strip()
            except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                return
            if not 0 <= turn_index < len(self._session_manager.get_history()):
                return
            QTimer.singleShot(
                0,
                lambda: self._popup_chat_turn_menu(
                    turn_index,
                    selected_text,
                    global_pos,
                ),
            )

        self.chat.page().runJavaScript(script, show_for_turn)

    def _popup_chat_turn_menu(
        self,
        turn_index: int,
        selected_text: str,
        global_pos,
    ) -> None:
        previous_menu = getattr(self, "_active_chat_turn_menu", None)
        if previous_menu is not None:
            previous_menu.close()
        menu = self._build_chat_turn_menu(turn_index, selected_text)
        self._active_chat_turn_menu = menu

        def release_menu() -> None:
            if getattr(self, "_active_chat_turn_menu", None) is menu:
                self._active_chat_turn_menu = None
            menu.deleteLater()

        menu.aboutToHide.connect(release_menu)
        menu.popup(global_pos)

    def _build_chat_turn_menu(
        self, turn_index: int, selected_text: str = ""
    ) -> QMenu:
        menu = QMenu(self.chat)
        menu.setObjectName("chatTurnMenu")
        menu.setStyleSheet(
            f"QMenu#chatTurnMenu{{background:{COLORS['surface3']};color:{COLORS['text']};"
            f"border:1px solid {COLORS['border']};padding:6px;}}"
            f"QMenu#chatTurnMenu::item{{padding:7px 18px;border-radius:5px;}}"
            f"QMenu#chatTurnMenu::item:selected{{background:{COLORS['surface2']};"
            f"color:{COLORS['accent']};}}"
        )

        if selected_text:
            copy_selection_action = menu.addAction(get_text("chat_copy_selection"))
            copy_selection_action.setObjectName("chatCopySelectionAction")
            copy_selection_action.triggered.connect(
                lambda: QApplication.clipboard().setText(selected_text)
            )

        copy_question_action = menu.addAction(get_text("chat_copy_question"))
        copy_question_action.setObjectName("chatCopyQuestionAction")
        copy_question_action.triggered.connect(
            lambda: self._copy_chat_question(turn_index)
        )
        menu.addSeparator()

        selected = turn_index in self._selected_turn_indices
        select_action = menu.addAction(
            get_text("chat_unselect_turn") if selected else get_text("chat_select_turn")
        )
        select_action.setObjectName("chatSelectTurnAction")
        select_action.triggered.connect(
            lambda: self._set_chat_turn_selected(turn_index, not selected)
        )

        delete_action = menu.addAction(get_text("chat_delete_turn"))
        delete_action.setObjectName("chatDeleteTurnAction")
        delete_action.triggered.connect(lambda: self._delete_chat_turns([turn_index]))

        if self._selected_turn_indices:
            menu.addSeparator()
            count = len(self._selected_turn_indices)
            delete_selected = menu.addAction(
                get_text("chat_delete_selected").replace("{count}", str(count))
            )
            delete_selected.setObjectName("chatDeleteSelectedAction")
            delete_selected.triggered.connect(
                lambda: self._delete_chat_turns(sorted(self._selected_turn_indices))
            )
            clear_action = menu.addAction(get_text("chat_clear_selection"))
            clear_action.setObjectName("chatClearSelectionAction")
            clear_action.triggered.connect(self._clear_chat_turn_selection)
        return menu

    def _copy_chat_question(self, turn_index: int) -> None:
        history = self._session_manager.get_history()
        if 0 <= turn_index < len(history):
            QApplication.clipboard().setText(history[turn_index][0])

    def _set_chat_turn_selected(self, turn_index: int, selected: bool) -> None:
        if selected:
            self._selected_turn_indices.add(turn_index)
        else:
            self._selected_turn_indices.discard(turn_index)
        outline = COLORS["accent"] if selected else "transparent"
        background = COLORS["surface2"] if selected else "transparent"
        self.chat.page().runJavaScript(
            f"""var turn=document.querySelector('[data-rag-turn="1"][data-turn-index="{turn_index}"]');
if(turn){{turn.style.outline='2px solid {outline}';turn.style.background='{background}';}}"""
        )

    def _clear_chat_turn_selection(self) -> None:
        self._selected_turn_indices.clear()
        if not hasattr(self, "chat"):
            return
        self.chat.page().runJavaScript(
            "document.querySelectorAll('[data-rag-turn=\"1\"]').forEach(function(turn){"
            "turn.style.outline='2px solid transparent';"
            "turn.style.background='transparent';"
            "});"
        )

    def _delete_chat_turns(self, turn_indices: list[int]) -> None:
        history = self._session_manager.get_history()
        valid = sorted({index for index in turn_indices if 0 <= index < len(history)})
        if not valid:
            return
        message_key = "chat_delete_one_confirm" if len(valid) == 1 else "chat_delete_many_confirm"
        message = get_text(message_key).replace("{count}", str(len(valid)))
        reply = QMessageBox.question(
            self,
            get_text("chat_delete_confirm_title"),
            message,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._session_manager.delete_messages(valid)
        except OSError as error:
            QMessageBox.warning(self, get_text("session_save_error"), str(error))
            return

        history = self._session_manager.get_history()
        self._conversation_history = history
        self._last_qa = history[-1] if history else ("", "")
        self._selected_turn_indices.clear()
        self._active_turn_dom_id = ""
        self._clear_sources_for_session_change()
        if history:
            self._show_session_content(history)
        else:
            self.chat.setHtml(self._welcome_html())
        self._refresh_session_list()

    def _delete_session(self, session_id: str) -> None:
        session = self._session_manager.sessions.get(session_id)
        if session is None:
            self._refresh_session_list()
            return
        reply = QMessageBox.question(
            self,
            get_text("session_delete_confirm"),
            get_text("session_delete_msg").replace("{name}", session.title),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        deleting_current = session_id == self._session_manager.current_id
        try:
            deleted = self._session_manager.delete(session_id)
        except OSError as error:
            QMessageBox.warning(self, get_text("session_save_error"), str(error))
            return
        if deleted and deleting_current:
            self._show_current_session()
        self._refresh_session_list()

    def _toggle_session_panel(self) -> None:
        self.session_panel.setVisible(not self.session_panel.isVisible())
