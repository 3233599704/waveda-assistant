from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from raggg.indexing.embeddings import tokenize
from raggg.indexing.vector_store import VectorStore, chunk_retrieval_text
from raggg.models import Chunk


WAVEDA_TERMS = {"waveda", "端口", "边界", "pml", "网格", "仿真", "菜单", "设置", "波端口", "集总端口", "脚本", "扫参", "xml", "matlab", "python", "批量", "scan", "sweep", "循环", "重试", "诊断", "退出码", "mesh", "sim", "export"}
FORMULA_TERMS = {"公式", "方程", "maxwell", "麦克斯韦", "推导", "积分", "微分", "边界条件"}
DEFINITION_TERMS = {"什么是", "是什么", "定义"}
GENERIC_TITLES = {
    "设置",
    "设计设置",
    "建模",
    "工具",
    "选项",
    "视图",
    "文件",
    "仿真",
    "电磁结果",
    "端口",
    "材料",
    "快照",
    "结果",
    "错误",
    "常见问题",
}

# BM25 参数（标准值）
BM25_K1 = 1.5
BM25_B = 0.75


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float
    vector_score: float
    lexical_score: float
    bm25_raw: float = 0.0


def _lexical_overlap(query_tokens: set[str], content: str) -> float:
    """词袋重合度。生产代码已改用 BM25，此函数保留给 .tmp/grid_search.py 复现实验。"""
    if not query_tokens:
        return 0.0
    content_tokens = set(tokenize(content))
    if not content_tokens:
        return 0.0
    token_score = len(query_tokens & content_tokens) / len(query_tokens)

    # Chinese bigrams are useful for precision, but some of them depend on
    # the order in which the user happened to phrase the question (for
    # example, ``数如`` appears in ``S参数如何导出`` but not in the reversed
    # wording).  Keep the bigram score while also measuring stable atoms:
    # ASCII words/numbers and individual CJK characters.  This prevents an
    # incidental cross-word bigram from lowering an otherwise equivalent
    # query's coverage.
    stable_query_tokens = {token for token in query_tokens if token.isascii() or len(token) == 1}
    stable_content_tokens = {token for token in content_tokens if token.isascii() or len(token) == 1}
    stable_score = (
        len(stable_query_tokens & stable_content_tokens) / len(stable_query_tokens)
        if stable_query_tokens
        else 0.0
    )
    return max(token_score, stable_score)


class Retriever:
    def __init__(self, store: VectorStore) -> None:
        self.store = store
        # Only question headings participate in retrieval. The selected
        # chunk still carries its full body as answer context.
        self._term_counts: list[Counter[str]] = []
        df: Counter[str] = Counter()
        doc_lengths: list[int] = []
        for chunk in store.chunks:
            counts = Counter(tokenize(chunk_retrieval_text(chunk)))
            self._term_counts.append(counts)
            doc_lengths.append(sum(counts.values()))
            for term in counts:
                df[term] += 1
        self._df = df
        self._doc_lengths = doc_lengths
        self._avgdl = (sum(doc_lengths) / len(doc_lengths)) if doc_lengths else 1.0

    def _bm25_scores(self, query_tokens: set[str]) -> np.ndarray:
        """每个 chunk 的 BM25 原始分（含 IDF 与长度归一）。"""
        scores = np.zeros(len(self._term_counts), dtype=np.float64)
        n_docs = len(self._term_counts)
        for token in query_tokens:
            df = self._df.get(token, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for index, counts in enumerate(self._term_counts):
                tf = counts.get(token, 0)
                if tf == 0:
                    continue
                norm = 1 - BM25_B + BM25_B * self._doc_lengths[index] / self._avgdl
                scores[index] += idf * tf * (BM25_K1 + 1) / (tf + BM25_K1 * norm)
        return scores

    @staticmethod
    def _min_max_normalize(scores: np.ndarray) -> np.ndarray:
        if len(scores) == 0:
            return scores
        low = float(scores.min())
        high = float(scores.max())
        if high <= low:
            return np.zeros_like(scores)
        return (scores - low) / (high - low)

    def search(self, query: str, top_k: int = 6) -> list[SearchResult]:
        if not self.store.chunks:
            return []
        query_vector = self.store.embedding_model.embed_query(query)
        vector_scores = self.store.vectors @ query_vector
        query_tokens = set(tokenize(query))
        query_lower = query.lower()

        lexical_raw = self._bm25_scores(query_tokens)
        lexical_scores = self._min_max_normalize(lexical_raw)

        results: list[SearchResult] = []
        for index, chunk in enumerate(self.store.chunks):
            question_heading = chunk_retrieval_text(chunk)
            vector_score = float(vector_scores[index]) if len(vector_scores) else 0.0
            lexical_score = float(lexical_scores[index])
            # 配比由评测集网格搜索标定（41 题，2026-07）：
            # 0.4 向量 + 0.6 BM25 在 hash/bge 两种嵌入下均为最优或并列最优。
            # 向量与 BM25 均基于问题标题，不让正文里的偶然词语影响命中。
            score = 0.4 * vector_score + 0.6 * lexical_score

            # 以下为领域硬编码加分。A7 消融实验结论（2026-07，41 题评测集）：
            # 全部删除后 hit@5 从 0.878 跌到 0.805（hash）/ 0.854→0.854 但 hit@1
            # 从 0.78 跌到 0.66（bge）。语义嵌入并不能替代这些规则，保留。
            # 优先级加权 (1-5, 默认3) — 高优先级文档获得额外得分
            priority = int(chunk.metadata.get("priority", 3))
            score *= 0.9 + 0.07 * priority  # priority=3 → 1.11x, priority=5 → 1.25x

            chunk_text_lower = question_heading.lower()
            is_helpful = chunk.source_type in ("waveda_help", "user_tutorial") or priority >= 4
            if is_helpful and any(term in query_lower for term in WAVEDA_TERMS):
                score += 0.08
            compact_query = query_lower.replace(" ", "").replace("？", "").replace("?", "")
            compact_title = question_heading.lower().replace(" ", "")
            title_tokens = set(tokenize(question_heading))
            if (
                is_helpful
                and len(title_tokens) >= 2
                and compact_title not in GENERIC_TITLES
                and compact_title in compact_query
            ):
                score += 0.45
            matched_special_terms = [
                term
                for term in WAVEDA_TERMS | FORMULA_TERMS
                if term in query_lower and term in chunk_text_lower
            ]
            score += 0.14 * len(matched_special_terms)
            if "pml" in query_lower and "pml" in chunk_text_lower:
                score += 0.3
            if "吸收边界" in query_lower and "吸收边界" in chunk_text_lower:
                score += 0.25
            if any(term in query_lower for term in DEFINITION_TERMS):
                if "是什么" in compact_title or compact_title in compact_query or compact_query in compact_title:
                    score += 0.45

            results.append(
                SearchResult(
                    chunk=chunk,
                    score=score,
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                    bm25_raw=float(lexical_raw[index]),
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        selected: list[SearchResult] = []
        per_document: dict[str, int] = {}
        for result in results:
            relative_path = result.chunk.relative_path
            if per_document.get(relative_path, 0) >= 2:
                continue
            selected.append(result)
            per_document[relative_path] = per_document.get(relative_path, 0) + 1
            if len(selected) >= top_k:
                break
        return selected
