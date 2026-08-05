"""Retrieval backends: TF-IDF hybrid (default) and optional vector hybrid (P3)."""

from __future__ import annotations

from typing import Any, Protocol

from app.rag.chunking import chunk_text
from app.rag.hybrid import build_idf, hybrid_score, tokenize as hybrid_tokenize
from app.rag.vector_index import LocalVectorIndex, build_index_from_settings


class RetrieverBackend(Protocol):
    name: str

    def rank(
        self,
        query: str,
        documents: list[Any],
        *,
        top_k: int,
        chunk_size: int,
        overlap: int,
        max_chunks: int,
        settings: Any | None = None,
        lexical_scorer: Any | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        ...


def _hit(
    *,
    doc: Any,
    body: str,
    score: float,
    lex: float,
    vec_part: float,
    retrieval: str,
    chunk_id: int = -1,
    chunk_total: int = 0,
) -> dict[str, Any]:
    excerpt = body[:300] + ("…" if len(body) > 300 else "")
    hit: dict[str, Any] = {
        "id": doc.id,
        "title": doc.title,
        "content": body,
        "excerpt": excerpt,
        "score": round(score, 2),
        "lexical_score": round(lex, 2),
        "vector_score": round(vec_part, 2),
        "source_type": getattr(doc, "source_type", "text") or "text",
        "retrieval": retrieval,
    }
    if chunk_id >= 0:
        hit["chunk_id"] = chunk_id
        hit["chunk_total"] = chunk_total
    return hit


class TfidfHybridRetriever:
    """Default P0–P2 path: lexical + in-memory TF-IDF cosine."""

    name = "tfidf"

    def rank(
        self,
        query: str,
        documents: list[Any],
        *,
        top_k: int,
        chunk_size: int,
        overlap: int,
        max_chunks: int,
        settings: Any | None = None,
        lexical_scorer: Any | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        del settings, user_id  # unused; signature shared with vector backend
        if lexical_scorer is None:
            raise ValueError("lexical_scorer required for TF-IDF retriever")

        corpus_tokens: list[list[str]] = []
        chunk_rows: list[tuple[Any, str, list[str], float, int, int]] = []
        for doc in documents:
            chunks = chunk_text(doc.content, chunk_size=chunk_size, overlap=overlap) or [
                doc.content[:500]
            ]
            chunks = chunks[:max_chunks]
            total = len(chunks)
            for ci, ch in enumerate(chunks):
                toks = hybrid_tokenize(f"{doc.title} {ch}")
                corpus_tokens.append(toks)
                lex = float(lexical_scorer(query, doc.title, ch))
                chunk_rows.append((doc, ch, toks, lex, ci, total))

        if not chunk_rows:
            return []

        idf = build_idf(corpus_tokens)
        q_tokens = hybrid_tokenize(query)
        scored: list[tuple[float, float, float, Any, str, int, int]] = []
        for doc, ch, toks, lex, ci, total in chunk_rows:
            overlap = set(q_tokens) & set(toks)
            if lex < 1.5 and not overlap:
                continue
            h = hybrid_score(lex, q_tokens, toks, idf)
            # 短关键词/缩写（如 FYP）lexical 够但 hybrid 会被压到 3 以下 → 放行精确命中
            keep = (
                h >= 2.2
                or (lex >= 2.5 and bool(overlap))
                or lex >= 4.0
            )
            if keep:
                scored.append((max(h, lex * 0.85), lex, h - lex, doc, ch, ci, total))

        best_by_doc: dict[int, tuple[float, float, float, Any, str, int, int]] = {}
        for row in scored:
            doc_id = row[3].id
            if doc_id not in best_by_doc or row[0] > best_by_doc[doc_id][0]:
                best_by_doc[doc_id] = row
        ranked = sorted(best_by_doc.values(), key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        for score, lex, vec_part, doc, best, chunk_ci, chunk_t in ranked[:top_k]:
            body = best or doc.content
            results.append(
                _hit(
                    doc=doc,
                    body=body,
                    score=score,
                    lex=lex,
                    vec_part=vec_part,
                    retrieval="hybrid",
                    chunk_id=chunk_ci,
                    chunk_total=chunk_t,
                )
            )
        return results


class VectorHybridRetriever:
    """
    Optional P3 path: lexical + local embedding cosine.

    Falls back to TF-IDF if index/embedding fails so the product stays usable.
    """

    name = "vector"

    def rank(
        self,
        query: str,
        documents: list[Any],
        *,
        top_k: int,
        chunk_size: int,
        overlap: int,
        max_chunks: int,
        settings: Any | None = None,
        lexical_scorer: Any | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if lexical_scorer is None:
            raise ValueError("lexical_scorer required for vector retriever")
        if settings is None:
            raise ValueError("settings required for vector retriever")

        try:
            index: LocalVectorIndex = build_index_from_settings(settings, user_id=user_id)
            index.ensure(
                documents,
                chunk_size=chunk_size,
                overlap=overlap,
                max_chunks=max_chunks,
            )
            vec_hits = index.search(query, top_k=max(top_k * 3, 12), min_cosine=0.02)
        except Exception:
            # Degrade to TF-IDF — vector is optional and must not break RAG
            return TfidfHybridRetriever().rank(
                query,
                documents,
                top_k=top_k,
                chunk_size=chunk_size,
                overlap=overlap,
                max_chunks=max_chunks,
                settings=settings,
                lexical_scorer=lexical_scorer,
                user_id=user_id,
            )

        docs_by_id = {int(d.id): d for d in documents}
        lex_w = float(getattr(settings, "rag_lexical_weight", 0.55))
        vec_w = float(getattr(settings, "rag_vector_weight", 0.45))
        total_w = lex_w + vec_w
        if total_w <= 1e-9:
            lex_w, vec_w = 0.55, 0.45
        else:
            lex_w, vec_w = lex_w / total_w, vec_w / total_w

        combined: list[tuple[float, float, float, Any, str, int, int]] = []
        for sim, ch in vec_hits:
            doc = docs_by_id.get(int(ch.doc_id))
            if doc is None:
                continue
            lex = float(lexical_scorer(query, ch.title or doc.title, ch.text))
            vec_part = sim * 12.0  # map [0,1] → ~[0,12] like TF-IDF hybrid
            score = lex_w * lex + vec_w * vec_part
            # Keep weak vector-only matches only if lexical isn't empty-noise
            if score < 2.5 and lex < 2.0 and sim < 0.12:
                continue
            # VectorChunk 无 chunk_index；用 -1 表示未知
            combined.append((score, lex, vec_part, doc, ch.text, -1, 0))

        # Also merge strong pure-lexical docs missed by embedding threshold
        seen = {row[3].id for row in combined}
        for doc in documents:
            if doc.id in seen:
                continue
            chunks = chunk_text(doc.content, chunk_size=chunk_size, overlap=overlap) or [
                doc.content[:500]
            ]
            best_lex = 0.0
            best_ch = chunks[0] if chunks else ""
            best_ci = 0
            for ci, ch in enumerate(chunks[:max_chunks]):
                s = float(lexical_scorer(query, doc.title, ch))
                if s > best_lex:
                    best_lex = s
                    best_ch = ch
                    best_ci = ci
            if best_lex >= 6.0:
                combined.append((best_lex * lex_w, best_lex, 0.0, doc, best_ch, best_ci, len(chunks[:max_chunks])))

        combined.sort(key=lambda x: x[0], reverse=True)
        results: list[dict[str, Any]] = []
        for score, lex, vec_part, doc, body, ch_id, ch_t in combined[:top_k]:
            results.append(
                _hit(
                    doc=doc,
                    body=body or doc.content,
                    score=score,
                    lex=lex,
                    vec_part=vec_part,
                    retrieval="dense+sparse-hybrid",
                    chunk_id=ch_id,
                    chunk_total=ch_t,
                )
            )
        return results


def get_retriever(vector_enabled: bool) -> RetrieverBackend:
    if vector_enabled:
        return VectorHybridRetriever()
    return TfidfHybridRetriever()
