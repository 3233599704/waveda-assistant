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
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from raggg.config import Settings, application_root, config_env_path, load_settings
from raggg.desktop.image_cache import ImageDataUriCache
from raggg.desktop.session_manager import SessionManager
from raggg.i18n import get_text, get_language, set_language, get_welcome_text
from raggg.pipeline.builder import BuildReport, build_knowledge_base
from raggg.pipeline.ingestion import IngestReport, ingest_document
from raggg.pipeline.rag_pipeline import RAGAnswer, RAGPipeline
from raggg.pipeline.source_watch import SourceSnapshot, scan_source_tree, snapshot_changed
from raggg.retrieval.retriever import SearchResult
from raggg.theme import get_theme, set_theme, get_colors, build_style, get_chat_bubble_colors, THEMES

# ── 动态主题 ──
COLORS = get_colors()
APP_STYLE = build_style()


class MetricCard(QFrame):
    def __init__(self, label: str, value: str, color: str = COLORS["accent"]) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        title = QLabel(label)
        title.setObjectName("metricLabel")
        title.setMinimumHeight(18)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setStyleSheet(f"color: {color};")
        self.value_label.setMinimumHeight(26)
        self.value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(title)
        layout.addWidget(self.value_label)

    def set_value(self, value: str, color: str | None = None) -> None:
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"color: {color};")


class AILoaderOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None, text: str = "正在载入") -> None:
        super().__init__(parent)
        self.visual_mode = "orbital-glow"
        self.text = text
        self._angle = 90
        self._pulse = 0
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        self.progress_label = QLabel(self)
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet(
            "background:transparent;color:rgba(33,55,76,210);"
            "font:12px 'Microsoft YaHei UI';"
        )
        self.progress_label.hide()

    def set_text(self, text: str) -> None:
        self.text = text or "请稍候"
        self.update()

    def set_progress_text(self, text: str) -> None:
        self.progress_label.setText(text)
        self.progress_label.setVisible(bool(text))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        label_width = min(520, max(220, self.width() - 80))
        self.progress_label.setGeometry(
            (self.width() - label_width) // 2,
            self.height() // 2 + 108,
            label_width,
            48,
        )

    def _advance(self) -> None:
        self._angle = (self._angle + 2) % 360
        self._pulse = (self._pulse + 1) % 180
        self.update()

    def _letter_intensity(self, phase: int) -> float:
        return 0.38 + 0.62 * max(0.0, 1.0 - abs(phase - 18) / 18)

    def _letter_lift(self, phase: int) -> int:
        return 3 if 12 <= phase <= 24 else 0

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        dark_mode = get_theme() == "dark"
        if dark_mode:
            background_stops = (
                (0.0, QColor(26, 20, 40)),
                (0.42, QColor(15, 36, 51)),
                (1.0, QColor(10, 48, 72)),
            )
            halo_rgb = (82, 172, 226)
            ring_colors = (
                QColor(108, 190, 226, 72),
                QColor(48, 112, 150, 164),
                QColor(70, 165, 220, 228),
                QColor(38, 109, 179, 230),
                QColor(16, 42, 64, 222),
            )
            core_colors = (
                QColor(54, 104, 132, 220),
                QColor(31, 79, 104, 202),
                QColor(20, 58, 82, 176),
                QColor(12, 37, 58, 142),
            )
            arc_colors = (
                QColor(194, 231, 250, 178),
                QColor(74, 151, 219, 136),
                QColor(143, 207, 240, 100),
            )
            sweep_color = QColor(100, 181, 236, 210)
            text_rgb = (220, 229, 240)
        else:
            background_stops = (
                (0.0, QColor(248, 228, 239)),
                (0.42, QColor(231, 241, 240)),
                (1.0, QColor(126, 199, 241)),
            )
            halo_rgb = (101, 181, 228)
            ring_colors = (
                QColor(255, 255, 255, 70),
                QColor(210, 242, 252, 132),
                QColor(116, 195, 238, 230),
                QColor(68, 137, 218, 228),
                QColor(242, 252, 255, 206),
            )
            core_colors = (
                QColor(245, 253, 255, 226),
                QColor(226, 246, 250, 196),
                QColor(180, 225, 243, 142),
                QColor(112, 184, 232, 92),
            )
            arc_colors = (
                QColor(255, 255, 255, 178),
                QColor(68, 133, 209, 92),
                QColor(255, 255, 255, 82),
            )
            sweep_color = QColor(78, 145, 221, 188)
            text_rgb = (33, 55, 76)

        gradient = QLinearGradient(0, 0, 0, self.height())
        for position, color in background_stops:
            gradient.setColorAt(position, color)
        painter.fillRect(self.rect(), gradient)

        size = min(190, max(132, min(self.width(), self.height()) // 4))
        center_x = self.width() / 2
        center_y = self.height() / 2
        rect = QRectF(center_x - size / 2, center_y - size / 2, size, size)

        painter.setPen(Qt.NoPen)
        for spread, alpha in ((34, 28), (22, 46), (12, 64)):
            halo = QRadialGradient(rect.center(), size / 2 + spread)
            halo.setColorAt(0.0, QColor(255, 255, 255, 0))
            halo.setColorAt(0.55, QColor(*halo_rgb, alpha))
            halo.setColorAt(1.0, QColor(*halo_rgb, 0))
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(rect.adjusted(-spread, -spread, spread, spread))

        ring = QRadialGradient(rect.center(), size / 2)
        for position, color in zip((0.00, 0.54, 0.74, 0.89, 1.00), ring_colors):
            ring.setColorAt(position, color)
        painter.setBrush(QBrush(ring))
        painter.drawEllipse(rect)

        core_rect = rect.adjusted(24, 24, -24, -24)
        core = QRadialGradient(core_rect.center(), core_rect.width() / 2)
        for position, color in zip((0.00, 0.48, 0.76, 1.00), core_colors):
            core.setColorAt(position, color)
        painter.setBrush(QBrush(core))
        painter.drawEllipse(core_rect)

        painter.setBrush(Qt.NoBrush)
        for inset, color, width in zip((25, 34, 48), arc_colors, (3, 8, 2)):
            pen = QPen(color, width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawArc(rect.adjusted(inset, inset, -inset, -inset), (self._angle + inset) * 16, 118 * 16)

        sweep_rect = rect.adjusted(5, 5, -5, -5)
        sweep_pen = QPen(sweep_color, 6)
        sweep_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(sweep_pen)
        painter.drawArc(sweep_rect, -(self._angle + 18) * 16, 64 * 16)

        painter.setFont(QFont("Microsoft YaHei UI", 13, QFont.DemiBold))
        metrics = painter.fontMetrics()
        letters = list(self.text)
        spacing = 2
        total_width = sum(metrics.horizontalAdvance(letter) for letter in letters) + spacing * max(0, len(letters) - 1)
        x = center_x - total_width / 2
        base_y = center_y + metrics.ascent() / 2 - 2
        for index, letter in enumerate(letters):
            phase = (self._pulse + index * 9) % 90
            brightness = self._letter_intensity(phase)
            lift = -self._letter_lift(phase)
            color = QColor(*text_rgb)
            color.setAlpha(int(92 + 138 * brightness))
            painter.setPen(color)
            painter.drawText(QRectF(x, base_y - metrics.ascent() + lift, metrics.horizontalAdvance(letter) + 3, metrics.height()), Qt.AlignLeft, letter)
            x += metrics.horizontalAdvance(letter) + spacing


