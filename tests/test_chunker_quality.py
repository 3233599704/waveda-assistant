from pathlib import Path
import unittest

from raggg.models import Document
from raggg.preprocessing.chunker import chunk_document


def make_document(text: str) -> Document:
    return Document(
        source_type="obsidian_note",
        source_path=Path("manual.md"),
        relative_path="02_software_manual/manual.md",
        title="Manual",
        text=text,
    )


class ChunkerQualityTests(unittest.TestCase):
    def test_removes_editorial_sections_and_keeps_following_content(self) -> None:
        document = make_document(
            """# Manual
## 正文抽取
## 设置步骤
先选择端口，再确认方向。
> 图示要点：`port.png` 后续审查通过后再补图。
## 页内/相关链接
- [锚点](#port)
## 常见问题
方向预览应朝外。
## 待补图片清单
| 图片 | 路径 |
| --- | --- |
| port.png | images/port.png |
"""
        )

        chunks = chunk_document(document)
        joined = "\n".join(chunk.content for chunk in chunks)

        self.assertIn("先选择端口", joined)
        self.assertIn("方向预览应朝外", joined)
        self.assertNotIn("正文抽取", joined)
        self.assertNotIn("页内/相关链接", joined)
        self.assertNotIn("待补图片清单", joined)
        self.assertNotIn("后续审查通过后再补图", joined)

    def test_does_not_emit_heading_only_chunks(self) -> None:
        chunks = chunk_document(make_document("# Manual\n## 设置步骤\n操作正文。"))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section, "设置步骤")
        self.assertIn("操作正文", chunks[0].content)


if __name__ == "__main__":
    unittest.main()
