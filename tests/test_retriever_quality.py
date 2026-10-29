from pathlib import Path
import unittest

from raggg.indexing.vector_store import VectorStore
from raggg.models import Chunk
from raggg.retrieval.retriever import Retriever


def make_chunk(index: int, relative_path: str) -> Chunk:
    return Chunk(
        id=str(index),
        source_type="obsidian_note",
        source_path=str(Path(relative_path)),
        relative_path=relative_path,
        title="波端口",
        section=f"设置 {index}",
        content="波端口 设置 方向",
        metadata={"priority": 4},
    )


class RetrieverQualityTests(unittest.TestCase):
    def test_retrieval_ignores_body_only_matches(self) -> None:
        chunks = [
            Chunk(
                id="heading-match",
                source_type="waveda_help",
                source_path="heading.md",
                relative_path="heading.md",
                title="WavEDA FAQ",
                section="如何导出 S 参数？",
                content="这里介绍端口结果和数据图。",
                metadata={"priority": 4},
            ),
            Chunk(
                id="body-only",
                source_type="waveda_help",
                source_path="body.md",
                relative_path="body.md",
                title="端口设置",
                section="如何设置端口？",
                content="正文提到如何导出 S 参数，但问题标题没有这些词。",
                metadata={"priority": 4},
            ),
        ]
        results = Retriever(VectorStore.from_chunks(chunks)).search("S参数如何导出", top_k=1)

        self.assertEqual(results[0].chunk.id, "heading-match")

    def test_question_heading_matches_both_word_orders(self) -> None:
        chunk = Chunk(
            id="export",
            source_type="waveda_help",
            source_path="faq.md",
            relative_path="faq.md",
            title="WavEDA FAQ",
            section="如何导出 S 参数，或者找到工程生成的 snp 文件？",
            content="正文内容只作为命中后的回答上下文。",
            metadata={"priority": 4},
        )
        retriever = Retriever(VectorStore.from_chunks([chunk]))

        for query in ("S参数如何导出", "如何导出S参数"):
            with self.subTest(query=query):
                self.assertEqual(retriever.search(query, top_k=1)[0].chunk.id, "export")

    def test_reordered_mixed_language_query_keeps_same_lexical_coverage(self) -> None:
        chunks = [
            Chunk(
                id="export",
                source_type="waveda_help",
                source_path="faq.md",
                relative_path="faq.md",
                title="WavEDA FAQ",
                section="S 参数怎么导出？",
                content="生成端口结果后，可以右键数据图导出 txt 或 csv 文件。",
                metadata={"priority": 4},
            )
        ]
        retriever = Retriever(VectorStore.from_chunks(chunks))

        forward = retriever.search("S参数如何导出", top_k=1)[0]
        reversed_query = retriever.search("如何导出S参数", top_k=1)[0]

        self.assertEqual(forward.chunk.id, "export")
        self.assertEqual(reversed_query.chunk.id, "export")
        self.assertAlmostEqual(forward.lexical_score, reversed_query.lexical_score)

    def test_limits_repeated_chunks_from_the_same_document(self) -> None:
        chunks = [
            make_chunk(1, "manual.md"),
            make_chunk(2, "manual.md"),
            make_chunk(3, "manual.md"),
            make_chunk(4, "tutorial.md"),
        ]
        retriever = Retriever(VectorStore.from_chunks(chunks))

        results = retriever.search("波端口怎么设置方向", top_k=3)
        paths = [result.chunk.relative_path for result in results]

        self.assertEqual(paths.count("manual.md"), 2)
        self.assertIn("tutorial.md", paths)

    def test_bm25_prefers_rare_term_match(self) -> None:
        """A4：BM25 的 IDF 应让稀有词命中的文档排在泛用词命中之前。"""
        common_doc = Chunk(
            id="c1",
            source_type="obsidian_note",
            source_path="common.md",
            relative_path="common.md",
            title="仿真",
            section="仿真",
            content="仿真 " * 200,
            metadata={},
        )
        rare_doc = Chunk(
            id="c2",
            source_type="obsidian_note",
            source_path="rare.md",
            relative_path="rare.md",
            title="色散",
            section="色散",
            content="磁色散 材料 设置",
            metadata={},
        )
        # 语料里塞满“仿真”，让“仿真”成为泛用词、“磁色散”保持稀有
        filler = [
            Chunk(
                id=f"f{index}",
                source_type="obsidian_note",
                source_path=f"filler{index}.md",
                relative_path=f"filler{index}.md",
                title="仿真",
                section="仿真",
                content="仿真 仿真 仿真",
                metadata={},
            )
            for index in range(20)
        ]
        retriever = Retriever(VectorStore.from_chunks([common_doc, rare_doc, *filler]))

        results = retriever.search("磁色散 仿真", top_k=5)

        self.assertEqual(results[0].chunk.relative_path, "rare.md")


if __name__ == "__main__":
    unittest.main()
