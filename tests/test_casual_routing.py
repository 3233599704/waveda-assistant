import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from raggg.generation.llm_client import LLMCancelledError
from raggg.pipeline.rag_pipeline import RAGPipeline
from raggg.retrieval.english_query_rewriter import EnglishQueryRewriter


class CasualRoutingTests(unittest.TestCase):
    def make_pipeline(self) -> RAGPipeline:
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.settings = SimpleNamespace(retrieval_min_score=20.0)
        pipeline.retriever = Mock()
        pipeline.retriever.search.return_value = []
        pipeline.query_rewriter = Mock()
        pipeline.query_rewriter.rewrite.side_effect = (
            lambda query, should_cancel=None: query
        )
        pipeline.client = Mock()
        pipeline.client.is_configured = True
        return pipeline

    def test_casual_message_without_sources_uses_model(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(["你好", "呀！"])
        received: list[str] = []

        answer = pipeline.ask("姐妹你好香", on_chunk=received.append)

        self.assertEqual(answer.answer, "你好呀！")
        self.assertEqual(received, ["你好", "呀！"])
        self.assertEqual(answer.sources, [])
        pipeline.client.complete_stream.assert_called_once()

    def test_whitespace_attachment_context_still_retrieves_before_casual_routing(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete.return_value = "Hello!"

        answer = pipeline.ask("hello", additional_context="   ")

        self.assertEqual(answer.answer, "Hello!")
        pipeline.retriever.search.assert_called_once_with("hello", top_k=8)

    def test_non_streaming_english_answer_repairs_mixed_language_output(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete.side_effect = [
            "Open 端口结果 and click 导出.",
            "Open Port Results and click Export.",
        ]

        answer = pipeline.ask("hello")

        self.assertEqual(
            answer.answer,
            "Open Port Results and click Export.",
        )
        self.assertNotRegex(answer.answer, r"[\u4e00-\u9fff]")

    def test_english_answer_repairs_han_characters_outside_basic_cjk(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete.return_value = "English-only answer."

        for marker in ("㐀", "豈", "𠀀"):
            with self.subTest(marker=marker):
                answer = pipeline._enforce_answer_language(
                    f"Mixed {marker} output.",
                    language="en",
                    should_cancel=None,
                    fallback_answer="English fallback.",
                )

                self.assertEqual(answer, "English-only answer.")

    def test_invalid_or_failed_english_repair_uses_safe_fallback(self) -> None:
        pipeline = self.make_pipeline()

        for repair_result in (None, ["English"], "仍然是中文"):
            with self.subTest(repair_result=repair_result):
                pipeline.client.complete.reset_mock()
                pipeline.client.complete.return_value = repair_result
                answer = pipeline._enforce_answer_language(
                    "Mixed 中文 output.",
                    language="en",
                    should_cancel=None,
                    fallback_answer="English fallback.",
                )
                self.assertEqual(answer, "English fallback.")

        pipeline.client.complete.side_effect = RuntimeError("repair failed")
        self.assertEqual(
            pipeline._enforce_answer_language(
                "Mixed 中文 output.",
                language="en",
                should_cancel=None,
                fallback_answer="English fallback.",
            ),
            "English fallback.",
        )

    def test_english_repair_propagates_cancellation(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete.side_effect = LLMCancelledError("cancelled")

        with self.assertRaises(LLMCancelledError):
            pipeline._enforce_answer_language(
                "Mixed 中文 output.",
                language="en",
                should_cancel=lambda: True,
                fallback_answer="English fallback.",
            )

    def test_laughter_without_sources_is_casual(self) -> None:
        self.assertTrue(RAGPipeline._is_casual_message("hhh"))
        self.assertTrue(RAGPipeline._is_casual_message("哈哈哈哈"))

    def test_casual_followup_retrieves_context_before_casual_fallback(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(["哈哈，", "我在。"])
        pipeline.client.complete.return_value = "Haha, I am here."

        answer = pipeline.ask(
            "hhh",
            conversation_history=[("PML 怎么设置？", "在边界条件中设置。")],
            on_chunk=lambda _chunk: None,
        )

        self.assertEqual(answer.answer, "Haha, I am here.")
        retrieval_query = pipeline.retriever.search.call_args.args[0]
        self.assertIn("PML", retrieval_query)
        self.assertTrue(retrieval_query.endswith("\nhhh"))

    def test_return_to_first_question_setting_replays_exact_first_answer(self) -> None:
        pipeline = self.make_pipeline()
        original_answer = (
            "```html\n<html><body>完整的第一次回答，不能被摘要截断。</body></html>\n```"
        )
        history = [
            ("输出这个 HTML 的 SOP，并保留原设定", original_answer),
            ("边界条件怎么改？", "请修改边界条件。"),
        ]
        received: list[str] = []

        answer = pipeline.ask(
            "回到第一次提问的设定",
            conversation_history=history,
            on_chunk=received.append,
        )

        self.assertEqual(answer.answer, original_answer)
        self.assertEqual(received, [original_answer])
        self.assertEqual(answer.sources, [])
        pipeline.query_rewriter.rewrite.assert_not_called()
        pipeline.retriever.search.assert_not_called()
        pipeline.client.complete_stream.assert_not_called()

    def test_restate_first_question_returns_exact_question_text(self) -> None:
        pipeline = self.make_pipeline()
        original_question = "输出这个 HTML 的 SOP，并保留原设定"

        answer = pipeline.ask(
            "第一次提问是什么？",
            conversation_history=[(original_question, "第一次回答")],
        )

        self.assertEqual(answer.answer, original_question)
        pipeline.retriever.search.assert_not_called()

    def test_casual_looking_message_uses_grounded_prompt_when_faq_matches(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        source = SimpleNamespace(
            bm25_raw=25.0,
            chunk=SimpleNamespace(
                title="Correction FAQ",
                source_type="team_tutorial",
                relative_path="faq/correction.md",
                content="Use the correction action to submit improved guidance.",
            ),
        )
        pipeline.retriever.search.return_value = [source]
        pipeline.client.complete.return_value = "Use the correction action. [1]"

        answer = pipeline.ask("纠错")

        self.assertEqual(answer.answer, "Use the correction action. [1]")
        self.assertEqual(answer.sources, [source])
        prompt = pipeline.client.complete.call_args.args[0]
        self.assertIn("Correction FAQ", prompt)
        self.assertIn(
            "Use the correction action to submit improved guidance.",
            prompt,
        )
        self.assertIn("[1]", prompt)

    def test_short_technical_terms_are_not_classified_as_casual(self) -> None:
        for question in (
            "PML",
            "PEC",
            "S11",
            "wave port",
            "lumped port",
            "far field",
            "near field",
            "observer",
            "snapshot",
            "geometry",
            "domain",
            "meshing",
            "permittivity",
            "conductivity",
            "touchstone",
        ):
            with self.subTest(question=question):
                self.assertFalse(RAGPipeline._is_casual_message(question))

    def test_english_question_with_chinese_attachment_uses_original_query_and_language(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.is_configured = False
        question = "How do I export S-parameters?"

        answer = pipeline.ask(
            question,
            additional_context="附件内容：这里是中文仿真记录。",
        )

        pipeline.query_rewriter.rewrite.assert_called_once_with(
            question,
            should_cancel=None,
        )
        self.assertEqual(answer.question, question)
        self.assertEqual(
            answer.answer,
            "Insufficient evidence in the knowledge base to answer this question.",
        )

    def test_technical_question_without_sources_still_refuses(self) -> None:
        pipeline = self.make_pipeline()
        received: list[str] = []

        answer = pipeline.ask("WavEDA 中未知求解器怎么设置？", on_chunk=received.append)

        self.assertIn("资料中没有足够依据", answer.answer)
        self.assertEqual(received, [answer.answer])
        pipeline.client.complete_stream.assert_not_called()

    def test_model_rewrite_improves_retrieval_without_changing_english_prompt(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        pipeline.query_rewriter = EnglishQueryRewriter(
            lambda _prompt, _should_cancel: "波导模式 截止频率"
        )
        pipeline.retriever.search.return_value = [
            SimpleNamespace(
                bm25_raw=25.0,
                chunk=SimpleNamespace(
                    title="Waveguide",
                    source_type="waveda_help",
                    relative_path="Waveguide.md",
                    content="波导模式与截止频率说明。",
                ),
            )
        ]
        pipeline.client.complete.return_value = "Use the modal cutoff setup. [1]"
        question = "How do I calculate waveguide cutoff?"

        answer = pipeline.ask(question)

        retrieval_query = pipeline.retriever.search.call_args.args[0]
        prompt = pipeline.client.complete.call_args.args[0]
        self.assertIn("波导模式 截止频率", retrieval_query)
        self.assertIn(f"Question:{question}", prompt)
        self.assertEqual(answer.question, question)
        self.assertEqual(answer.answer, "Use the modal cutoff setup. [1]")


if __name__ == "__main__":
    unittest.main()
