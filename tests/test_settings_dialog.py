from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QFileDialog

from raggg.config import Settings
from raggg.desktop.settings_dialog import SettingsDialog, detect_waveda_subpaths
from raggg.theme import build_style


def make_settings(
    project_root: Path,
    *,
    waveda_root: Path | None = None,
    waveda_help_root: Path | None = None,
    waveda_example_root: Path | None = None,
) -> Settings:
    return Settings(
        project_root=project_root,
        waveda_root=waveda_root,
        waveda_help_root=(
            waveda_help_root
            or project_root / "wavEDA_docs" / "helpHtml" / "helpHtml"
        ),
        waveda_example_root=waveda_example_root,
        obsidian_vault_root=project_root / "knowledge_base",
        data_dir=project_root / "data",
        embedding_model="local-hashed-vectors",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="",
        llm_model="deepseek-chat",
    )


class SettingsDialogPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_dialog(self, settings: Settings) -> SettingsDialog:
        with patch.object(SettingsDialog, "_build_knowledge_base_tab"):
            return SettingsDialog(settings)

    def test_detects_help_and_example_folders_from_install_root(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            waveda_root = project_root / "WavEDA"
            help_root = waveda_root / "documentation" / "helpHtml"
            example_root = waveda_root / "Example"
            help_root.mkdir(parents=True)
            example_root.mkdir()

            detected_help, detected_example = detect_waveda_subpaths(
                waveda_root,
                project_root,
            )

            self.assertEqual(detected_help, help_root)
            self.assertEqual(detected_example, example_root)

    def test_auto_mode_grays_detected_paths_and_root_has_browse_button(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            settings = make_settings(project_root)
            dialog = self._make_dialog(settings)
            waveda_root = project_root / "WavEDA"
            help_root = waveda_root / "documentation" / "helpHtml"
            example_root = waveda_root / "Example"
            help_root.mkdir(parents=True)
            example_root.mkdir()

            with patch.object(
                QFileDialog,
                "getExistingDirectory",
                return_value=str(waveda_root),
            ):
                dialog.waveda_root_browse_button.click()

            self.assertTrue(dialog.waveda_auto_paths_check.isChecked())
            self.assertFalse(dialog.waveda_help_root_edit.isEnabled())
            self.assertFalse(dialog.waveda_example_root_edit.isEnabled())
            self.assertEqual(
                project_root / dialog.waveda_help_root_edit.text(),
                help_root,
            )
            self.assertEqual(
                project_root / dialog.waveda_example_root_edit.text(),
                example_root,
            )
            dialog.close()

    def test_special_install_can_enable_manual_subpaths(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            dialog = self._make_dialog(make_settings(project_root))

            dialog.waveda_auto_paths_check.setChecked(False)

            self.assertTrue(dialog.waveda_help_root_edit.isEnabled())
            self.assertTrue(dialog.waveda_example_root_edit.isEnabled())
            self.assertTrue(dialog.waveda_help_browse_button.isEnabled())
            self.assertTrue(dialog.waveda_example_browse_button.isEnabled())
            dialog.close()

    def test_dark_theme_applies_complete_dialog_and_control_styles(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "raggg.theme._current_theme",
            "dark",
        ):
            dialog = self._make_dialog(make_settings(Path(tmp)))
            style = dialog.styleSheet()

            self.assertIn("QDialog", style)
            self.assertIn("background: #0b1119", style)
            self.assertIn("color: #dce5f0", style)
            self.assertIn("QComboBox", style)
            self.assertIn("QTabWidget::pane", style)
            dialog.close()

    def test_api_key_context_menu_has_readable_palette_in_both_themes(self) -> None:
        expected = {
            "light": ("#f7fbfd", "#10202d"),
            "dark": ("#23344b", "#dce5f0"),
        }
        for theme, (background, text) in expected.items():
            with self.subTest(theme=theme), TemporaryDirectory() as tmp, patch(
                "raggg.theme._current_theme",
                theme,
            ):
                dialog = self._make_dialog(make_settings(Path(tmp)))
                menu = dialog.key_edit.createStandardContextMenu()
                menu.ensurePolished()

                self.assertEqual(
                    menu.palette().color(QPalette.Window).name(),
                    background,
                )
                self.assertEqual(
                    menu.palette().color(QPalette.Text).name(),
                    text,
                )
                action_text = " ".join(action.text() for action in menu.actions())
                self.assertIn("Copy", action_text)
                self.assertIn("Paste", action_text)

                menu.close()
                dialog.close()

    def test_global_menu_style_defines_selected_disabled_and_separator_states(
        self,
    ) -> None:
        expected_separators = {
            "light": "#c5d3dc",
            "dark": "#4b6078",
        }
        for theme, separator in expected_separators.items():
            with self.subTest(theme=theme), patch(
                "raggg.theme._current_theme",
                theme,
            ):
                style = build_style()

            self.assertIn("QMenu::item:selected", style)
            self.assertIn("QMenu::item:disabled", style)
            self.assertIn("QMenu::separator", style)
            self.assertIn(f"background: {separator};", style)

    def test_user_edition_shows_update_tab_without_maintenance_tabs(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = make_settings(Path(tmp))
            settings = Settings(**{**settings.__dict__, "app_edition": "user"})
            dialog = SettingsDialog(settings)
            tab_titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]

            self.assertIn("知识库更新", tab_titles)
            self.assertNotIn("知识库", tab_titles)
            self.assertNotIn("纠错审核", tab_titles)
            self.assertTrue(hasattr(dialog, "install_knowledge_package_btn"))
            dialog.close()

    def test_maintainer_edition_builds_maintenance_tabs(self) -> None:
        with TemporaryDirectory() as tmp, patch.object(
            SettingsDialog,
            "_build_knowledge_base_tab",
        ) as build_kb, patch.object(
            SettingsDialog,
            "_build_correction_review_tab",
        ) as build_review:
            SettingsDialog(make_settings(Path(tmp))).close()

        build_kb.assert_called_once_with()
        build_review.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
