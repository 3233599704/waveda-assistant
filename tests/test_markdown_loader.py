from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from raggg.loaders.markdown_loader import load_markdown_document


class MarkdownLoaderTests(unittest.TestCase):
    def test_indexing_false_is_exposed_in_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "placeholder.md"
            path.write_text("---\nindexing: false\n---\n\n# Placeholder", encoding="utf-8")

            document = load_markdown_document(path, root)

            self.assertFalse(document.metadata["indexing"])

    def test_frontmatter_priority_overrides_folder_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "05_reference" / "imported.md"
            path.parent.mkdir()
            path.write_text(
                "---\ncontent_kind: imported\npriority: 5\n---\n\n# Imported\n\nText",
                encoding="utf-8",
            )

            document = load_markdown_document(path, root)

            self.assertEqual(document.metadata["priority"], 5)
            self.assertEqual(document.metadata["content_type"], "imported")

    def test_invalid_priority_uses_folder_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "01_team_tutorials" / "guide.md"
            path.parent.mkdir()
            path.write_text("---\npriority: 99\n---\n\n# Guide\n\nText", encoding="utf-8")

            document = load_markdown_document(path, root)

            self.assertEqual(document.metadata["priority"], 5)

    def test_theory_notes_use_low_default_priority(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "06_theory_notes" / "theory.md"
            path.parent.mkdir()
            path.write_text("# Theory\n\nEquation", encoding="utf-8")

            document = load_markdown_document(path, root)

            self.assertEqual(document.metadata["priority"], 1)
            self.assertEqual(document.metadata["knowledge_layer"], "theory_note")

    def test_physics_domain_is_inferred_from_framework_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "02_software_manual" / "Thermal_Project" / "Boundary.md"
            path.parent.mkdir(parents=True)
            path.write_text("# Thermal boundary", encoding="utf-8")

            document = load_markdown_document(path, root)

            self.assertEqual(document.metadata["physics_domain"], "thermal")


if __name__ == "__main__":
    unittest.main()
