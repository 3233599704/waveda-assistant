from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.config import load_settings
from raggg.pipeline.rag_pipeline import RAGPipeline


def main() -> int:
    pipeline = RAGPipeline(load_settings())
    queries = ["棱柱", "怎么设置棱柱？", "怎么创建棱柱？", "Prism 棱柱"]
    for query in queries:
        print("\nQUERY", query)
        for index, result in enumerate(pipeline.retriever.search(query, top_k=10), 1):
            chunk = result.chunk
            snippet = chunk.content[:100].replace("\n", " ")
            print(
                index,
                round(result.score, 3),
                chunk.source_type,
                chunk.title,
                chunk.relative_path,
                "|",
                snippet,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
