from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from raggg.desktop.image_index import ImageIndex
from raggg.desktop.rendering import markdown_to_html


class DesktopRenderingTests(unittest.TestCase):
    def test_adjacent_citations_render_as_clickable_superscripts(self) -> None:
        rendered = markdown_to_html("结论。[1][2]")

        self.assertIn("RAGGG_CITATION:1", rendered)
        self.assertIn("RAGGG_CITATION:2", rendered)
        self.assertEqual(rendered.count("<sup"), 2)

    def test_markdown_numeric_link_is_not_rewritten_as_citation(self) -> None:
        rendered = markdown_to_html("[1](https://example.com)")

        self.assertNotIn("RAGGG_CITATION", rendered)
        self.assertIn("[1](https://example.com)", rendered)

    def test_historical_citations_render_without_click_handler(self) -> None:
        rendered = markdown_to_html("结论。[1]", citations_clickable=False)

        self.assertIn("<sup", rendered)
        self.assertNotIn("RAGGG_CITATION", rendered)

    def test_ordered_list_resumes_number_after_intervening_paragraph(self) -> None:
        rendered = markdown_to_html("1. First\n\nParagraph\n\n2. Second")

        self.assertIn('<ol start="2">', rendered)

    def test_image_index_maps_relative_path_and_filename(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = (
                root
                / "wavEDA_docs"
                / "helpHtml"
                / "helpHtml"
                / "guide"
                / "images"
                / "port.png"
            )
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")

            index = ImageIndex(root)
            index.build()

            self.assertEqual(index.paths["guide/images/port.png"], str(image))
            self.assertEqual(index.paths["port.png"], str(image))

    def test_rendered_answer_image_uses_english_alt_text(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = (
                root
                / "wavEDA_docs"
                / "helpHtml"
                / "helpHtml"
                / "guide"
                / "images"
                / "port.png"
            )
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")

            with patch(
                "raggg.desktop.rendering.application_root",
                return_value=root,
            ), patch(
                "raggg.desktop.rendering.path_to_data_uri",
                return_value="data:image/png;base64,AA==",
            ):
                rendered = markdown_to_html("Image: ./images/port.png")

            self.assertIn('alt="Diagram"', rendered)
            self.assertNotRegex(
                rendered,
                r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]",
            )


if __name__ == "__main__":
    unittest.main()
