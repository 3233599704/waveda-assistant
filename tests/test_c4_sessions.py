"""C4: 会话管理测试 — 创建/切换/删除/持久化"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raggg.desktop.session_manager import MAX_HISTORY_TURNS, SessionManager


class SessionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_new_session_creates_non_empty(self) -> None:
        sm = SessionManager(self.data_dir)
        self.assertIsNotNone(sm.current)
        self.assertTrue(sm.current_id)

    def test_new_session_is_idle(self) -> None:
        sm = SessionManager(self.data_dir)
        self.assertEqual(len(sm.current.messages), 0)
        self.assertEqual(sm.current.title, "新对话")

    def test_add_message_persists(self) -> None:
        sm = SessionManager(self.data_dir)
        sm.add_message("测试问题", "测试回答")
        self.assertEqual(len(sm.current.messages), 1)
        self.assertEqual(sm.current.messages[0], ("测试问题", "测试回答"))

        # 重新加载应保持
        sm2 = SessionManager(self.data_dir)
        self.assertEqual(len(sm2.current.messages), 1)

    def test_legacy_stopped_answers_are_removed_on_load(self) -> None:
        path = self.data_dir / "conversations.json"
        path.write_text(
            json.dumps(
                {
                    "session": {
                        "id": "session",
                        "title": "测试",
                        "messages": [
                            ["Q1", "已停止生成"],
                            ["Q2", "partial\n\n> 已停止生成"],
                            ["Q3", "正常回答"],
                        ],
                        "created_at": "2026-07-28T09:00:00",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        manager = SessionManager(self.data_dir)

        self.assertEqual(manager.get_history("session"), [("Q3", "正常回答")])

    def test_delete_selected_messages_persists_and_preserves_order(self) -> None:
        sm = SessionManager(self.data_dir)
        for index in range(4):
            sm.add_message(f"Q{index}", f"A{index}")
        session_id = sm.current_id

        deleted = sm.delete_messages([0, 2])

        self.assertEqual(deleted, 2)
        self.assertEqual(sm.get_history(), [("Q1", "A1"), ("Q3", "A3")])
        self.assertEqual(
            SessionManager(self.data_dir).get_history(session_id),
            [("Q1", "A1"), ("Q3", "A3")],
        )

    def test_delete_messages_rolls_back_when_save_fails(self) -> None:
        sm = SessionManager(self.data_dir)
        sm.add_message("Q1", "A1")
        sm.add_message("Q2", "A2")

        with patch.object(sm, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                sm.delete_messages([0])

        self.assertEqual(sm.get_history(), [("Q1", "A1"), ("Q2", "A2")])

    def test_set_title(self) -> None:
        sm = SessionManager(self.data_dir)
        sm.set_title("新标题")
        self.assertEqual(sm.current.title, "新标题")

    def test_rename_targets_session_id_without_switching(self) -> None:
        sm = SessionManager(self.data_dir)
        first_id = sm.current_id
        second = sm.new_session()

        self.assertTrue(sm.rename(first_id, "  手动标题  "))

        self.assertEqual(sm.current_id, second.id)
        self.assertEqual(sm.sessions[first_id].title, "手动标题")
        self.assertFalse(sm.rename("missing", "标题"))
        self.assertFalse(sm.rename(first_id, "   "))

    def test_pinned_sessions_sort_before_normal_sessions_by_pin_time(self) -> None:
        sm = SessionManager(self.data_dir)
        first = sm.current
        first.created_at = "2026-01-01T00:00:00"
        second = sm.new_session()
        second.created_at = "2026-02-01T00:00:00"
        third = sm.new_session()
        third.created_at = "2026-03-01T00:00:00"

        self.assertTrue(sm.set_pinned(first.id, True, pinned_at="2026-07-01T00:00:00"))
        self.assertTrue(sm.set_pinned(second.id, True, pinned_at="2026-07-02T00:00:00"))
        self.assertEqual(
            [session.id for session in sm.sorted_sessions()],
            [second.id, first.id, third.id],
        )

        original_pin_time = second.pinned_at
        self.assertTrue(sm.set_pinned(second.id, True, pinned_at="2026-07-03T00:00:00"))
        self.assertEqual(second.pinned_at, original_pin_time)

        self.assertTrue(sm.set_pinned(second.id, False))
        self.assertEqual(
            [session.id for session in sm.sorted_sessions()],
            [first.id, third.id, second.id],
        )
        self.assertFalse(sm.set_pinned("missing", True))

    def test_pin_state_persists_and_old_json_defaults_to_unpinned(self) -> None:
        sm = SessionManager(self.data_dir)
        sid = sm.current_id
        sm.add_message("Q", "A")
        sm.set_pinned(sid, True, pinned_at="2026-07-02T00:00:00")
        self.assertEqual(
            SessionManager(self.data_dir).sessions[sid].pinned_at,
            "2026-07-02T00:00:00",
        )

        path = self.data_dir / "conversations.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw[sid].pop("pinned_at")
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        self.assertIsNone(SessionManager(self.data_dir).sessions[sid].pinned_at)

    def test_rename_rolls_back_when_save_fails(self) -> None:
        sm = SessionManager(self.data_dir)
        sid = sm.current_id
        original = sm.sessions[sid].title
        with patch.object(sm, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                sm.rename(sid, "不会保存")
        self.assertEqual(sm.sessions[sid].title, original)

    def test_pin_rolls_back_when_save_fails(self) -> None:
        sm = SessionManager(self.data_dir)
        sid = sm.current_id
        with patch.object(sm, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                sm.set_pinned(sid, True, pinned_at="2026-07-02T00:00:00")
        self.assertIsNone(sm.sessions[sid].pinned_at)

    def test_deleting_current_selects_first_canonical_session(self) -> None:
        sm = SessionManager(self.data_dir)
        pinned = sm.current
        sm.add_message("Q1", "A1")
        sm.set_pinned(pinned.id, True, pinned_at="2026-07-02T00:00:00")
        normal = sm.new_session()
        sm.add_message("Q2", "A2")

        self.assertTrue(sm.delete(normal.id))
        self.assertEqual(sm.current_id, pinned.id)

    def test_delete_rolls_back_when_save_fails(self) -> None:
        sm = SessionManager(self.data_dir)
        first_id = sm.current_id
        second = sm.new_session()
        with patch.object(sm, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                sm.delete(second.id)
        self.assertIn(second.id, sm.sessions)
        self.assertEqual(sm.current_id, second.id)
        self.assertIn(first_id, sm.sessions)

    def test_switch_session_preserves_history(self) -> None:
        sm = SessionManager(self.data_dir)
        sid1 = sm.current_id
        sm.add_message("Q1", "A1")

        sm.new_session()
        sid2 = sm.current_id
        sm.add_message("Q2", "A2")

        sm.switch_to(sid1)
        self.assertEqual(len(sm.get_history()), 1)
        self.assertEqual(sm.get_history()[0][0], "Q1")

        sm.switch_to(sid2)
        self.assertEqual(len(sm.get_history()), 1)
        self.assertEqual(sm.get_history()[0][0], "Q2")

    def test_delete_session_keeps_at_least_one(self) -> None:
        sm = SessionManager(self.data_dir)
        sid = sm.current_id
        sm.delete(sid)
        # 只有一个时会拒绝删除
        self.assertIsNotNone(sm.current)
        self.assertIn(sm.current_id, sm.sessions)

    def test_delete_non_current_session(self) -> None:
        sm = SessionManager(self.data_dir)
        _ = sm.current_id
        sm.new_session()  # 现在有两个
        sid2 = sm.current_id
        sm.new_session()  # 有三个
        self.assertTrue(sm.delete(sid2))
        self.assertNotIn(sid2, sm.sessions)

    def test_history_capped(self) -> None:
        sm = SessionManager(self.data_dir)
        for i in range(MAX_HISTORY_TURNS + 5):
            sm.add_message(f"Q{i}", f"A{i}")
        self.assertEqual(len(sm.current.messages), MAX_HISTORY_TURNS)
        self.assertEqual(sm.current.messages[0], ("Q5", "A5"))
        self.assertEqual(
            sm.current.messages[-1],
            (f"Q{MAX_HISTORY_TURNS + 4}", f"A{MAX_HISTORY_TURNS + 4}"),
        )

    def test_persistence_across_reload(self) -> None:
        sm = SessionManager(self.data_dir)
        sm.add_message("持久化测试", "持久化回答")
        sm.set_title("持久化标题")
        sid = sm.current_id

        sm2 = SessionManager(self.data_dir)
        self.assertIn(sid, sm2.sessions)
        self.assertEqual(sm2.get_history(sid), [("持久化测试", "持久化回答")])
        self.assertEqual(sm2.sessions[sid].title, "持久化标题")

    def test_file_format_is_valid_json(self) -> None:
        sm = SessionManager(self.data_dir)
        sm.add_message("Q", "A")
        file_path = self.data_dir / "conversations.json"
        self.assertTrue(file_path.exists())
        data = json.loads(file_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)


if __name__ == "__main__":
    unittest.main()
