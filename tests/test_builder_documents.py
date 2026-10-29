from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

from raggg.config import Settings
from raggg.pipeline.builder import _iter_knowledge_base_documents, build_knowledge_base


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


def write_docx(path: Path, *paragraphs: str) -> None:
    body = "\n".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


class BuilderDocumentTests(unittest.TestCase):
    def test_excludes_non_indexed_framework_documents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge_base"
            root.mkdir()
            (root / "guide.md").write_text("# Real guide\n\nUseful", encoding="utf-8")
            (root / "_README.md").write_text(
                "---\nindexing: false\n---\n\n# Folder instructions",
                encoding="utf-8",
            )

            documents = _iter_knowledge_base_documents(root)

            self.assertEqual([document.relative_path for document in documents], ["guide.md"])

    def test_reuses_unchanged_documents_and_embeddings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "knowledge_base"
            kb.mkdir()
            first_path = kb / "first.md"
            first_path.write_text("# First\n\nPort setup", encoding="utf-8")
            (kb / "second.md").write_text("# Second\n\nMesh setup", encoding="utf-8")
            settings = make_settings(root)

            first_report = build_knowledge_base(settings)
            second_report = build_knowledge_base(settings)

            self.assertEqual(first_report.rebuilt_document_count, 2)
            self.assertEqual(first_report.embedded_chunk_count, first_report.chunk_count)
            self.assertEqual(second_report.rebuilt_document_count, 0)
            self.assertEqual(second_report.reused_document_count, 2)
            self.assertEqual(second_report.embedded_chunk_count, 0)

            first_path.write_text("# First\n\nUpdated port setup", encoding="utf-8")
            changed_report = build_knowledge_base(settings)

            self.assertEqual(changed_report.rebuilt_document_count, 1)
            self.assertEqual(changed_report.reused_document_count, 1)
            self.assertEqual(changed_report.embedded_chunk_count, 1)

    def test_excludes_raw_error_tables_from_semantic_index(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge_base"
            error_dir = root / "04_error_cases"
            error_dir.mkdir(parents=True)
            (error_dir / "error_message_index.md").write_text("# Curated\n\nUseful", encoding="utf-8")
            (error_dir / "error_message_index.csv.md").write_text("# Generated CSV", encoding="utf-8")
            (error_dir / "raw_ui_messages.csv.md").write_text("# Raw UI", encoding="utf-8")

            documents = _iter_knowledge_base_documents(root)
            relative_paths = {document.relative_path for document in documents}

            self.assertIn("04_error_cases/error_message_index.md", relative_paths)
            self.assertNotIn("04_error_cases/error_message_index.csv.md", relative_paths)
            self.assertNotIn("04_error_cases/raw_ui_messages.csv.md", relative_paths)

    def test_build_indexes_pdf_and_docx_files_in_knowledge_base(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "knowledge_base"
            kb.mkdir()
            write_docx(kb / "manual.docx", "DOCX paragraph")
            (kb / "paper.pdf").write_bytes(b"%PDF-test")
            fake_reader = Mock()
            fake_reader.pages = [Mock(extract_text=Mock(return_value="PDF paragraph"))]
            fake_pypdf = types.SimpleNamespace(PdfReader=Mock(return_value=fake_reader))

            with patch.dict(sys.modules, {"pypdf": fake_pypdf}):
                report = build_knowledge_base(make_settings(root))

            chunks = json.loads((root / "data" / "index" / "chunks.json").read_text(encoding="utf-8"))
            joined = "\n".join(chunk["content"] for chunk in chunks)
            self.assertEqual(report.obsidian_document_count, 2)
            self.assertIn("DOCX paragraph", joined)
            self.assertIn("PDF paragraph", joined)

    def test_build_reports_ordered_progress_stages(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            kb = root / "knowledge_base"
            kb.mkdir()
            (kb / "one.md").write_text("# One\n\nPort setup", encoding="utf-8")
            events = []

            build_knowledge_base(make_settings(root), on_progress=events.append)

            self.assertEqual(
                [event.stage for event in events],
                ["scan", "chunk", "embed", "save", "complete"],
            )
            self.assertTrue(all(event.message for event in events))
            stage_events = {event.stage: event for event in events}
            self.assertIsNone(stage_events["chunk"].current)
            self.assertIsNone(stage_events["embed"].current)


if __name__ == "__main__":
    unittest.main()
