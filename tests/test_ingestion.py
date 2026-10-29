from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import sys
import types
import zipfile

from raggg.config import Settings
from raggg.pipeline.ingestion import ingest_document


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


class IngestionTests(unittest.TestCase):
    def test_imports_markdown_into_imported_folder(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "new guide.md"
            source.write_text("# New Guide\n\ncontent", encoding="utf-8")

            report = ingest_document(make_settings(tmp_path), source)

            self.assertEqual(
                report.imported_path,
                tmp_path / "knowledge_base" / "05_reference" / "imported" / "new guide.md",
            )
            self.assertEqual(report.imported_path.read_text(encoding="utf-8"), "# New Guide\n\ncontent")
            self.assertEqual(report.source_format, "markdown")


    def test_converts_text_file_to_markdown(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "notes.txt"
            source.write_text("plain notes", encoding="utf-8")

            report = ingest_document(make_settings(tmp_path), source)

            self.assertEqual(report.imported_path.name, "notes.md")
            self.assertEqual(report.imported_path.read_text(encoding="utf-8"), "# notes\n\nplain notes\n")
            self.assertEqual(report.source_format, "text")

    def test_converts_docx_file_to_markdown(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "guide.docx"
            document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("word/document.xml", document_xml)

            report = ingest_document(make_settings(tmp_path), source)

            self.assertEqual(report.imported_path.name, "guide.md")
            self.assertEqual(
                report.imported_path.read_text(encoding="utf-8"),
                "# guide\n\nFirst paragraph\n\nSecond paragraph\n",
            )
            self.assertEqual(report.source_format, "word")

    def test_converts_pdf_file_to_markdown(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "paper.pdf"
            source.write_bytes(b"%PDF-test")
            fake_reader = Mock()
            fake_reader.pages = [
                Mock(extract_text=Mock(return_value="Page one")),
                Mock(extract_text=Mock(return_value="Page two")),
            ]
            fake_pypdf = types.SimpleNamespace(PdfReader=Mock(return_value=fake_reader))

            with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
                report = ingest_document(make_settings(tmp_path), source)

            self.assertEqual(report.imported_path.name, "paper.md")
            self.assertEqual(
                report.imported_path.read_text(encoding="utf-8"),
                "# paper\n\nPage one\n\nPage two\n",
            )
            self.assertEqual(report.source_format, "pdf")

    def test_pdf_import_reports_missing_dependency(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "paper.pdf"
            source.write_bytes(b"%PDF-test")

            with patch.dict(sys.modules, {"pypdf": None}):
                with self.assertRaisesRegex(RuntimeError, "pypdf"):
                    ingest_document(make_settings(tmp_path), source)

    def test_rejects_unsupported_extension(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "table.xlsx"
            source.write_bytes(b"not supported")

            with self.assertRaisesRegex(ValueError, "不支持"):
                ingest_document(make_settings(tmp_path), source)


    def test_avoids_overwriting_existing_import(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            imported = tmp_path / "knowledge_base" / "05_reference" / "imported"
            imported.mkdir(parents=True)
            (imported / "guide.md").write_text("old", encoding="utf-8")
            source = tmp_path / "guide.md"
            source.write_text("new", encoding="utf-8")

            report = ingest_document(make_settings(tmp_path), source)

            self.assertEqual(report.imported_path.name, "guide-2.md")
            self.assertEqual(report.imported_path.read_text(encoding="utf-8"), "new")
            self.assertEqual((imported / "guide.md").read_text(encoding="utf-8"), "old")


if __name__ == "__main__":
    unittest.main()
