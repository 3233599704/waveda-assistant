from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from raggg.pipeline.source_watch import scan_source_tree, snapshot_changed


class SourceWatchTests(unittest.TestCase):
    def test_scan_returns_supported_source_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("markdown", encoding="utf-8")
            (root / "b.pdf").write_bytes(b"pdf")
            (root / "c.docx").write_bytes(b"docx")
            (root / "ignored.tmp").write_text("ignored", encoding="utf-8")

            snapshot = scan_source_tree(root)

            self.assertEqual(set(snapshot), {"a.md", "b.pdf", "c.docx"})

    def test_snapshot_changes_when_file_content_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "note.md"
            note.write_text("old", encoding="utf-8")
            before = scan_source_tree(root)

            note.write_text("new content", encoding="utf-8")
            after = scan_source_tree(root)

            self.assertTrue(snapshot_changed(before, after))

    def test_snapshot_changes_when_file_is_added(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = scan_source_tree(root)

            (root / "new.txt").write_text("new", encoding="utf-8")
            after = scan_source_tree(root)

            self.assertTrue(snapshot_changed(before, after))

    def test_missing_root_is_empty_snapshot(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "missing"

            self.assertEqual(scan_source_tree(root), {})


if __name__ == "__main__":
    unittest.main()
