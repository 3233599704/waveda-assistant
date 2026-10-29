import html
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from raggg.desktop.source_viewer import SourceViewer
from raggg.i18n import get_text


def render_markdown_stub(text: str) -> str:
    return f"<html><body>{html.escape(text)}</body></html>"


class SourceViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_viewer(self, root: Path) -> tuple[SourceViewer, Path]:
        source = root / "guide.md"
        source.write_text("# Original", encoding="utf-8")
        viewer = SourceViewer(
            "guide",
            render_markdown_stub("# Original"),
            file_path=source,
            preview_renderer=render_markdown_stub,
        )
        return viewer, source

    def test_linked_path_and_mode_toggle_are_available(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, source = self.make_viewer(Path(tmp))

            self.assertEqual(viewer.path_edit.text(), str(source.resolve()))
            self.assertTrue(viewer._edit_btn.isEnabled())
            self.assertEqual(viewer._stack.currentIndex(), 0)

            viewer._edit_btn.click()
            self.assertEqual(viewer._stack.currentIndex(), 1)
            self.assertEqual(viewer._edit_btn.text(), get_text("source_viewer_preview"))

            viewer.editor.setPlainText("# Updated preview")
            viewer._edit_btn.click()
            self.assertEqual(viewer._stack.currentIndex(), 0)
            self.assertIn("Updated preview", viewer._html_content)
            self.assertFalse(viewer._save_btn.isHidden())

            with patch.object(QMessageBox, "question", return_value=QMessageBox.Discard):
                viewer.close()

    def test_first_show_refreshes_preview_after_web_view_is_visible(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, _source = self.make_viewer(Path(tmp))

            with patch.object(viewer, "_set_preview_html") as refresh:
                viewer.show()
                QTest.qWait(150)

            refresh.assert_called_with(viewer._html_content)
            self.assertFalse(viewer._initial_preview_refresh_pending)
            self.assertEqual(viewer._stack.currentIndex(), 0)
            viewer.close()

    def test_html_source_uses_light_page_background(self) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "guide.html"
            source.write_text("<html><body>Guide</body></html>", encoding="utf-8")
            viewer = SourceViewer("guide", source.read_text(), file_path=source)

            self.assertEqual(
                viewer.viewer.page().backgroundColor().name().lower(), "#ffffff"
            )
            viewer.close()

    def test_save_updates_file_preview_and_dirty_state(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, source = self.make_viewer(Path(tmp))
            changes: list[bool] = []
            viewer.knowledge_changed.connect(lambda: changes.append(True))
            viewer.editor.setPlainText("# Saved content")

            self.assertTrue(viewer._save_file())

            self.assertEqual(source.read_text(encoding="utf-8"), "# Saved content")
            self.assertIn("Saved content", viewer._html_content)
            self.assertFalse(viewer.editor.document().isModified())
            self.assertEqual(changes, [True])
            viewer.close()

    def test_external_change_requires_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, source = self.make_viewer(Path(tmp))
            viewer.editor.setPlainText("# Local edit")
            source.write_text("# External edit", encoding="utf-8")
            changed_ns = (viewer._loaded_mtime_ns or 0) + 1_000_000_000
            os.utime(source, ns=(changed_ns, changed_ns))

            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.No
            ) as question:
                self.assertFalse(viewer._save_file())

            question.assert_called_once()
            self.assertEqual(source.read_text(encoding="utf-8"), "# External edit")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Discard):
                viewer.close()

    def test_unsaved_close_can_be_cancelled(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, _source = self.make_viewer(Path(tmp))
            viewer.editor.setPlainText("# Unsaved")
            event = QCloseEvent()

            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.Cancel
            ):
                viewer.closeEvent(event)

            self.assertFalse(event.isAccepted())
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.Discard
            ):
                viewer.close()

    def test_toolbar_has_no_duplicate_close_button(self) -> None:
        with TemporaryDirectory() as tmp:
            viewer, _source = self.make_viewer(Path(tmp))
            close_buttons = [
                button
                for button in viewer.findChildren(QPushButton)
                if button.text() == get_text("btn_close")
            ]
            self.assertEqual(close_buttons, [])
            viewer.close()

    def test_read_only_viewer_hides_editing_and_rejects_save(self) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "guide.md"
            source.write_text("original", encoding="utf-8")
            viewer = SourceViewer(
                "guide",
                "original",
                file_path=source,
                read_only=True,
            )

            self.assertTrue(viewer._edit_btn.isHidden())
            self.assertFalse(viewer._save_file())
            self.assertEqual(source.read_text(encoding="utf-8"), "original")
            viewer.close()


if __name__ == "__main__":
    unittest.main()
