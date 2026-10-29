import unittest
from unittest.mock import Mock

from raggg.pipeline.rag_pipeline import RAGPipeline


class RAGPipelineStreamingTests(unittest.TestCase):
    def make_pipeline(self) -> RAGPipeline:
        pipeline = RAGPipeline.__new__(RAGPipeline)
        pipeline.client = Mock()
        return pipeline

    def test_forwards_stream_chunks_and_joins_answer(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(["波端口", "设置"])
        received: list[str] = []

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "question",
            [],
            received.append,
        )

        self.assertEqual(answer, "波端口设置")
        self.assertEqual(received, ["波端口", "设置"])
        self.assertIsNone(warning)

    def test_falls_back_to_complete_when_streaming_is_rejected(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.side_effect = RuntimeError("stream unsupported")
        pipeline.client.complete.return_value = "完整回答"
        received: list[str] = []

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "question",
            [],
            received.append,
        )

        self.assertEqual(answer, "完整回答")
        self.assertEqual(received, ["完整回答"])
        self.assertIsNone(warning)

    def test_english_stream_repairs_mixed_language_before_display(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(
            ["Open 端口结果", " and click 导出."]
        )
        pipeline.client.complete.return_value = (
            "Open Port Results and click Export."
        )
        received: list[str] = []

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "How do I export S-parameters?",
            [],
            received.append,
            fallback_answer="English fallback.",
            language="en",
        )

        self.assertEqual(answer, "Open Port Results and click Export.")
        self.assertEqual(received, ["Open "])
        self.assertNotRegex(answer, r"[\u4e00-\u9fff]")
        self.assertIsNone(warning)

    def test_english_only_chunks_are_forwarded_as_they_arrive(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(
            ["Open Port ", "Results and click Export."]
        )
        received: list[str] = []

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "How do I export S-parameters?",
            [],
            received.append,
            fallback_answer="English fallback.",
            language="en",
        )

        self.assertEqual(answer, "Open Port Results and click Export.")
        self.assertEqual(received, ["Open Port ", "Results and click Export."])
        self.assertIsNone(warning)

    def test_english_stream_error_after_han_returns_repaired_answer(self) -> None:
        pipeline = self.make_pipeline()

        def broken_stream():
            yield "Open 端口结果"
            raise RuntimeError("stream interrupted")

        pipeline.client.complete_stream.return_value = broken_stream()
        pipeline.client.complete.return_value = "Open Port Results."
        received: list[str] = []

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "How do I export S-parameters?",
            [],
            received.append,
            fallback_answer="English fallback.",
            language="en",
        )

        self.assertEqual(answer, "Open Port Results.")
        self.assertEqual(received, ["Open "])
        self.assertIsNotNone(warning)

    def test_english_stream_cancellation_returns_no_unsafe_partial_answer(
        self,
    ) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(
            ["Safe English prefix. ", "More English."]
        )
        received: list[str] = []
        cancelled = False

        def receive(chunk: str) -> None:
            nonlocal cancelled
            received.append(chunk)
            cancelled = True

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "How do I export S-parameters?",
            [],
            receive,
            should_cancel=lambda: cancelled,
            fallback_answer="English fallback.",
            language="en",
        )

        self.assertEqual(answer, "")
        self.assertEqual(received, ["Safe English prefix. "])
        self.assertIsNone(warning)
        pipeline.client.complete.assert_not_called()

    def test_cancellation_keeps_partial_answer_without_fallback(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.client.complete_stream.return_value = iter(["已经", "不应出现"])
        received: list[str] = []
        cancelled = False

        def receive(chunk: str) -> None:
            nonlocal cancelled
            received.append(chunk)
            cancelled = True

        answer, warning = pipeline._complete_streaming(
            "prompt",
            "question",
            [],
            receive,
            should_cancel=lambda: cancelled,
        )

        self.assertEqual(answer, "已经")
        self.assertEqual(received, ["已经"])
        self.assertIsNone(warning)
        pipeline.client.complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
