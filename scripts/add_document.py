#!/usr/bin/env python3
"""
waveda_rag 单文档增量追加工具
用法:
  python scripts/add_document.py <文件路径>
  python scripts/add_document.py knowledge_base/tutorials/新教程.md
  python scripts/add_document.py wavEDA_docs/extracted_pages/EM_Project/新页面.md

功能: 将单个Markdown文件切块、向量化，追加到现有索引，无需重建整个知识库。
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

# 将 src 加入路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from raggg.config import Settings
from raggg.indexing.vector_store import VectorStore
from raggg.preprocessing.chunker import MarkdownChunker
from raggg.models import Chunk

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def load_existing_chunks(store: VectorStore) -> list[dict]:
    """加载已存在的chunks元数据"""
    chunks_path = Path(store.data_dir) / "index" / "chunks.json"
    if chunks_path.exists():
        with open(chunks_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_chunks(store: VectorStore, chunks: list[dict]):
    """保存chunks到索引"""
    chunks_path = Path(store.data_dir) / "index" / "chunks.json"
    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"  [OK] chunks.json 已更新 ({len(chunks)} 条)")


def add_document(filepath: str):
    """将单个文档追加到知识库索引"""
    path = Path(filepath)
    if not path.exists():
        print(f"[ERROR] 文件不存在: {filepath}")
        sys.exit(1)

    if path.suffix not in (".md", ".html"):
        print(f"[ERROR] 不支持的文件类型: {path.suffix}，只支持 .md / .html")
        sys.exit(1)

    print(f"[1/4] 读取文件: {path.name}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 切块
    print(f"[2/4] 文本切块 (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")
    title = path.stem
    source_type = "obsidian_note" if "theory" in str(path) else "waveda_help"

    chunker = MarkdownChunker(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = chunker.split(content)

    # 加载设置和存储
    settings = Settings.from_env(PROJECT_ROOT)
    store = VectorStore(settings)

    # 加载已有chunks
    existing = load_existing_chunks(store)
    existing_count = len(existing)

    # 生成新chunks
    new_chunks = []
    for i, chunk_text in enumerate(chunks):
        chunk_dict = {
            "id": f"doc_{existing_count + i}",
            "title": title,
            "source_type": source_type,
            "relative_path": str(path.relative_to(PROJECT_ROOT)),
            "content": chunk_text,
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        new_chunks.append(chunk_dict)

    print(f"  生成 {len(new_chunks)} 个知识块")

    # 向量化新chunks
    print(f"[3/4] 向量化...")
    new_texts = [c["content"] for c in new_chunks]
    new_vectors = store.embed(new_texts)

    # 更新向量文件
    import numpy as np
    vectors_path = Path(store.data_dir) / "index" / "vectors.npy"
    if vectors_path.exists():
        old_vectors = np.load(vectors_path)
        merged_vectors = np.concatenate([old_vectors, new_vectors], axis=0)
    else:
        merged_vectors = new_vectors
    np.save(vectors_path, merged_vectors)
    print(f"  [OK] vectors.npy 已更新 ({merged_vectors.shape[0]} 条)")

    # 更新chunks
    existing.extend(new_chunks)
    save_chunks(store, existing)

    # 更新 raw_manifest
    manifest_path = Path(store.data_dir) / "raw_manifest.json"
    manifest = []
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    manifest.append({
        "source_type": source_type,
        "source_path": str(path.absolute()),
        "relative_path": str(path.relative_to(PROJECT_ROOT)),
        "title": title,
        "chunks_added": len(new_chunks),
    })
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  [OK] raw_manifest.json 已更新")

    print(f"\n[4/4] 完成! {path.name} 已加入知识库 ({len(new_chunks)} 个知识块)")
    print(f"  总知识块: {len(existing)}")
    print(f"\n  重启应用后在界面上点'重新载入索引'即可生效。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/add_document.py <文件路径>")
        print("示例: python scripts/add_document.py knowledge_base/tutorials/新教程.md")
        sys.exit(1)
    add_document(sys.argv[1])
