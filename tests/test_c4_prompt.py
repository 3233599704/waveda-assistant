"""C4: Prompt 构建测试 — 验证格式、包含来源、正确处理空结果"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.generation.prompt_builder import build_local_answer, build_prompt
from raggg.retrieval.retriever import SearchResult


class _FakeChunk:
    def __init__(self, title: str, content: str, path: str = "test/doc.md",
                 source_type: str = "waveda_help") -> None:
        self.title = title
        self.content = content
        self.relative_path = path
        self.source_type = source_type
        self.section = title


def _make_result(title: str, content: str, score: float = 0.8) -> SearchResult:
    return SearchResult(
        chunk=_FakeChunk(title, content),
        score=score,
        vector_score=0.5,
        lexical_score=0.3,
    )


class PromptBuildingTests(unittest.TestCase):
    def test_attachment_context_is_separate_from_english_question(self) -> None:
        prompt = build_prompt(
            "How do I export S-parameters?",
            [],
            language="en",
            additional_context="附件内容：中文仿真记录",
        )

        self.assertIn("Question:How do I export S-parameters?", prompt)
        self.assertIn("User-provided attachment context:", prompt)
        self.assertIn("附件内容：中文仿真记录", prompt)

    def test_prompt_with_sources_contains_reference_label(self) -> None:
        sources = [_make_result("端口设置", "端口设置的详细步骤...")]
        prompt = build_prompt("端口怎么设置？", sources)
        self.assertIn("端口设置", prompt)
        self.assertIn("端口怎么设置？", prompt)

    def test_prompt_without_sources_graceful(self) -> None:
        prompt = build_prompt("端口怎么设置？", [])
        self.assertIsInstance(prompt, str)
        self.assertIn("端口怎么设置？", prompt)

    def test_prompt_contains_citation_instruction(self) -> None:
        prompt = build_prompt("问题", [_make_result("T", "C")])
        self.assertIn("[1]", prompt)
        self.assertIn("不得编造", prompt)

    def test_prompt_sources_are_numbered(self) -> None:
        results = [
            _make_result("DocA", "Content A"),
            _make_result("DocB", "Content B"),
        ]
        prompt = build_prompt("Q", results)
        self.assertIn("[1]", prompt)
        self.assertIn("[2]", prompt)

    def test_long_history_keeps_opening_memory_and_recent_turns(self) -> None:
        history = [
            (f"Question {index}", f"Answer {index} " + ("detail " * 80))
            for index in range(60)
        ]
        prompt = build_prompt("Current question", [], conversation_history=history)

        self.assertIn("Question 0", prompt)
        self.assertIn("Question 59", prompt)
        self.assertNotIn("Question 20", prompt)
        self.assertLess(len(prompt), 25_000)

    def test_local_answer_with_sources(self) -> None:
        sources = [_make_result("端口指南", "步骤一：打开界面...步骤二：设置参数...")]
        answer = build_local_answer("端口怎么设置？", sources)
        self.assertIn("端口指南", answer)
        self.assertIn("引用来源", answer)

    def test_local_answer_empty(self) -> None:
        answer = build_local_answer("问题", [])
        self.assertIn("没有足够依据", answer)

    def test_english_language_override_builds_english_prompt(self) -> None:
        prompt = build_prompt(
            "How do I set a port?",
            [],
            language="en",
        )

        self.assertIn("You are an English RAG assistant", prompt)
        self.assertIn("Citation rules:", prompt)
        self.assertIn("Question:", prompt)

    def test_chinese_language_override_remains_chinese(self) -> None:
        prompt = build_prompt("端口怎么设置？", [], language="zh")

        self.assertIn("引用规则", prompt)

    def test_english_local_no_source_answer_is_english(self) -> None:
        answer = build_local_answer("How?", [], language="en")

        self.assertEqual(
            answer,
            "Insufficient evidence in the knowledge base to answer this question.",
        )

    def test_english_local_answer_does_not_copy_chinese_source_text(self) -> None:
        sources = [
            _make_result(
                "㐀",
                "豈𠀀",
            )
        ]

        answer = build_local_answer("How do I export data?", sources, language="en")

        self.assertNotRegex(
            answer,
            r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]",
        )
        self.assertIn("[1]", answer)


if __name__ == "__main__":
    unittest.main()
