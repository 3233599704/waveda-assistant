from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from raggg.config import Settings
from raggg.indexing.embeddings import EmbeddingModel
from raggg.indexing.semantic_embeddings import create_embedding_model
from raggg.indexing.vector_store import VectorStore, chunk_retrieval_text
from raggg.loaders.html_loader import iter_html_documents
from raggg.loaders.markdown_loader import (
    infer_physics_domain,
    iter_markdown_documents,
    knowledge_path_metadata,
)
from raggg.models import Chunk, Document
from raggg.pipeline.ingestion import _extract_docx_text, _extract_pdf_text
from raggg.preprocessing.chunker import chunk_document


SEMANTIC_INDEX_EXCLUDED_PATHS = {
    "04_error_cases/error_message_index.csv.md",
    "04_error_cases/raw_ui_messages.csv.md",
}
CHUNK_SCHEMA_VERSION = 2
EMBEDDING_SCHEMA_VERSION = 3


@dataclass(frozen=True)
class BuildReport:
    document_count: int
    chunk_count: int
    waveda_document_count: int
    obsidian_document_count: int
    data_dir: Path
    rebuilt_document_count: int = 0
    reused_document_count: int = 0
    embedded_chunk_count: int = 0


@dataclass(frozen=True)
class BuildProgress:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None


ProgressCallback = Callable[[BuildProgress], None]


def _report_progress(
    callback: ProgressCallback | None,
    stage: str,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if callback is not None:
        callback(BuildProgress(stage, message, current, total))


def _document_key(source_type: str, relative_path: str) -> str:
    return f"{source_type}:{relative_path}"


def _document_fingerprint(document: Document) -> str:
    payload = {
        "chunk_schema_version": CHUNK_SCHEMA_VERSION,
        "source_path": str(document.source_path),
        "title": document.title,
        "text": document.text,
        "links": document.links,
        "images": document.images,
        "metadata": document.metadata,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _document_manifest(
    documents: list[Document], fingerprints: dict[str, str]
) -> list[dict[str, str | int]]:
    return [
        {
            "source_type": doc.source_type,
            "source_path": str(doc.source_path),
            "relative_path": doc.relative_path,
            "title": doc.title,
            "fingerprint": fingerprints[_document_key(doc.source_type, doc.relative_path)],
            "chunk_schema_version": CHUNK_SCHEMA_VERSION,
        }
        for doc in documents
    ]


def _write_chunks(path: Path, chunks: list[Chunk]) -> None:
    path.write_text(
        json.dumps([chunk.to_dict() for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _load_reusable_chunks(data_dir: Path) -> tuple[dict[str, str], dict[str, list[Chunk]]]:
    manifest_data = _read_json(data_dir / "raw_manifest.json")
    chunks_data = _read_json(data_dir / "index" / "chunks.json")
    if not isinstance(manifest_data, list) or not isinstance(chunks_data, list):
        return {}, {}

    fingerprints: dict[str, str] = {}
    for item in manifest_data:
        if not isinstance(item, dict) or item.get("chunk_schema_version") != CHUNK_SCHEMA_VERSION:
            continue
        source_type = item.get("source_type")
        relative_path = item.get("relative_path")
        fingerprint = item.get("fingerprint")
        if all(isinstance(value, str) for value in (source_type, relative_path, fingerprint)):
            fingerprints[_document_key(source_type, relative_path)] = fingerprint

    chunks_by_document: dict[str, list[Chunk]] = {}
    try:
        chunks = [Chunk.from_dict(item) for item in chunks_data if isinstance(item, dict)]
    except TypeError:
        return {}, {}
    for chunk in chunks:
        key = _document_key(chunk.source_type, chunk.relative_path)
        chunks_by_document.setdefault(key, []).append(chunk)
    return fingerprints, chunks_by_document


def _load_reusable_vectors(data_dir: Path, model: EmbeddingModel) -> dict[str, np.ndarray]:
    meta = _read_json(data_dir / "index" / "build_meta.json")
    if not isinstance(meta, dict) or meta.get("embedding_schema_version") != EMBEDDING_SCHEMA_VERSION:
        return {}
    # 嵌入模型换了就必须全量重算，不能复用旧模型的向量
    if meta.get("embedding_model") != model.model_id:
        return {}
    try:
        store = VectorStore.load(data_dir / "index", embedding_model=model)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if len(store.chunks) != len(store.vectors):
        return {}
    return {chunk.id: store.vectors[index] for index, chunk in enumerate(store.chunks)}


def _build_incremental_vectors(
    chunks: list[Chunk], data_dir: Path, model: EmbeddingModel
) -> tuple[np.ndarray, int]:
    reusable = _load_reusable_vectors(data_dir, model)
    missing_chunks = [chunk for chunk in chunks if chunk.id not in reusable]
    embedded = model.embed_many([chunk_retrieval_text(chunk) for chunk in missing_chunks])
    for index, chunk in enumerate(missing_chunks):
        reusable[chunk.id] = embedded[index]
    if not chunks:
        return np.zeros((0, model.dimensions), dtype=np.float32), 0
    return np.vstack([reusable[chunk.id] for chunk in chunks]), len(missing_chunks)


def _iter_knowledge_base_documents(root: Path) -> list[Document]:
    documents = [
        document
        for document in iter_markdown_documents(root)
        if document.relative_path not in SEMANTIC_INDEX_EXCLUDED_PATHS
        and document.metadata.get("indexing", True)
    ]
    if not root.exists():
        return documents

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            text = _extract_pdf_text(path)
        elif suffix == ".docx":
            text = _extract_docx_text(path)
        else:
            continue
        relative_path = path.relative_to(root).as_posix()
        documents.append(
            Document(
                source_type="obsidian_note",
                source_path=path,
                relative_path=relative_path,
                title=path.stem,
                text=text,
                metadata={
                    "domain": "multiphysics",
                    "content_type": "document",
                    "has_formula": any(token in text for token in ("$$", "\\nabla", "\\partial")),
                    "has_wikilink": False,
                    "physics_domain": infer_physics_domain(relative_path),
                    **knowledge_path_metadata(relative_path),
                },
            )
        )
    return documents


def build_knowledge_base(
    settings: Settings,
    on_progress: ProgressCallback | None = None,
) -> BuildReport:
    if not settings.can_manage_knowledge:
        raise PermissionError("用户版无权重建知识库索引。")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _report_progress(on_progress, "scan", "正在扫描知识文档")
    documents = []
    waveda_docs = iter_html_documents(settings.waveda_help_root)
    obsidian_docs = _iter_knowledge_base_documents(settings.obsidian_vault_root)
    documents.extend(waveda_docs)
    documents.extend(obsidian_docs)

    _report_progress(
        on_progress,
        "chunk",
        "正在复用或切分文档",
    )
    previous_fingerprints, previous_chunks = _load_reusable_chunks(settings.data_dir)
    fingerprints: dict[str, str] = {}
    chunks: list[Chunk] = []
    rebuilt_document_count = 0
    reused_document_count = 0
    for document in documents:
        key = _document_key(document.source_type, document.relative_path)
        fingerprint = _document_fingerprint(document)
        fingerprints[key] = fingerprint
        if previous_fingerprints.get(key) == fingerprint and key in previous_chunks:
            chunks.extend(previous_chunks[key])
            reused_document_count += 1
        else:
            chunks.extend(chunk_document(document))
            rebuilt_document_count += 1

    _report_progress(
        on_progress,
        "embed",
        "正在生成向量",
    )
    embedding_model = create_embedding_model(settings.embedding_model)
    vectors, embedded_chunk_count = _build_incremental_vectors(
        chunks, settings.data_dir, embedding_model
    )

    _report_progress(on_progress, "save", "正在写入索引")
    (settings.data_dir / "raw_manifest.json").write_text(
        json.dumps(_document_manifest(documents, fingerprints), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_chunks(settings.data_dir / "processed_chunks.json", chunks)
    store = VectorStore(chunks=chunks, vectors=vectors, embedding_model=embedding_model)
    store.save(settings.data_dir / "index")
    (settings.data_dir / "index" / "build_meta.json").write_text(
        json.dumps(
            {
                "chunk_schema_version": CHUNK_SCHEMA_VERSION,
                "embedding_schema_version": EMBEDDING_SCHEMA_VERSION,
                "embedding_model": embedding_model.model_id,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = BuildReport(
        document_count=len(documents),
        chunk_count=len(chunks),
        waveda_document_count=len(waveda_docs),
        obsidian_document_count=len(obsidian_docs),
        data_dir=settings.data_dir,
        rebuilt_document_count=rebuilt_document_count,
        reused_document_count=reused_document_count,
        embedded_chunk_count=embedded_chunk_count,
    )
    _report_progress(
        on_progress,
        "complete",
        "索引构建完成",
        len(documents),
        len(documents),
    )
    return report
