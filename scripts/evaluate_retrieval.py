"""检索质量评测脚本（A1/A2）。

用法：
    python scripts/evaluate_retrieval.py                # 默认评测集 + 全量输出
    python scripts/evaluate_retrieval.py --quiet        # 只看汇总数字
    python scripts/evaluate_retrieval.py --json out.json  # 结果存 JSON，便于 A/B 对比

指标：hit@1、hit@5、MRR（任一 expected_path 命中即算对）。
out_of_scope 题目不计入命中率，只打印最高分，用于标定 A6 的分数门槛。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.config import load_settings
from raggg.indexing.semantic_embeddings import create_embedding_model
from raggg.indexing.vector_store import VectorStore
from raggg.retrieval.retriever import Retriever

DEFAULT_EVAL = ROOT / "tests" / "fixtures" / "retrieval_eval.json"


def evaluate(
    eval_path: Path,
    top_k: int,
    quiet: bool,
    index_dir: Path | None,
    embedding: str | None,
) -> dict:
    settings = load_settings()
    model = create_embedding_model(embedding if embedding is not None else settings.embedding_model)
    resolved_index = index_dir or (settings.data_dir / "index")
    store = VectorStore.load(resolved_index, embedding_model=model)
    retriever = Retriever(store)
    print(f"嵌入模型: {model.model_id}  索引目录: {resolved_index}  chunks: {len(store.chunks)}")

    dataset = json.loads(eval_path.read_text(encoding="utf-8"))
    in_scope = [q for q in dataset["questions"] if not q.get("out_of_scope")]
    out_scope = [q for q in dataset["questions"] if q.get("out_of_scope")]

    hit1 = hit5 = 0
    rr_total = 0.0
    details = []
    for item in in_scope:
        question = item["question"]
        expected = set(item["expected_paths"])
        results = retriever.search(question, top_k=top_k)
        paths = [r.chunk.relative_path for r in results]
        first_hit_rank = next(
            (rank for rank, path in enumerate(paths, 1) if path in expected), None
        )
        if first_hit_rank == 1:
            hit1 += 1
        if first_hit_rank is not None:
            hit5 += 1
            rr_total += 1.0 / first_hit_rank
        details.append(
            {
                "id": item["id"],
                "question": question,
                "hit_rank": first_hit_rank,
                "top_paths": paths,
                "top_scores": [round(r.score, 4) for r in results],
            }
        )
        if not quiet:
            mark = {1: "HIT@1", None: "MISS"}.get(first_hit_rank, f"HIT@{first_hit_rank}")
            print(f"[{mark:6s}] #{item['id']:>2} {question}")
            if first_hit_rank != 1:
                for rank, result in enumerate(results, 1):
                    flag = ">>" if result.chunk.relative_path in expected else "  "
                    print(
                        f"    {flag} {rank}. {result.score:.4f} "
                        f"{result.chunk.title} [{result.chunk.relative_path}]"
                    )

    n = len(in_scope)
    summary = {
        "eval_set": str(eval_path),
        "top_k": top_k,
        "in_scope_questions": n,
        "hit@1": round(hit1 / n, 4),
        "hit@5": round(hit5 / n, 4),
        "mrr": round(rr_total / n, 4),
    }
    print("\n===== 汇总 =====")
    print(f"题目数: {n}  hit@1: {summary['hit@1']:.3f}  "
          f"hit@{top_k}: {summary[f'hit@5']:.3f}  MRR: {summary['mrr']:.3f}")

    if out_scope:
        print("\n===== out-of-scope（供 A6 门槛标定，不计入命中率）=====")
        oos = []
        for item in out_scope:
            results = retriever.search(item["question"], top_k=top_k)
            top = results[0] if results else None
            top_score = round(top.score, 4) if top else 0.0
            oos.append({"id": item["id"], "question": item["question"], "top_score": top_score})
            print(f"#{item['id']} top_score={top_score:.4f}  {item['question']}")
            if top and not quiet:
                print(f"    top1: {top.chunk.title} [{top.chunk.relative_path}]")
        summary["out_of_scope"] = oos

    summary["details"] = details
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="检索质量评测 (hit@1 / hit@5 / MRR)")
    parser.add_argument("--eval", type=Path, default=DEFAULT_EVAL, help="评测集 JSON 路径")
    parser.add_argument("--top-k", type=int, default=5, help="检索返回条数")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总数字")
    parser.add_argument("--json", type=Path, default=None, help="把结果写入 JSON 文件")
    parser.add_argument("--index-dir", type=Path, default=None,
                        help="索引目录（默认 data/index，A/B 对比时指向备用索引）")
    parser.add_argument("--embedding", default=None,
                        help="嵌入模型，如 local-hashed-vectors 或 fastembed:BAAI/bge-small-zh-v1.5")
    args = parser.parse_args()

    summary = evaluate(args.eval, args.top_k, args.quiet, args.index_dir, args.embedding)
    if args.json:
        args.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n结果已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
