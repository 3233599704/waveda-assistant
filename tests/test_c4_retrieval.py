"""C4: 检索打分测试 — 基于评测集验证命中率 > 50%"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.config import load_settings
from raggg.indexing.vector_store import VectorStore
from raggg.retrieval.retriever import Retriever


class RetrievalScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = load_settings()
        cls.store = VectorStore.load(settings.data_dir / "index")
        cls.retriever = Retriever(cls.store)
        eval_path = ROOT / "tests" / "fixtures" / "retrieval_eval.json"
        cls.eval_data = json.loads(eval_path.read_text(encoding="utf-8"))

    def test_retriever_returns_results(self) -> None:
        """检索器对正常查询返回非空结果"""
        results = self.retriever.search("端口怎么设置", top_k=6)
        self.assertGreater(len(results), 0, "对基本查询应返回结果")

    def test_retriever_top_k_limit(self) -> None:
        results = self.retriever.search("端口", top_k=3)
        self.assertLessEqual(len(results), 3)

    def test_empty_query_does_not_crash(self) -> None:
        results = self.retriever.search("", top_k=5)
        self.assertIsInstance(results, list)

    def test_search_result_has_required_fields(self) -> None:
        results = self.retriever.search("PML 边界条件", top_k=5)
        for r in results:
            self.assertIsNotNone(r.chunk)
            self.assertIsNotNone(r.chunk.title)
            self.assertIsNotNone(r.chunk.content)
            self.assertGreater(r.score, 0, f"chunk '{r.chunk.title}' 得分为0")

    def test_eval_hit_rate_above_baseline(self) -> None:
        """评测集 hit@5 不低于基线水平"""
        hit_count = 0
        total = 0
        for q in self.eval_data.get("questions", []):
            if q.get("out_of_scope"):
                continue
            results = self.retriever.search(q["question"], top_k=5)
            expected = set(q.get("expected_paths", []))
            if not expected:
                continue
            total += 1
            returned_paths = {r.chunk.relative_path for r in results}
            if expected & returned_paths:
                hit_count += 1

        if total == 0:
            self.skipTest("评测集无可评题目")

        hit_rate = hit_count / total
        print(f"\n  hit@5 = {hit_count}/{total} = {hit_rate:.3f}")
        self.assertGreater(hit_rate, 0.5, f"hit@5={hit_rate:.3f} 低于 0.5 基线")


if __name__ == "__main__":
    unittest.main()
