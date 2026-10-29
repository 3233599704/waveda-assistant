import json
from dataclasses import replace
from pathlib import Path
import unittest

from raggg.config import load_settings
from raggg.i18n import TEXTS
from raggg.indexing.vector_store import VectorStore
from raggg.pipeline.rag_pipeline import RAGPipeline
from raggg.retrieval.english_query_rewriter import EnglishQueryRewriter
from raggg.retrieval.retriever import Retriever


ROOT = Path(__file__).resolve().parents[1]


class EnglishRetrievalLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = load_settings()
        cls.min_score = settings.retrieval_min_score
        cls.retriever = Retriever(
            VectorStore.load(settings.data_dir / "index")
        )
        fixture = ROOT / "tests" / "fixtures" / "english_retrieval_eval.json"
        cls.cases = json.loads(fixture.read_text(encoding="utf-8"))["questions"]
        cls.rewriter = EnglishQueryRewriter()
        cls.pipeline = RAGPipeline(
            replace(settings, llm_api_key="", retrieval_min_score=20.0)
        )

    def test_curated_english_questions_retrieve_expected_evidence(self) -> None:
        failures = []
        for case in self.cases:
            query = self.rewriter.rewrite(case["question"])
            results = self.retriever.search(query, top_k=8)
            retained = [
                result
                for result in results
                if result.bm25_raw >= self.min_score
            ]
            paths = [result.chunk.relative_path for result in retained]
            expected = [value.casefold() for value in case["expected"]]
            if not any(
                fragment in path.casefold()
                for fragment in expected
                for path in paths
            ):
                failures.append(
                    {
                        "question": case["question"],
                        "query": query,
                        "expected": case["expected"],
                        "paths": paths,
                        "scores": [
                            round(result.bm25_raw, 4)
                            for result in retained
                        ],
                    }
                )

        self.assertEqual(failures, [])

    def test_all_builtin_english_questions_answer_from_live_index(self) -> None:
        for key in (
            "quick_q1",
            "quick_q2",
            "quick_q3",
            "welcome_example_1",
            "welcome_example_2",
            "welcome_example_3",
        ):
            with self.subTest(key=key):
                question = TEXTS[key]["en"]
                answer = self.pipeline.ask(question)

                self.assertEqual(answer.question, question)
                self.assertTrue(answer.sources)
                self.assertTrue(
                    all(source.bm25_raw >= 20.0 for source in answer.sources)
                )
                self.assertNotIn("Insufficient evidence", answer.answer)
                self.assertNotRegex(
                    answer.answer,
                    (
                        r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
                        r"\U00020000-\U000323af]"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
