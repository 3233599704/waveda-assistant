"""
合并式索引重建：
- 保留源文件不存在的 chunk（外部 Obsidian vault / 外部 helpHtml）
- 从 kb_sources.yaml 重新加载仓库内文件，分块并向量化
- 合并两部分，保存新的 chunks.json + vectors.npy
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# 添加 src 到 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raggg.config import load_settings
from raggg.indexing.embeddings import HashedEmbeddingModel
from raggg.indexing.vector_store import VectorStore
from raggg.loaders.markdown_loader import iter_markdown_documents
from raggg.models import Chunk
from raggg.preprocessing.chunker import chunk_documents


def main() -> None:
    settings = load_settings()
    index_dir = settings.data_dir / "index"
    chunks_path = index_dir / "chunks.json"
    vectors_path = index_dir / "vectors.npy"

    # 1. 加载现有索引
    print("[1/4] 加载现有索引...")
    old_store = VectorStore.load(index_dir)
    print(f"  现有 chunks: {len(old_store.chunks)}")

    # 2. 分离：仓库内的丢弃重建，仓库外的保留
    repo_root = ROOT.resolve()
    preserved_chunks: list[Chunk] = []
    preserved_indices: list[int] = []
    dropped_count = 0

    for i, chunk in enumerate(old_store.chunks):
        sp = Path(chunk.source_path).resolve() if chunk.source_path else None
        # 源文件在仓库目录内 → 会被重建 → 丢弃旧版本
        # 源文件在仓库外（Obsidian vault / 外部安装目录）→ 保留
        if sp and str(sp).startswith(str(repo_root)):
            dropped_count += 1
        else:
            preserved_chunks.append(chunk)
            preserved_indices.append(i)

    # 统计保留的来源
    from collections import Counter
    preserved_sources = Counter()
    for c in preserved_chunks:
        sp = c.source_path or "(none)"
        # 只取顶层目录
        preserved_sources[sp[:60]] += 1

    print(f"[2/4] 保留外部 chunk: {len(preserved_chunks)}")
    print(f"  丢弃（仓库内重建）: {dropped_count}")
    print(f"  保留来源示例:")
    for src, cnt in preserved_sources.most_common(5):
        print(f"    [{cnt}] {src}")

    # 提取保留的向量
    if preserved_indices:
        preserved_vectors = old_store.vectors[preserved_indices]
    else:
        preserved_vectors = np.empty((0, 384), dtype=np.float32)

    # 3. 从仓库路径加载文档并分块
    print("[3/4] 从仓库路径重建 chunk...")
    all_docs = []
    for source in [
        ROOT / "knowledge_base/01_team_tutorials",
        ROOT / "knowledge_base/02_software_manual",
        ROOT / "knowledge_base/03_examples",
        ROOT / "knowledge_base/04_error_cases",
        ROOT / "knowledge_base/05_reference",
        ROOT / "knowledge_base/06_theory_notes",
        ROOT / "knowledge_base/07_scripting_automation_all",
    ]:
        if source.exists():
            docs = list(iter_markdown_documents(source))
            print(f"  {source.relative_to(ROOT)}: {len(docs)} documents")
            all_docs.extend(docs)

    new_chunks = chunk_documents(all_docs)
    print(f"  新建 chunks: {len(new_chunks)}")

    # 4. 向量化新 chunks，合并保存
    print("[4/4] 向量化并合并保存...")
    model = HashedEmbeddingModel()
    new_vectors = model.embed_many([c.content for c in new_chunks])

    all_chunks = preserved_chunks + new_chunks
    all_vectors = np.vstack([preserved_vectors, new_vectors]) if len(preserved_chunks) > 0 else new_vectors

    print(f"  最终 chunks: {len(all_chunks)} (保留 {len(preserved_chunks)} + 重建 {len(new_chunks)})")
    print(f"  向量矩阵: {all_vectors.shape}")

    # 备份旧索引
    backup_dir = index_dir / "backup"
    backup_dir.mkdir(exist_ok=True)
    import shutil
    shutil.copy2(chunks_path, backup_dir / "chunks.json")
    shutil.copy2(vectors_path, backup_dir / "vectors.npy")
    print(f"  旧索引已备份到 {backup_dir.relative_to(ROOT)}")

    # 保存
    store = VectorStore(chunks=all_chunks, vectors=all_vectors, embedding_model=model)
    store.save(index_dir)
    print("  保存完成！")


if __name__ == "__main__":
    main()
