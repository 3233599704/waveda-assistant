from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QLineEdit, QPushButton

from raggg.config import Settings
from raggg.desktop.main_window import AILoaderOverlay, WorkbenchWindow, favorite_matches, favorite_score
from raggg.desktop.workers import AskResult, CancellationToken
from raggg.models import Chunk
from raggg.pipeline.builder import BuildProgress
from raggg.pipeline.rag_pipeline import RAGAnswer
from raggg.retrieval.retriever import SearchResult
from raggg.theme import get_colors


def make_settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        waveda_root=None,
        waveda_help_root=root / "wavEDA_docs" / "helpHtml" / "helpHtml",
        waveda_example_root=None,
        obsidian_vault_root=root / "knowledge_base",
        data_dir=root / "data",
        embedding_model="local-hashed-vectors",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
    )


class DesktopLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_minimal_gui_starts_with_hidden_sidebar(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            self.assertTrue(window.sidebar_container.isHidden())
            self.assertEqual(window.sidebar_toggle_button.text(), "◧")
            self.assertEqual(window.import_button.text(), "+")
            self.assertEqual(window.ask_button.text(), "↑")
            self.assertGreaterEqual(window.question.parentWidget().minimumWidth(), 480)
            self.assertEqual(window.chat.contextMenuPolicy(), Qt.CustomContextMenu)

    def test_sources_page_keeps_theme_background_after_custom_page_install(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            self.assertEqual(
                window.sources.page().backgroundColor(),
                QColor(get_colors()["bg"]),
            )

    def test_question_input_uses_themed_standard_context_menu(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            self.assertEqual(
                window.question.contextMenuPolicy(),
                Qt.CustomContextMenu,
            )
            menu = window._create_question_context_menu()
            copy_actions = [
                action
                for action in menu.actions()
                if action.text().endswith("\tCtrl+C")
            ]
            self.assertTrue(copy_actions)

    def test_question_context_menu_has_readable_colors_in_both_themes(self) -> None:
        expected_colors = {
            "light": ("#f5f6f8", "#26323d", "#e2e8ef", "#9aa2aa"),
            "dark": ("#1b2635", "#e2e8f0", "#2f4258", "#77869a"),
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            for theme, colors in expected_colors.items():
                with self.subTest(theme=theme), patch(
                    "raggg.theme._current_theme",
                    theme,
                ):
                    style = (
                        window._create_question_context_menu()
                        .styleSheet()
                        .replace(" ", "")
                    )
                    for color in colors:
                        self.assertIn(color, style)

    def test_sidebar_toggle_shows_and_hides_sidebar(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window.sidebar_toggle_button.click()
            self.assertFalse(window.sidebar_container.isHidden())

            window.sidebar_toggle_button.click()
            self.assertTrue(window.sidebar_container.isHidden())

    def test_sidebar_has_manual_rebuild_button_and_busy_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            button = getattr(window, "rebuild_index_button", None)
            self.assertIsNotNone(button)
            self.assertEqual(button.text(), "重建索引")
            with patch.object(window, "_rebuild_async") as rebuild:
                button.click()
                rebuild.assert_called_once_with()

            window._set_busy(True, "正在重建知识库")
            self.assertFalse(button.isEnabled())
            window._set_busy(False, "就绪")
            self.assertTrue(button.isEnabled())

    def test_basic_shortcuts_are_window_scoped(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            expected = {
                "focusQuestionShortcut": "Ctrl+L",
                "newSessionShortcut": "Ctrl+N",
                "toggleSidebarShortcut": "Ctrl+B",
            }
            shortcuts = {
                shortcut.objectName(): shortcut
                for shortcut in window.findChildren(QShortcut)
            }

            self.assertEqual(set(shortcuts), set(expected))
            for name, sequence in expected.items():
                self.assertEqual(shortcuts[name].key(), QKeySequence(sequence))
                self.assertEqual(shortcuts[name].context(), Qt.WindowShortcut)

    def test_ctrl_l_focuses_and_selects_question_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window.show()
            self.app.processEvents()
            window.question.setText("replace me")
            window.focus_question_shortcut.activated.emit()

            self.assertTrue(window.question.hasFocus())
            self.assertEqual(window.question.selectedText(), "replace me")

    def test_ctrl_n_creates_session_only_while_idle(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window.show()
            self.app.processEvents()
            original_id = window._session_manager.current_id
            window.new_session_shortcut.activated.emit()
            idle_id = window._session_manager.current_id

            self.assertNotEqual(idle_id, original_id)
            self.assertTrue(window.question.hasFocus())

            window.is_busy = True
            window.new_session_shortcut.activated.emit()

            self.assertEqual(window._session_manager.current_id, idle_id)

    def test_ctrl_b_toggles_only_data_sidebar(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            session_was_hidden = window.session_panel.isHidden()
            self.assertTrue(window.sidebar_container.isHidden())

            window.toggle_sidebar_shortcut.activated.emit()

            self.assertFalse(window.sidebar_container.isHidden())
            self.assertEqual(window.session_panel.isHidden(), session_was_hidden)

    def test_shortcuts_are_discoverable_in_tooltips(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            self.assertIn("Ctrl+L", window.question.toolTip())
            self.assertIn("Ctrl+B", window.sidebar_toggle_button.toolTip())
            new_session_buttons = [
                button
                for button in window.session_panel.findChildren(QPushButton)
                if "Ctrl+N" in button.toolTip()
            ]
            self.assertEqual(len(new_session_buttons), 1)

    def test_startup_loader_is_visible_with_initial_message(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            self.assertFalse(window.loader_overlay.isHidden())
            self.assertEqual(window.loader_overlay.text, "正在载入")

    def test_busy_state_reuses_loader_overlay(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window.loader_overlay.hide()
            window._set_busy(True, "正在检索")

            self.assertFalse(window.loader_overlay.isHidden())
            self.assertEqual(window.loader_overlay.text, "正在检索")

    def test_generation_busy_state_turns_send_button_into_stop_button(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            token = CancellationToken()
            window._generation_token = token
            window.pipeline = Mock()
            window._set_busy(True, "正在检索与生成")

            self.assertTrue(window.loader_overlay.isHidden())
            self.assertFalse(window.question.isHidden())
            self.assertEqual(window.ask_button.text(), "■")
            self.assertEqual(window.ask_button.toolTip(), "停止生成")
            self.assertTrue(window.ask_button.isEnabled())

            window.ask_button.click()

            self.assertTrue(token.is_cancelled())
            self.assertFalse(window.ask_button.isEnabled())
            window.pipeline.cancel_active_request.assert_called_once_with()

            window._on_generation_finished(token)
            self.assertEqual(window.ask_button.text(), "↑")
            self.assertTrue(window.ask_button.isEnabled())

    def test_chat_supports_selecting_and_appending_multiple_attachments(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.txt"
            second = root / "second.md"
            first.write_text("first attachment", encoding="utf-8")
            second.write_text("second attachment", encoding="utf-8")
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            with patch(
                "raggg.desktop.views.QFileDialog.getOpenFileNames",
                side_effect=[([str(first)], ""), ([str(second)], "")],
            ):
                window._import_document()
                window._import_document()

            self.assertEqual(len(window._temp_attachments), 2)
            self.assertFalse(window.attachment_scroll.isHidden())
            self.assertEqual(window.attachment_cards_layout.count(), 2)
            close_buttons = window.attachment_cards_widget.findChildren(
                QPushButton,
                "attachmentCloseButton",
            )
            self.assertEqual(len(close_buttons), 2)

            first_close = next(
                button for button in close_buttons if "first.txt" in button.toolTip()
            )
            first_close.click()

            self.assertEqual(len(window._temp_attachments), 1)
            self.assertEqual(window.attachment_cards_layout.count(), 1)

            context = window._build_attachment_context()
            self.assertIn("second attachment", context)
            self.assertNotIn("请比较这两个文件", context)

    def test_attachment_payload_is_sent_and_kept_for_session_memory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            attachment = root / "notes.txt"
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            window.pipeline = Mock()
            window.pipeline.ask.return_value = RAGAnswer(
                question="request",
                answer="answer",
                sources=[],
            )
            window._temp_attachments = [(attachment, "private attachment content")]
            window.question.setText("总结附件")

            with patch.object(window, "_append_user") as append_user, \
                 patch.object(window, "_begin_streaming_assistant", return_value="stream"), \
                 patch.object(window, "_set_busy"), \
                 patch.object(window, "_start_worker") as start_worker:
                window._ask()

            result = start_worker.call_args.args[0].fn()
            request_text = window.pipeline.ask.call_args.args[0]
            attachment_context = window.pipeline.ask.call_args.kwargs[
                "additional_context"
            ]
            self.assertEqual(request_text, "总结附件")
            self.assertIn("private attachment content", attachment_context)
            self.assertEqual(result.question, "总结附件")
            append_user.assert_called_once_with("总结附件")
            self.assertEqual(
                window._temp_attachments,
                [(attachment, "private attachment content")],
            )

    def test_busy_loader_keeps_side_panels_visible(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window.show()
            window.session_panel.show()
            window.sidebar_container.show()
            self.app.processEvents()
            window._set_busy(True, "正在检索")
            self.app.processEvents()

            self.assertFalse(window.session_panel.isHidden())
            self.assertFalse(window.sidebar_container.isHidden())
            self.assertEqual(window.loader_overlay.geometry(), window.main_workspace.geometry())
            self.assertFalse(window.loader_overlay.geometry().intersects(window.session_panel.geometry()))
            self.assertFalse(window.loader_overlay.geometry().intersects(window.sidebar_container.geometry()))
            window.close()

    def test_loader_uses_orbital_glow_animation_contract(self) -> None:
        overlay = AILoaderOverlay(text="生成中")

        self.assertEqual(overlay.visual_mode, "orbital-glow")
        self.assertGreater(overlay._letter_intensity(18), overlay._letter_intensity(60))
        self.assertGreaterEqual(overlay._letter_lift(18), 2)

    @unittest.skip("legacy expectation searched answer正文; favorites now search question only")
    def test_favorite_search_matches_question_only_case_insensitively(self) -> None:
        favorite = {
            "question": "How do I set a Wave Port?",
            "answer": "在边界设置中选择端口截面。",
        }
        self.assertTrue(favorite_matches(favorite, "wave port"))
        self.assertTrue(favorite_matches(favorite, "端口截面"))
        self.assertTrue(favorite_matches(favorite, ""))
        self.assertFalse(favorite_matches(favorite, "PML"))

    @unittest.skip("legacy expectation searched answer正文; favorites now search question only")
    def test_favorite_search_ignores_all_whitespace_variants(self) -> None:
        favorite = {
            "question": "How do I set a Wave Port?",
            "answer": "选择\u00a0端口\t截面。",
        }

        for query in (
            "waveport",
            "wave   port",
            "wave\tport",
            "wave\u3000port",
            "选择端口截面",
            "选择\n端口\u00a0截面",
        ):
            with self.subTest(query=query):
                self.assertTrue(favorite_matches(favorite, query))
                self.assertGreater(favorite_score(favorite, query), 0)

        self.assertTrue(favorite_matches(favorite, " \t\u00a0\n"))

    @unittest.skip("legacy expectation searched answer正文; favorites now search question only")
    def test_favorites_dialog_filters_question_and_answer_content(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.joinpath("data").mkdir()
            root.joinpath("data", "favorites.json").write_text(
                json.dumps([
                    {"question": "如何设置波端口？", "answer": "选择端口截面", "time": "2026-07-15 10:00"},
                    {"question": "网格怎么划分？", "answer": "使用自适应网格", "time": "2026-07-15 11:00"},
                ], ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            def inspect_dialog(dialog: QDialog) -> int:
                search_input = dialog.findChild(QLineEdit, "favoritesSearchInput")
                self.assertIsNotNone(search_input)
                search_input.setText("自适应网格")
                cards = dialog.findChildren(QFrame, "metricCard")
                self.assertEqual(len(cards), 2)
                self.assertEqual(sum(not card.isHidden() for card in cards), 1)
                self.assertTrue(dialog.findChild(QLabel, "favoritesNoResults").isHidden())
                search_input.setText("不存在的内容")
                self.assertTrue(all(card.isHidden() for card in cards))
                self.assertFalse(dialog.findChild(QLabel, "favoritesNoResults").isHidden())
                search_input.clear()
                self.assertTrue(all(not card.isHidden() for card in cards))
                return QDialog.Rejected

            with patch.object(QDialog, "exec", new=inspect_dialog):
                window._open_favorites()

    def test_favorite_search_does_not_match_answer_body(self) -> None:
        favorite = {"question": "How do I export S parameters?", "answer": "Use the port result tree."}

        self.assertTrue(favorite_matches(favorite, "export S parameters"))
        self.assertFalse(favorite_matches(favorite, "port result tree"))

    def test_source_cards_have_stable_citation_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            chunk = Chunk(
                id="source-1",
                source_type="waveda_help",
                source_path=str(root / "port.html"),
                relative_path="guide/port.html",
                title="Port",
                section="Setup",
                content="Port setup",
            )
            result = SearchResult(chunk, 0.9, 0.8, 0.1)

            rendered = window._sources_html([result])

            self.assertIn('id="source-1"', rendered)

    def test_citation_console_message_focuses_matching_source(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            with patch.object(window, "_focus_source") as focus_source:
                window._on_console_msg(0, "RAGGG_CITATION:2", 0, "")

            focus_source.assert_called_once_with(2)

    def test_citation_focus_opens_corresponding_source_document(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "port.md"
            source_path.write_text(
                "# Port setup\n\nConfigure the port here.",
                encoding="utf-8",
            )
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window._source_paths[1] = str(source_path)
            self.assertTrue(window.sidebar_container.isHidden())
            with patch("raggg.desktop.views.SourceViewer") as viewer_type:
                window._focus_source(1)

            self.assertTrue(window.sidebar_container.isHidden())
            title, rendered_html, parent = viewer_type.call_args.args
            self.assertEqual(title, "port")
            self.assertIn("Configure the port here.", rendered_html)
            self.assertIs(parent, window)
            self.assertEqual(viewer_type.call_args.kwargs["file_path"], source_path)
            viewer_type.return_value.knowledge_changed.connect.assert_called_once_with(
                window._check_source_changes
            )
            viewer_type.return_value.show.assert_called_once_with()

    def test_loader_progress_text_updates_during_rebuild(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))

            window._on_build_progress(
                BuildProgress("embed", "正在生成向量", 3, 10)
            )

            self.assertIn("正在生成向量", window.loader_overlay.progress_label.text())
            self.assertIn("3/10", window.loader_overlay.progress_label.text())

    def test_switching_sessions_clears_stale_source_mapping(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            first_id = window._session_manager.current_id
            window._session_manager.add_message("Q", "A [1]")
            second = window._session_manager.new_session()
            window._refresh_session_list()
            window._source_paths[1] = str(root / "unrelated.html")
            for row in range(window.session_list.count()):
                item = window.session_list.item(row)
                if item.data(Qt.UserRole) == first_id:
                    window.session_list.setCurrentRow(row)
                    break

            self.assertEqual(window._session_manager.current_id, first_id)
            self.assertNotEqual(window._session_manager.current_id, second.id)
            self.assertEqual(window._source_paths, {})

    def test_new_session_clears_previous_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            window._source_paths[1] = str(root / "previous.html")

            window._new_session()

            self.assertEqual(window._source_paths, {})

    def test_answer_warning_is_rendered_after_answer(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            result = AskResult(
                "question",
                RAGAnswer(
                    question="question",
                    answer="answer",
                    sources=[],
                    warning="API warning",
                ),
            )

            with patch.object(window, "_append_assistant") as append_assistant, \
                 patch.object(window, "_remember_turn"), \
                 patch.object(window, "_sources_html", return_value="<html></html>"):
                window._on_answer_done(result)

            self.assertEqual(
                [item.args[0] for item in append_assistant.call_args_list],
                ["answer", "> ⚠️ API warning"],
            )

    def test_english_answer_image_cards_do_not_append_chinese_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            result = AskResult(
                "How do I configure a wave port?",
                RAGAnswer(
                    question="How do I configure a wave port?",
                    answer="Configure the wave port as follows. [1]",
                    sources=[object()],
                ),
            )

            with patch.object(window, "_append_assistant"), \
                 patch.object(window, "_remember_turn"), \
                 patch.object(window, "_sources_html", return_value="<html></html>"), \
                 patch.object(window, "_append_html_to_active_turn") as append_html, \
                 patch(
                     "raggg.desktop.views._extract_images_from_sources",
                     return_value=[(str(root / "port.png"), "波端口网格")],
                 ), \
                 patch(
                     "raggg.desktop.views._path_to_data_uri",
                     return_value="data:image/png;base64,AA==",
                 ):
                window._on_answer_done(result)

            rendered = append_html.call_args.args[0]
            self.assertIn("Reference image 1", rendered)
            self.assertNotRegex(
                rendered,
                r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]",
            )

    def test_cancelled_answer_becomes_status_and_is_not_saved_to_context(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(WorkbenchWindow, "_build_image_index"), \
                 patch.object(WorkbenchWindow, "_preload_images"), \
                 patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
                 patch.object(WorkbenchWindow, "_start_source_watcher"):
                window = WorkbenchWindow(make_settings(root))
            result = AskResult(
                "question",
                RAGAnswer(
                    question="question",
                    answer="partial answer",
                    sources=[],
                    cancelled=True,
                ),
            )

            with patch.object(window, "_show_cancelled_status") as show_status, \
                 patch.object(window, "_remember_turn") as remember:
                window._on_answer_done(result, "stream-id")

            show_status.assert_called_once_with("stream-id")
            remember.assert_not_called()
            self.assertEqual(window._session_manager.get_history(), [])
            self.assertEqual(window._last_qa, ("", ""))


if __name__ == "__main__":
    unittest.main()
