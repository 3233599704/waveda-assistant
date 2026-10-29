from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from raggg.config import load_settings
from raggg.pipeline.rag_pipeline import RAGPipeline


QUESTIONS = [
    "波端口怎么设置？",
    "S 参数怎么导出？",
    "WavEDA 里的 PML 和吸收边界有什么关系？",
]


def main() -> int:
    pipeline = RAGPipeline(load_settings())
    for question in QUESTIONS:
        answer = pipeline.ask(question)
        print(f"\nQUESTION: {question}")
        print(answer.answer[:500])
        print("SOURCES:")
        for source in answer.sources[:3]:
            chunk = source.chunk
            print(f"- {chunk.title} | {chunk.source_type} | {chunk.relative_path} | score={source.score:.3f}")
        if not answer.sources:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
