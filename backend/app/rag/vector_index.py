"""Local on-disk vector index for optional P3 retrieval (JSON, no FAISS/GPU)."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import ROOT_DIR
from app.rag.embeddings import EmbeddingBackend, get_embedding_backend
from app.rag.chunking import chunk_text

_INDEX_LOCK = threading.Lock()
_DIRTY = True  # force rebuild after process start / learn


def mark_vector_index_dirty() -> None:
    """Invalidate cached index (call after learn / ingest)."""
    global _DIRTY
    with _INDEX_LOCK:
        _DIRTY = True


def default_index_dir(configured: str = "") -> Path:
    raw = (configured or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (ROOT_DIR / p)
    return ROOT_DIR / "data" / "vector_index"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def corpus_fingerprint(documents: Iterable[Any], *, chunk_size: int, overlap: int, max_chunks: int) -> str:
    h = hashlib.sha256()
    h.update(f"{chunk_size}:{overlap}:{max_chunks}".encode())
    for doc in documents:
        doc_id = getattr(doc, "id", None)
        title = getattr(doc, "title", "") or ""
        content = getattr(doc, "content", "") or ""
        h.update(f"{doc_id}|{len(content)}|{title}\n".encode("utf-8", errors="ignore"))
    return h.hexdigest()[:32]


@dataclass
class VectorChunk:
    doc_id: int
    title: str
    text: str
    source_type: str
    embedding: list[float]


class LocalVectorIndex:
    """Persist chunk embeddings under data/vector_index/ (pure JSON)."""

    def __init__(self, index_dir: Path, backend: EmbeddingBackend) -> None:
        self.index_dir = index_dir
        self.backend = backend
        self.chunks: list[VectorChunk] = []
        self.fingerprint: str = ""
        self.provider: str = backend.name
        self.dim: int = backend.dim

    @property
    def meta_path(self) -> Path:
        return self.index_dir / "meta.json"

    @property
    def chunks_path(self) -> Path:
        return self.index_dir / "chunks.json"

    def load(self) -> bool:
        if not self.meta_path.exists() or not self.chunks_path.exists():
            return False
        try:
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            raw_chunks = json.loads(self.chunks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if meta.get("provider") != self.backend.name:
            return False
        self.fingerprint = str(meta.get("fingerprint") or "")
        self.dim = int(meta.get("dim") or self.backend.dim)
        self.provider = str(meta.get("provider") or self.backend.name)
        loaded: list[VectorChunk] = []
        for row in raw_chunks or []:
            emb = row.get("embedding") or []
            loaded.append(
                VectorChunk(
                    doc_id=int(row["doc_id"]),
                    title=str(row.get("title") or ""),
                    text=str(row.get("text") or ""),
                    source_type=str(row.get("source_type") or "text"),
                    embedding=[float(x) for x in emb],
                )
            )
        self.chunks = loaded
        return True

    def save(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "version": 1,
            "provider": self.backend.name,
            "dim": self.dim,
            "fingerprint": self.fingerprint,
            "chunk_count": len(self.chunks),
        }
        payload = [
            {
                "doc_id": c.doc_id,
                "title": c.title,
                "text": c.text,
                "source_type": c.source_type,
                "embedding": c.embedding,
            }
            for c in self.chunks
        ]
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.chunks_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def rebuild(
        self,
        documents: list[Any],
        *,
        chunk_size: int,
        overlap: int,
        max_chunks: int,
    ) -> None:
        fp = corpus_fingerprint(
            documents, chunk_size=chunk_size, overlap=overlap, max_chunks=max_chunks
        )
        texts: list[str] = []
        meta_rows: list[tuple[int, str, str, str]] = []
        for doc in documents:
            chunks = chunk_text(doc.content, chunk_size=chunk_size, overlap=overlap) or [
                (doc.content or "")[:500]
            ]
            chunks = chunks[:max_chunks]
            for ch in chunks:
                texts.append(f"{doc.title}\n{ch}")
                meta_rows.append(
                    (
                        int(doc.id),
                        str(doc.title or ""),
                        ch,
                        str(getattr(doc, "source_type", "text") or "text"),
                    )
                )
        embeddings = self.backend.embed_texts(texts) if texts else []
        if embeddings:
            self.dim = len(embeddings[0])
        built: list[VectorChunk] = []
        for (doc_id, title, text, source_type), emb in zip(meta_rows, embeddings):
            built.append(
                VectorChunk(
                    doc_id=doc_id,
                    title=title,
                    text=text,
                    source_type=source_type,
                    embedding=emb,
                )
            )
        self.chunks = built
        self.fingerprint = fp
        self.provider = self.backend.name
        self.save()

    def ensure(
        self,
        documents: list[Any],
        *,
        chunk_size: int,
        overlap: int,
        max_chunks: int,
        force: bool = False,
    ) -> None:
        global _DIRTY
        fp = corpus_fingerprint(
            documents, chunk_size=chunk_size, overlap=overlap, max_chunks=max_chunks
        )
        with _INDEX_LOCK:
            dirty = _DIRTY or force
            if not dirty and self.chunks and self.fingerprint == fp:
                return
            if not dirty and self.load() and self.fingerprint == fp:
                _DIRTY = False
                return
            self.rebuild(
                documents,
                chunk_size=chunk_size,
                overlap=overlap,
                max_chunks=max_chunks,
            )
            _DIRTY = False

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        min_cosine: float = 0.05,
    ) -> list[tuple[float, VectorChunk]]:
        if not self.chunks:
            return []
        q_emb = self.backend.embed_texts([query or ""])[0]
        scored: list[tuple[float, VectorChunk]] = []
        for ch in self.chunks:
            sim = _cosine(q_emb, ch.embedding)
            if sim >= min_cosine:
                scored.append((sim, ch))
        scored.sort(key=lambda x: x[0], reverse=True)
        # dedupe by doc: keep best chunk
        best: dict[int, tuple[float, VectorChunk]] = {}
        for sim, ch in scored:
            prev = best.get(ch.doc_id)
            if prev is None or sim > prev[0]:
                best[ch.doc_id] = (sim, ch)
        ranked = sorted(best.values(), key=lambda x: x[0], reverse=True)
        return ranked[: max(1, int(top_k))]


def build_index_from_settings(settings: Any) -> LocalVectorIndex:
    backend = get_embedding_backend(
        getattr(settings, "rag_embedding_provider", "hash"),
        dim=int(getattr(settings, "rag_embedding_dim", 256)),
        api_key=getattr(settings, "llm_api_key", ""),
        base_url=getattr(settings, "llm_base_url", ""),
        model=getattr(settings, "rag_embedding_model", "") or "text-embedding-3-small",
        timeout=float(getattr(settings, "llm_timeout_seconds", 30.0)),
    )
    index_dir = default_index_dir(getattr(settings, "rag_vector_index_dir", "") or "")
    return LocalVectorIndex(index_dir, backend)
