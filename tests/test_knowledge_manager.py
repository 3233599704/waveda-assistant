import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from raggg.config import Settings
from raggg.desktop.knowledge_manager import KnowledgeManager
from raggg.pipeline.knowledge_import import mark_imports_indexed


def make_settings(root: Path) -> Settings:
    return Settings(
        project_root=root,
        waveda_root=None,
        waveda_help_root=root / "wavEDA_docs",
        waveda_example_root=None,
        obsidian_vault_root=root / "knowledge_base",
        data_dir=root / "data",
        embedding_model="local-hashed-vectors",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
    )


class KnowledgeManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_category_selects_recommended_default_priority(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge_base").mkdir()
            manager = KnowledgeManager(make_settings(root))

            theory_index = manager.category_combo.findData("06_theory_notes")
            manager.category_combo.setCurrentIndex(theory_index)

            self.assertEqual(manager.priority_combo.currentData(), 1)

    def test_custom_top_level_folder_is_available_as_target_node(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom = root / "knowledge_base" / "08_custom_physics"
            custom.mkdir(parents=True)

            manager = KnowledgeManager(make_settings(root))

            self.assertGreaterEqual(
                manager.category_combo.findData("08_custom_physics"), 0
            )
            manager.close()

    def test_user_edition_cannot_construct_manager(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            settings = Settings(**{**settings.__dict__, "app_edition": "user"})

            with self.assertRaises(PermissionError):
                KnowledgeManager(settings)

    def test_new_nested_subdir_is_created_selected_and_visible_in_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_root = root / "knowledge_base"
            kb_root.mkdir()
            manager = KnowledgeManager(make_settings(root))
            theory_index = manager.category_combo.findData("06_theory_notes")
            manager.category_combo.setCurrentIndex(theory_index)

            with patch(
                "raggg.desktop.knowledge_manager.QInputDialog.getText",
                return_value=("射频电路/芯片设计", True),
            ):
                manager._new_subdir()

            created = kb_root / "06_theory_notes" / "射频电路" / "芯片设计"
            self.assertTrue(created.is_dir())
            self.assertEqual(manager._subdir_value, "射频电路/芯片设计")
            self.assertEqual(
                Path(manager.tree.currentItem().data(0, Qt.UserRole)).resolve(),
                created.resolve(),
            )
            self.assertIn("射频电路/芯片设计", manager.target_path_label.text())
            manager.close()

    def test_invalid_parent_path_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge_base").mkdir()
            manager = KnowledgeManager(make_settings(root))

            with patch.object(QMessageBox, "warning") as warning:
                result = manager._validated_relative_parts(
                    "../outside", allow_nested=True
                )

            self.assertIsNone(result)
            warning.assert_called_once()
            manager.close()

    def test_import_archives_source_tracks_manifest_and_selects_output(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb_root = root / "knowledge_base"
            kb_root.mkdir()
            source = root / "射频理论资料.md"
            source.write_text("# 射频理论\n\n完整正文", encoding="utf-8")
            manager = KnowledgeManager(make_settings(root))
            theory_index = manager.category_combo.findData("06_theory_notes")
            manager.category_combo.setCurrentIndex(theory_index)
            manager._set_subdir("射频电路", "射频电路")
            manager.desc_edit.setText("射频理论资料")
            changes: list[bool] = []
            manager.knowledge_changed.connect(lambda: changes.append(True))

            with (
                patch(
                    "raggg.desktop.knowledge_manager.analyze_document",
                    return_value="分类: 理论笔记",
                ),
                patch.object(
                    QMessageBox, "question", return_value=QMessageBox.Yes
                ),
                patch.object(QMessageBox, "information"),
            ):
                imported = manager._import_file(str(source), "md")

            self.assertIsNotNone(imported)
            assert imported is not None
            self.assertTrue(imported.exists())
            self.assertEqual(imported.parent, kb_root / "06_theory_notes" / "射频电路")
            content = imported.read_text(encoding="utf-8")
            self.assertIn("source_archive:", content)
            archive_files = list((kb_root / ".source_files").rglob("*.md"))
            self.assertEqual(len(archive_files), 1)
            self.assertEqual(archive_files[0].read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            manifest = json.loads(
                (kb_root / ".imports" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest[-1]["output_path"], imported.relative_to(kb_root).as_posix())
            self.assertEqual(changes, [True])
            self.assertEqual(
                Path(manager.tree.currentItem().data(0, Qt.UserRole)).resolve(),
                imported.resolve(),
            )
            manager.close()

            restarted = KnowledgeManager(make_settings(root))
            self.assertIsNotNone(restarted.tree.currentItem())
            self.assertEqual(
                Path(restarted.tree.currentItem().data(0, Qt.UserRole)).resolve(),
                imported.resolve(),
            )
            restarted.close()

            self.assertEqual(mark_imports_indexed(kb_root), 1)
            updated_manifest = json.loads(
                (kb_root / ".imports" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(updated_manifest[-1]["index_status"], "indexed")
            self.assertIn("indexed_at", updated_manifest[-1])

    def test_duplicate_import_gets_unique_output_name(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge_base").mkdir()
            source = root / "guide.md"
            source.write_text("# Guide", encoding="utf-8")
            manager = KnowledgeManager(make_settings(root))
            manager._set_subdir("", "root")

            with (
                patch(
                    "raggg.desktop.knowledge_manager.analyze_document",
                    return_value="分类: 教程",
                ),
                patch.object(
                    QMessageBox, "question", return_value=QMessageBox.Yes
                ),
                patch.object(QMessageBox, "information"),
            ):
                first = manager._import_file(str(source), "md")
                second = manager._import_file(str(source), "md")

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            assert first is not None and second is not None
            self.assertEqual(first.name, "guide.md")
            self.assertEqual(second.name, "guide_2.md")
            manager.close()


if __name__ == "__main__":
    unittest.main()
