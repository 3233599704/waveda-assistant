from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from raggg.config import Settings, load_settings
from raggg.desktop.favorites import (
    FavoritesMixin,
    favorite_matches,
    favorite_score,
    highlight_keywords,
    normalize_favorite_search_text,
)
from raggg.desktop.image_index import ImageIndex
from raggg.desktop.rendering import (
    markdown_to_html,
    render_inline_markdown,
    web_wrapper,
)
from raggg.desktop.views import WorkbenchViewsMixin
from raggg.desktop.sessions import SessionsMixin
from raggg.desktop.widgets import AILoaderOverlay
from raggg.theme import apply_application_style


class WorkbenchWindow(FavoritesMixin, SessionsMixin, WorkbenchViewsMixin):
    """Desktop coordinator assembled from focused feature modules."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)


def run_desktop_app() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_application_style(app)
    window = WorkbenchWindow(load_settings())
    window.show()
    return app.exec()
