from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from raggg.indexing.embeddings import EmbeddingModel, HashedEmbeddingModel
from raggg.models import Chunk


def chunk_retrieval_text(chunk: Chunk) -> str:
    """Return the question heading used for retrieval."""
    return (chunk.section or "").strip()


@dataclass
class VectorStore:
    chunks: list[Chunk]
    vectors: np.ndarray
    embedding_model: EmbeddingModel

    @classmethod
    def from_chunks(
        cls,
        chunks: list[Chunk],
        embedding_model: EmbeddingModel | None = None,
    ) -> "VectorStore":
        model = embedding_model or HashedEmbeddingModel()
        vectors = model.embed_many([chunk_retrieval_text(chunk) for chunk in chunks])
        return cls(chunks=chunks, vectors=vectors, embedding_model=model)

    def save(self, index_dir: Path) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "chunks.json").write_text(
            json.dumps([chunk.to_dict() for chunk in self.chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        np.save(index_dir / "vectors.npy", self.vectors)

    @classmethod
    def load(
        cls,
        index_dir: Path,
        embedding_model: EmbeddingModel | None = None,
    ) -> "VectorStore":
        model = embedding_model or HashedEmbeddingModel()
        chunks_data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
        chunks = [Chunk.from_dict(item) for item in chunks_data]
        vectors = np.load(index_dir / "vectors.npy")
        if vectors.ndim == 2 and vectors.shape[1] != model.dimensions:
            raise ValueError(
                f"索引向量维度 ({vectors.shape[1]}) 与嵌入模型 {model.model_id} "
                f"({model.dimensions}) 不一致，请用同一模型重建索引。"
            )
        return cls(chunks=chunks, vectors=vectors, embedding_model=model)
