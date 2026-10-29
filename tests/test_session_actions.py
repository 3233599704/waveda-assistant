import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from raggg.config import Settings
from raggg.desktop.main_window import WorkbenchWindow
from raggg.desktop.session_manager import Session
from raggg.desktop.sessions import COLORS, SessionListItemWidget, SessionPanel


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


class SessionActionWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_session_scrollbar_uses_local_neutral_colors_for_each_theme(self) -> None:
        expected_colors = {
            "light": ("#b7bdc5", "#a2a9b2"),
            "dark": ("#65707c", "#7a8591"),
        }

        for theme, (handle, hover) in expected_colors.items():
            with self.subTest(theme=theme), patch(
                "raggg.theme._current_theme",
                theme,
            ):
                panel = SessionPanel()
                style = panel.session_list.styleSheet().replace(" ", "")

                self.assertEqual(panel.session_list.objectName(), "sessionList")
                self.assertIn(f"background:{handle}", style)
                self.assertIn(f"background:{hover}", style)
                self.assertNotIn("#26364c", style)
                self.assertNotIn("#3a5070", style)

    def test_actions_button_is_visible_only_while_hovered(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", False, True)
        self.assertTrue(row.actions_button.isHidden())

        row.enterEvent(QEvent(QEvent.Enter))
        self.assertFalse(row.actions_button.isHidden())

        row.leaveEvent(QEvent(QEvent.Leave))
        self.assertTrue(row.actions_button.isHidden())

    def test_menu_actions_match_state_and_emit_target_id(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", True, False)
        emitted = []
        row.pin_requested.connect(lambda sid, pinned: emitted.append((sid, pinned)))
        menu = row._build_actions_menu()
        actions = menu.actions()

        self.assertEqual(
            [action.objectName() for action in actions],
            ["sessionRenameAction", "sessionPinAction", "sessionDeleteAction"],
        )
        self.assertEqual(actions[1].text(), "取消置顶")
        self.assertEqual(actions[2].text(), "删除对话")
        self.assertFalse(actions[2].isEnabled())

        actions[1].trigger()
        self.assertEqual(emitted, [("abc123", False)])

    def test_menu_uses_theme_colors_instead_of_transparent_black_background(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", False, True)
        menu = row._build_actions_menu()
        delete_button = menu.findChild(QPushButton, "sessionDeleteMenuButton")

        self.assertIn(f"background:{COLORS['surface3']}", menu.styleSheet())
        self.assertIn(f"color:{COLORS['text']}", menu.styleSheet())
        self.assertIsNotNone(delete_button)
        self.assertIn("background:transparent", delete_button.styleSheet())
        self.assertIn("border:none", delete_button.styleSheet())

    def test_rounded_menu_uses_a_translucent_frameless_popup_window(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", False, True)
        menu = row._build_actions_menu()

        self.assertTrue(menu.testAttribute(Qt.WA_TranslucentBackground))
        self.assertTrue(menu.windowFlags() & Qt.FramelessWindowHint)

    def test_unpinned_menu_emits_all_targeted_actions(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", False, True)
        renamed = []
        pinned = []
        deleted = []
        row.rename_requested.connect(renamed.append)
        row.pin_requested.connect(lambda sid, value: pinned.append((sid, value)))
        row.delete_requested.connect(deleted.append)
        actions = row._build_actions_menu().actions()

        self.assertEqual(actions[1].text(), "置顶")
        actions[0].trigger()
        actions[1].trigger()
        actions[2].trigger()

        self.assertEqual(renamed, ["abc123"])
        self.assertEqual(pinned, [("abc123", True)])
        self.assertEqual(deleted, ["abc123"])

    def test_title_click_activates_row_but_ellipsis_click_does_not(self) -> None:
        row = SessionListItemWidget("abc123", "会话标题", False, True)
        row.show()
        activated = []
        row.activated.connect(activated.append)

        QTest.mouseClick(row.title_label, Qt.LeftButton)
        self.assertEqual(activated, ["abc123"])

        with patch.object(row, "_show_actions_menu"):
            QTest.mouseClick(row.actions_button, Qt.LeftButton)
        self.assertEqual(activated, ["abc123"])

    def test_panel_populates_rows_and_forwards_targeted_actions(self) -> None:
        panel = SessionPanel()
        sessions = [
            Session(id="pinned", title="置顶会话", pinned_at="2026-07-02"),
            Session(id="normal", title="普通会话"),
        ]
        panel.set_sessions(sessions, current_id="normal")

        first_item = panel.session_list.item(0)
        first_row = panel.session_list.itemWidget(first_item)
        emitted = []
        panel.rename_requested.connect(emitted.append)
        first_row.rename_requested.emit("pinned")

        self.assertEqual(first_item.data(Qt.UserRole), "pinned")
        self.assertEqual(emitted, ["pinned"])
        self.assertEqual(panel.session_list.currentItem().data(Qt.UserRole), "normal")

        first_row.activated.emit("pinned")
        self.assertEqual(panel.session_list.currentItem().data(Qt.UserRole), "pinned")

    def test_duplicate_titles_include_creation_time_in_sidebar(self) -> None:
        panel = SessionPanel()
        panel.set_sessions(
            [
                Session(
                    id="first",
                    title="波端口设置要点",
                    created_at="2026-07-28T09:15:00",
                ),
                Session(
                    id="second",
                    title="波端口设置要点",
                    created_at="2026-07-28T14:30:00",
                ),
            ],
            current_id="second",
        )

        titles = [
            panel.session_list.itemWidget(panel.session_list.item(index))._full_title
            for index in range(panel.session_list.count())
        ]
        self.assertEqual(
            titles,
            ["波端口设置要点 · 09:15", "波端口设置要点 · 14:30"],
        )

    def test_long_title_keeps_ellipsis_inside_210_pixel_panel(self) -> None:
        panel = SessionPanel()
        panel.set_sessions(
            [
                Session(
                    id="long",
                    title="一段足以溢出两百一十像素会话侧栏的超长会话标题" * 4,
                ),
                Session(id="other", title="另一会话"),
            ],
            current_id="long",
        )
        panel.show()
        self.app.processEvents()

        item = panel.session_list.item(0)
        row = panel.session_list.itemWidget(item)
        button_right = panel.mapFromGlobal(
            row.actions_button.mapToGlobal(row.actions_button.rect().bottomRight())
        ).x()

        self.assertEqual(panel.width(), 210)
        self.assertEqual(panel.session_list.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(button_right, panel.width() - 1)
        self.assertTrue(row.title_label.text().endswith("…"))

    def test_session_rows_keep_a_clickable_height(self) -> None:
        panel = SessionPanel()
        panel.set_sessions(
            [Session(id="first", title="第一会话"), Session(id="second", title="第二会话")],
            current_id="first",
        )

        heights = [
            panel.session_list.item(index).sizeHint().height()
            for index in range(panel.session_list.count())
        ]

        self.assertTrue(all(height >= 32 for height in heights))

    def test_horizontal_ellipsis_button_fits_completely_inside_session_row(self) -> None:
        panel = SessionPanel()
        panel.set_sessions(
            [Session(id="first", title="第一会话"), Session(id="second", title="第二会话")],
            current_id="first",
        )
        panel.show()
        self.app.processEvents()

        row = panel.session_list.itemWidget(panel.session_list.item(0))
        row.enterEvent(QEvent(QEvent.Enter))
        self.app.processEvents()
        button = row.actions_button

        self.assertEqual(button.text(), "⋯")
        self.assertTrue(button.isVisible())
        self.assertGreaterEqual(button.geometry().top(), 0)
        self.assertLess(button.geometry().bottom(), row.height())

    def test_activated_row_updates_current_visual_state_for_both_rows(self) -> None:
        panel = SessionPanel()
        panel.set_sessions(
            [Session(id="first", title="第一会话"), Session(id="second", title="第二会话")],
            current_id="second",
        )
        first_row = panel.session_list.itemWidget(panel.session_list.item(0))
        second_row = panel.session_list.itemWidget(panel.session_list.item(1))

        first_row.activated.emit("first")

        self.assertTrue(first_row.is_current)
        self.assertFalse(second_row.is_current)
        self.assertEqual(first_row.title_label.styleSheet(), f"color:{COLORS['accent']};")
        self.assertEqual(second_row.title_label.styleSheet(), f"color:{COLORS['muted']};")


class SessionActionWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self) -> WorkbenchWindow:
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        with patch.object(WorkbenchWindow, "_build_image_index"), \
             patch.object(WorkbenchWindow, "_preload_images"), \
             patch.object(WorkbenchWindow, "_load_pipeline_if_ready"), \
             patch.object(WorkbenchWindow, "_start_source_watcher"):
            return WorkbenchWindow(make_settings(root))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_rename_non_current_session_does_not_switch_chat(self) -> None:
        window = self.make_window()
        first_id = window._session_manager.current_id
        first_title = window._session_manager.sessions[first_id].title
        second = window._session_manager.new_session()
        window._refresh_session_list()

        with patch(
            "raggg.desktop.sessions.QInputDialog.getText",
            return_value=("手动名称", True),
        ):
            window._rename_session(first_id)

        self.assertEqual(window._session_manager.current_id, second.id)
        self.assertNotEqual(first_title, "手动名称")
        self.assertEqual(window._session_manager.sessions[first_id].title, "手动名称")

    def test_pin_non_current_session_keeps_current_identity(self) -> None:
        window = self.make_window()
        first_id = window._session_manager.current_id
        second = window._session_manager.new_session()

        window._set_session_pinned(first_id, True)

        self.assertEqual(window._session_manager.current_id, second.id)
        self.assertIsNotNone(window._session_manager.sessions[first_id].pinned_at)

    def test_delete_non_current_session_preserves_current_chat(self) -> None:
        window = self.make_window()
        first_id = window._session_manager.current_id
        window._session_manager.add_message("Q1", "A1")
        second = window._session_manager.new_session()
        window._session_manager.add_message("Q2", "A2")
        window._conversation_history = window._session_manager.get_history()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(window.chat, "setHtml") as set_html:
            window._delete_session(first_id)

        self.assertEqual(window._session_manager.current_id, second.id)
        self.assertEqual(window._conversation_history, [("Q2", "A2")])
        set_html.assert_not_called()

    def test_delete_current_session_loads_remaining_history(self) -> None:
        window = self.make_window()
        first_id = window._session_manager.current_id
        window._session_manager.add_message("Q1", "A1")
        second = window._session_manager.new_session()
        window._session_manager.add_message("Q2", "A2")

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(window, "_show_session_content") as show_history:
            window._delete_session(second.id)

        self.assertEqual(window._session_manager.current_id, first_id)
        self.assertEqual(window._conversation_history, [("Q1", "A1")])
        show_history.assert_called_once_with([("Q1", "A1")])

    def test_delete_missing_session_refreshes_without_confirmation(self) -> None:
        window = self.make_window()

        with patch.object(QMessageBox, "question") as question, \
             patch.object(window, "_refresh_session_list") as refresh:
            window._delete_session("missing")

        question.assert_not_called()
        refresh.assert_called_once_with()

    def test_chat_turn_menu_supports_multi_select_and_delete(self) -> None:
        window = self.make_window()
        window._session_manager.add_message("Q1", "A1")
        window._session_manager.add_message("Q2", "A2")

        menu = window._build_chat_turn_menu(0)
        actions = {action.objectName(): action for action in menu.actions()}
        actions["chatCopyQuestionAction"].trigger()
        self.assertEqual(QApplication.clipboard().text(), "Q1")

        menu = window._build_chat_turn_menu(0, "selected words")
        actions = {action.objectName(): action for action in menu.actions()}
        actions["chatCopySelectionAction"].trigger()
        self.assertEqual(QApplication.clipboard().text(), "selected words")

        with patch.object(window, "_set_chat_turn_selected") as select_turn:
            menu = window._build_chat_turn_menu(0)
            actions = {action.objectName(): action for action in menu.actions()}
            actions["chatSelectTurnAction"].trigger()
            select_turn.assert_called_once_with(0, True)

        window._selected_turn_indices = {0, 1}
        with patch.object(window, "_delete_chat_turns") as delete_turns:
            menu = window._build_chat_turn_menu(1)
            actions = {action.objectName(): action for action in menu.actions()}
            actions["chatDeleteSelectedAction"].trigger()
            delete_turns.assert_called_once_with([0, 1])

    def test_chat_context_callback_decodes_json_and_opens_menu(self) -> None:
        window = self.make_window()
        window._session_manager.add_message("Q1", "A1")

        def run_javascript(_script, callback) -> None:
            callback('{"turnIndex": 0, "selectedText": "selected words"}')

        with patch.object(
            window.chat.page(), "runJavaScript", side_effect=run_javascript
        ), patch.object(
            QTimer, "singleShot", side_effect=lambda _delay, callback: callback()
        ), patch.object(window, "_popup_chat_turn_menu") as popup_menu:
            window._show_chat_context_menu(QPoint(20, 30))

        popup_menu.assert_called_once()
        self.assertEqual(popup_menu.call_args.args[:2], (0, "selected words"))

    def test_deleting_chat_turns_updates_memory_disk_and_rendered_history(self) -> None:
        window = self.make_window()
        session_id = window._session_manager.current_id
        for index in range(3):
            window._session_manager.add_message(f"Q{index}", f"A{index}")
        window._conversation_history = window._session_manager.get_history()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
             patch.object(window, "_clear_sources_for_session_change"), \
             patch.object(window, "_show_session_content") as show_history:
            window._delete_chat_turns([0, 2])

        expected = [("Q1", "A1")]
        self.assertEqual(window._conversation_history, expected)
        self.assertEqual(window._session_manager.get_history(), expected)
        self.assertEqual(window._last_qa, ("Q1", "A1"))
        show_history.assert_called_once_with(expected)

        reloaded = window._session_manager.__class__(window.settings.data_dir)
        self.assertEqual(reloaded.get_history(session_id), expected)

    def test_history_html_groups_each_question_and_answer_as_one_turn(self) -> None:
        window = self.make_window()

        with patch.object(window.chat, "setHtml") as set_html:
            window._show_session_content([("Q1", "A1"), ("Q2", "A2")])

        rendered = set_html.call_args.args[0]
        self.assertEqual(rendered.count("data-rag-turn='1'"), 2)
        self.assertIn("data-turn-index='0'", rendered)
        self.assertIn("data-turn-index='1'", rendered)
