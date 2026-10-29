from __future__ import annotations

import html
import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCloseEvent, QShowEvent
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from raggg.i18n import get_text
from raggg.theme import get_colors

COLORS = get_colors()

_BTN_BASE = (
    "QPushButton {{ border-radius: 6px; padding: 6px 16px; font-weight: 600; "
    "font-size: 12px; cursor: pointer; }}"
)
_BTN_OUTLINE = (
    _BTN_BASE
    + "QPushButton {{ background: rgba(128,128,128,0.12); color: {c}; "
    + "border: 1.5px solid {c}; }}"
    + "QPushButton:hover {{ background: {c}; color: #fff; }}"
)
_BTN_SOLID = (
    _BTN_BASE
    + "QPushButton {{ background: {c}; color: #fff; border: none; }}"
    + "QPushButton:hover {{ background: {h}; }}"
)


class SourceViewer(QDialog):
    """Preview and edit a source document while retaining its file identity."""

    knowledge_changed = Signal()

    def __init__(
        self,
        title: str,
        html_content: str,
        parent: QWidget | None = None,
        *,
        file_path: Path | None = None,
        preview_renderer: Callable[[str], str] | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self._read_only = read_only
        self._file_path = file_path.resolve() if file_path else None
        self._preview_renderer = preview_renderer
        self._html_content = html_content
        self._raw_text = ""
        self._dirty = False
        self._loaded_mtime_ns: int | None = None
        if self._file_path and self._file_path.exists():
            try:
                self._raw_text = self._file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self._raw_text = self._file_path.read_text(
                    encoding="utf-8", errors="ignore"
                )
            self._loaded_mtime_ns = self._file_path.stat().st_mtime_ns

        self.setWindowTitle(f"{title} - {get_text('source_viewer_title')}")
        self.resize(1000, 720)
        self.setMinimumSize(700, 500)
        self.setAttribute(Qt.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 10, 12, 8)
        toolbar.setSpacing(8)

        self._mode_label = QLabel(get_text("source_viewer_preview"))
        self._mode_label.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: 600; font-size: 12px;"
        )
        toolbar.addWidget(self._mode_label)

        self._edit_btn = QPushButton(get_text("source_viewer_edit"))
        self._edit_btn.setObjectName("sourceViewerModeButton")
        self._edit_btn.setStyleSheet(_BTN_OUTLINE.format(c=COLORS["accent2"]))
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.setEnabled(self._file_path is not None and not self._read_only)
        self._edit_btn.setVisible(not self._read_only)
        self._edit_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self._edit_btn)

        self._save_btn = QPushButton(get_text("source_viewer_save"))
        self._save_btn.setObjectName("sourceViewerSaveButton")
        self._save_btn.setStyleSheet(
            _BTN_SOLID.format(c=COLORS["accent"], h=COLORS["accent2"])
        )
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.clicked.connect(self._save_and_switch)
        self._save_btn.setVisible(False)
        toolbar.addWidget(self._save_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(12, 0, 12, 8)
        path_row.setSpacing(8)
        path_label = QLabel(get_text("source_viewer_path_label"))
        path_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 11px;")
        path_row.addWidget(path_label)
        path_text = (
            str(self._file_path)
            if self._file_path
            else get_text("source_viewer_no_path")
        )
        self.path_edit = QLineEdit(path_text)
        self.path_edit.setObjectName("sourceViewerPath")
        self.path_edit.setReadOnly(True)
        self.path_edit.setToolTip(path_text)
        self.path_edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {COLORS['muted']}; "
            "border: none; padding: 2px; font-size: 11px; }}"
        )
        path_row.addWidget(self.path_edit, stretch=1)
        layout.addLayout(path_row)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background: {COLORS['bg']};")

        self.viewer = QWebEngineView()
        self.viewer.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessFileUrls, True
        )
        suffix = self._file_path.suffix.lower() if self._file_path else ""
        preview_background = "#ffffff" if suffix in {".html", ".htm"} else COLORS["bg"]
        self.viewer.page().setBackgroundColor(QColor(preview_background))
        self._stack.addWidget(self.viewer)
        self._set_preview_html(html_content)
        self._initial_preview_refresh_pending = True

        self.editor = QTextEdit()
        self.editor.setPlainText(self._raw_text)
        self.editor.document().setModified(False)
        self.editor.textChanged.connect(self._mark_editor_modified)
        self.editor.setStyleSheet(
            f"QTextEdit {{ background: {COLORS['surface3']}; color: {COLORS['text']}; "
            "border: none; padding: 16px; "
            "font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', "
            "'Microsoft YaHei UI', monospace; font-size: 13.5px; line-height: 1.7; "
            f"selection-background-color: {COLORS['accent']}; selection-color: #fff; }}"
        )
        self._stack.addWidget(self.editor)
        layout.addWidget(self._stack, stretch=1)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._initial_preview_refresh_pending:
            self._initial_preview_refresh_pending = False
            QTimer.singleShot(100, self._refresh_initial_preview)

    def _refresh_initial_preview(self) -> None:
        if self._stack.currentIndex() == 0:
            self._set_preview_html(self._html_content)
            # QWebEngineView can remain visually blank when its first page is
            # loaded before the dialog is exposed. Re-activating the stack page
            # after the native window is visible forces Chromium to paint it.
            self._stack.setUpdatesEnabled(False)
            self._stack.setCurrentIndex(1)
            self._stack.setCurrentIndex(0)
            self._stack.setUpdatesEnabled(True)
            self.viewer.update()

    def _toggle_mode(self) -> None:
        if self._read_only:
            return
        self._switch_mode(0 if self._stack.currentIndex() == 1 else 1)

    def _switch_mode(self, index: int) -> None:
        if index == 0:
            self._refresh_preview()
        self._stack.setCurrentIndex(index)
        if index == 0:
            self._mode_label.setText(get_text("source_viewer_preview"))
            self._edit_btn.setText(get_text("source_viewer_edit"))
        else:
            self._mode_label.setText(get_text("source_viewer_edit"))
            self._edit_btn.setText(get_text("source_viewer_preview"))
        self._update_save_visibility()

    def _update_save_visibility(self) -> None:
        can_save = self._file_path is not None
        editing = self._stack.currentIndex() == 1
        self._save_btn.setVisible(can_save and (editing or self._dirty))

    def _mark_editor_modified(self) -> None:
        self._dirty = True
        self.editor.document().setModified(True)
        self._update_save_visibility()

    def _render_preview(self, text: str) -> str:
        if self._preview_renderer is not None:
            return self._preview_renderer(text)
        suffix = self._file_path.suffix.lower() if self._file_path else ""
        if suffix == ".md":
            from raggg.desktop.rendering import markdown_to_html, web_wrapper

            return web_wrapper(markdown_to_html(text))
        if suffix in {".html", ".htm"}:
            return text
        return (
            "<pre style='white-space:pre-wrap;font-size:13px;line-height:1.6;'>"
            f"{html.escape(text)}</pre>"
        )

    def _refresh_preview(self) -> None:
        if self._file_path is None:
            return
        self._html_content = self._render_preview(self.editor.toPlainText())
        self._set_preview_html(self._html_content)

    def _set_preview_html(self, content: str) -> None:
        if self._file_path is None:
            self.viewer.setHtml(content)
            return
        base_path = str(self._file_path.parent.resolve()) + os.sep
        self.viewer.setHtml(content, QUrl.fromLocalFile(base_path))

    def _save_and_switch(self) -> None:
        if self._save_file():
            self._switch_mode(0)

    def _save_file(self) -> bool:
        if self._read_only:
            return False
        if self._file_path is None:
            QMessageBox.warning(
                self,
                get_text("source_viewer_save"),
                get_text("source_viewer_no_path_warning"),
            )
            return False

        new_text = self.editor.toPlainText()
        if self._file_path.exists() and self._loaded_mtime_ns is not None:
            if self._file_path.stat().st_mtime_ns != self._loaded_mtime_ns:
                reply = QMessageBox.question(
                    self,
                    get_text("source_viewer_external_change_title"),
                    get_text("source_viewer_external_change_message"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return False

        try:
            self._file_path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(
                self,
                get_text("source_viewer_save_failed"),
                str(exc),
            )
            return False

        self._raw_text = new_text
        self._loaded_mtime_ns = self._file_path.stat().st_mtime_ns
        self._dirty = False
        self.editor.document().setModified(False)
        self._refresh_preview()
        self.knowledge_changed.emit()
        self._update_save_visibility()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._dirty:
            event.accept()
            return

        reply = QMessageBox.question(
            self,
            get_text("source_viewer_unsaved_title"),
            get_text("source_viewer_unsaved_message"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Save:
            if self._save_file():
                event.accept()
            else:
                event.ignore()
        elif reply == QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()
