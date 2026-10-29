import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from raggg.generation.llm_client import LLMCancelledError
from raggg.pipeline.rag_pipeline import RAGPipeline
from raggg.retrieval.retriever import SearchResult


def make_result(bm25_raw: float) -> SearchResult:
    return SearchResult(
        chunk=None,  # 过滤逻辑只看 bm25_raw，不触碰 chunk
        score=1.0,
        vector_score=0.5,
        lexical_score=0.5,
        bm25_raw=bm25_raw,
    )


class BuildRetrievalQueryTests(unittest.TestCase):
    """A5：只有追问才拼接历史，独立问题不被历史污染。"""

    def test_standalone_question_ignores_history(self) -> None:
        history = [("怎么设置波端口？", "……"), ("PML 边界怎么配？", "……")]
        query = RAGPipeline._build_retrieval_query("怎么创建一个棱柱？", history)
        self.assertEqual(query, "怎么创建一个棱柱？")

    def test_followup_includes_previous_question(self) -> None:
        history = [("怎么设置波端口？", "……")]
        query = RAGPipeline._build_retrieval_query("那这个和集总端口有什么区别？", history)
        self.assertEqual(query, "怎么设置波端口？\n那这个和集总端口有什么区别？")

    def test_very_short_followup_includes_previous_question(self) -> None:
        history = [("怎么设置波端口？", "……")]
        query = RAGPipeline._build_retrieval_query("为什么？", history)
        self.assertEqual(query, "怎么设置波端口？\n为什么？")

    def test_followup_uses_three_recent_distinct_questions(self) -> None:
        history = [
            ("最早的无关问题", "……"),
            ("周期边界怎么创建？", "……"),
            ("创建到 140 对为什么闪退？", "……"),
            ("有哪些排查方法？", "……"),
        ]
        query = RAGPipeline._build_retrieval_query("那需要改哪个设置？", history)

        self.assertEqual(
            query,
            "周期边界怎么创建？\n"
            "创建到 140 对为什么闪退？\n"
            "有哪些排查方法？\n"
            "那需要改哪个设置？",
        )
        self.assertNotIn("最早的无关问题", query)

    def test_empty_history_returns_question(self) -> None:
        query = RAGPipeline._build_retrieval_query("那怎么办？", [])
        self.assertEqual(query, "那怎么办？")

    def test_unrecognized_english_question_is_not_expanded(self) -> None:
        question = "Where is the project file saved?"

        query = RAGPipeline._build_retrieval_query(question, [])

        self.assertEqual(query, question)


class Bm25FloorFilterTests(unittest.TestCase):
    """A6：BM25 原始分门槛过滤不可靠命中。"""

    def test_below_floor_are_dropped(self) -> None:
        sources = [make_result(35.0), make_result(8.0), make_result(22.0)]
        kept = RAGPipeline._filter_by_bm25_floor(sources, 20.0)
        self.assertEqual([s.bm25_raw for s in kept], [35.0, 22.0])

    def test_zero_floor_disables_filter(self) -> None:
        sources = [make_result(0.0), make_result(1.0)]
        kept = RAGPipeline._filter_by_bm25_floor(sources, 0.0)
        self.assertEqual(len(kept), 2)

    def test_all_below_floor_returns_empty(self) -> None:
        sources = [make_result(3.0), make_result(1.5)]
        kept = RAGPipeline._filter_by_bm25_floor(sources, 20.0)
        self.assertEqual(kept, [])


class EnglishRewritePipelineTests(unittest.TestCase):
    def make_pipeline(self) -> RAGPipeline:
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.settings = SimpleNamespace(retrieval_min_score=20.0)
        pipeline.query_rewriter = Mock()
        pipeline.retriever = Mock()
        pipeline.retriever.search.return_value = []
        pipeline.client = Mock()
        pipeline.client.is_configured = False
        return pipeline

    def test_pipeline_uses_rewriter_output_for_search(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.query_rewriter.rewrite.return_value = "English\n中文检索"

        pipeline.ask("How do I export S-parameters?")

        pipeline.retriever.search.assert_called_once_with(
            "English\n中文检索",
            top_k=8,
        )

    def test_rewrite_cancellation_returns_cancelled_answer(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.query_rewriter.rewrite.side_effect = LLMCancelledError("cancelled")

        answer = pipeline.ask("How do I calculate cutoff?")

        self.assertTrue(answer.cancelled)
        self.assertEqual(answer.question, "How do I calculate cutoff?")
        pipeline.retriever.search.assert_not_called()

    def test_english_question_selects_english_answer_language(self) -> None:
        self.assertEqual(
            RAGPipeline._detect_answer_language("How do I set a port?"),
            "en",
        )

    def test_chinese_or_mixed_question_selects_chinese_answer_language(self) -> None:
        self.assertEqual(
            RAGPipeline._detect_answer_language("S 参数怎么导出？"),
            "zh",
        )


if __name__ == "__main__":
    unittest.main()
