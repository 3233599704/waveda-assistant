"""本地 ONNX 语义嵌入（A3）。

用 fastembed（ONNX Runtime，不依赖 PyTorch）加载中文语义模型，
替代 MD5 哈希袋词向量。默认模型 BAAI/bge-small-zh-v1.5（512 维，约 100MB），
首次使用自动下载模型到本地缓存。

`create_embedding_model()` 是工厂入口：任何时候 fastembed 不可用
（未安装、模型下载失败），都会回退到 HashedEmbeddingModel 并打印提示，
保证离线/便携环境永远可用。
"""

from __future__ import annotations

import numpy as np

from raggg.indexing.embeddings import EmbeddingModel, HashedEmbeddingModel

DEFAULT_SEMANTIC_MODEL = "BAAI/bge-small-zh-v1.5"
HASHED_MODEL_NAME = "local-hashed-vectors"


class OnnxEmbeddingModel:
    """fastembed/ONNX 语义嵌入，接口与 HashedEmbeddingModel 一致。"""

    def __init__(self, model_name: str = DEFAULT_SEMANTIC_MODEL) -> None:
        from fastembed import TextEmbedding  # 延迟导入：未安装 fastembed 时不影响哈希路径

        self.model_name = model_name
        self.model_id = f"fastembed:{model_name}"
        self._model = TextEmbedding(model_name=model_name)
        # 用一条探针文本确定维度，同时触发模型下载/加载
        self.dimensions = int(self.embed_text("dimension probe").shape[0])

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).astype(np.float32)

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = np.vstack(list(self._model.embed(texts)))
        return self._normalize(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        # BGE/E5 等检索模型的查询侧需要指令前缀，fastembed 的 query_embed 会自动加
        vector = np.vstack(list(self._model.query_embed([text])))
        return self._normalize(vector)[0]


def create_embedding_model(name: str | None) -> EmbeddingModel:
    """按配置名创建嵌入模型；语义模型不可用时回退哈希嵌入。

    - None / "local-hashed-vectors" → HashedEmbeddingModel
    - "fastembed:<model>" 或裸模型名（如 "BAAI/bge-small-zh-v1.5"）→ OnnxEmbeddingModel
    """
    if not name or name == HASHED_MODEL_NAME:
        return HashedEmbeddingModel()
    model_name = name.split(":", 1)[1] if name.startswith("fastembed:") else name
    try:
        return OnnxEmbeddingModel(model_name)
    except ImportError:
        print(
            f"[raggg] 未安装 fastembed，回退到哈希嵌入。"
            f"如需语义检索：pip install fastembed（当前配置 RAG_EMBEDDING_MODEL={name}）"
        )
    except Exception as exc:  # 模型下载失败、缓存损坏等
        print(f"[raggg] 语义嵌入模型 {model_name} 加载失败（{exc}），回退到哈希嵌入。")
    return HashedEmbeddingModel()
