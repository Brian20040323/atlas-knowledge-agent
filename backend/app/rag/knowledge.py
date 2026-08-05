"""Knowledge base: self-learning storage and retrieval."""

from __future__ import annotations

import re
import time
import asyncio
from contextlib import nullcontext
from typing import Any, TYPE_CHECKING

from app.config import get_settings
from app.db import crud
from app.db.session import get_session_maker
from app.rag.chunking import chunk_text
from app.rag.ingest import validate_content_length
from app.rag.query_rewrite import rewrite_search_query
from app.rag.retriever import get_retriever

if TYPE_CHECKING:
    from app.observability.traces import AgentTrace

_LEARN_PREFIXES = ("记住：", "记住:", "学习：", "学习:", "请记住：", "请记住:", "记下：", "记下:")

_RECENT_DOC_HINT = re.compile(
    r"(刚上传|刚才导入|刚导入|刚导的|最近上传|最近导入|"
    r"这份文档|这篇文档|这个文档|这个文件|这份文件|导入的文档|"
    r"文档(里|中)?(有|讲|说|写)|文件内容|文档内容)"
)


def is_recent_doc_question(text: str) -> bool:
    """User is asking about a just-uploaded / current document rather than open-web facts."""
    return bool(_RECENT_DOC_HINT.search((text or "").strip()))


def parse_learn_intent(text: str) -> tuple[str, str] | None:
    """Parse '记住：标题|内容' or '记住：内容'."""
    stripped = text.strip()
    for prefix in _LEARN_PREFIXES:
        if stripped.startswith(prefix):
            body = stripped[len(prefix) :].strip()
            if not body:
                return None
            if "|" in body:
                title, content = body.split("|", 1)
                return title.strip()[:200] or "未命名知识", content.strip()
            if "：" in body:
                title, content = body.split("：", 1)
                if content.strip():
                    return title.strip()[:200], content.strip()
            if ":" in body:
                title, content = body.split(":", 1)
                if content.strip():
                    return title.strip()[:200], content.strip()
            return body[:50], body
    return None


def _tokenize(text: str) -> set[str]:
    """Tokenize for retrieval: English words + Chinese bigrams (no single chars)."""
    text = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}", text))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chinese) - 1):
        tokens.add(chinese[i] + chinese[i + 1])
    # Longer n-grams help entity names (大学名等)
    for i in range(len(chinese) - 2):
        tokens.add(chinese[i] + chinese[i + 1] + chinese[i + 2])
    return {t for t in tokens if t}


def _score(query: str, title: str, content: str) -> float:
    q = query.lower().strip()
    title_l = title.lower()
    content_l = content.lower()
    score = 0.0

    # Strong signals: whole query / multi-char parts in title or content
    if q and len(q) >= 4 and (q in title_l or q in content_l):
        score += 8.0
    for part in re.split(r"[\s，,。！？!?；;：:|]+", q):
        part = part.strip()
        if len(part) >= 3 and part in title_l:
            score += 4.0
        elif len(part) >= 3 and part in content_l:
            score += 2.0

    q_tokens = _tokenize(query)
    # Drop ultra-generic bigrams that match almost everything
    stop = {
        "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
        "介绍", "一下", "问题", "相关",
    }
    q_tokens = {t for t in q_tokens if t not in stop and len(t) >= 2}
    if not q_tokens:
        return score

    text = f"{title} {content}".lower()
    t_tokens = _tokenize(text)
    overlap = q_tokens & t_tokens
    # Prefer longer token matches
    overlap_score = sum(1.5 if len(t) >= 3 else 0.4 for t in overlap)
    title_tokens = _tokenize(title)
    title_hit = q_tokens & title_tokens
    title_bonus = sum(2.5 if len(t) >= 3 else 0.5 for t in title_hit)
    score += overlap_score + title_bonus

    # Penalize weak matches: few distinctive overlaps
    distinctive = {t for t in overlap if len(t) >= 3}
    if len(distinctive) == 0 and score < 8:
        score *= 0.25
    return score


def _best_chunk_score(query: str, title: str, content: str) -> tuple[float, str, int, int]:
    """Score document via best overlapping chunk; returns (score, best_chunk, chunk_index, total_chunks)."""
    chunks = chunk_text(content, chunk_size=280, overlap=40)
    if not chunks:
        return 0.0, "", -1, 0
    best_score = 0.0
    best_chunk = chunks[0]
    best_idx = 0
    for i, ch in enumerate(chunks):
        s = _score(query, title, ch)
        if s > best_score:
            best_score = s
            best_chunk = ch
            best_idx = i
    # Slight bonus for full-doc match so short docs still rank
    full = _score(query, title, content)
    if full > best_score:
        return full, content[:500], -1, len(chunks)  # -1 = full-doc match
    return best_score, best_chunk, best_idx, len(chunks)


class KnowledgeService:
    async def search(
        self,
        query: str,
        top_k: int = 6,
        *,
        prefer_ids: list[int] | None = None,
        trace: "AgentTrace | None" = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        settings = get_settings()
        scan_limit = max(1, int(settings.rag_scan_limit))
        top_k = max(1, min(int(top_k or 1), int(settings.rag_top_k_max)))
        chunk_size = max(64, int(settings.rag_chunk_size))
        overlap = max(0, min(int(settings.rag_chunk_overlap), chunk_size // 2))
        max_chunks = max(1, int(settings.rag_max_chunks_per_doc))
        t0 = time.perf_counter()

        original_query = (query or "").strip()
        query = rewrite_search_query(original_query)
        prefer: list[int] = []
        seen_pref: set[int] = set()
        for raw in prefer_ids or []:
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid in seen_pref:
                continue
            seen_pref.add(pid)
            prefer.append(pid)
            if len(prefer) >= 8:
                break

        scan_ctx = trace.span("retrieve_db_scan", scan_limit=scan_limit) if trace else nullcontext()
        with scan_ctx as scan_span:
            session_maker = get_session_maker()
            async with session_maker() as db:
                documents = await crud.list_documents(
                    db, limit=scan_limit, user_id=user_id
                )
                if prefer:
                    extra = await crud.get_documents_by_ids(
                        db, prefer, user_id=user_id
                    )
                    have = {d.id for d in documents}
                    for doc in reversed(extra):
                        if doc.id not in have:
                            documents.insert(0, doc)
                            have.add(doc.id)
            if scan_span is not None:
                scan_span.meta["docs_scanned"] = len(documents)
                if prefer:
                    scan_span.meta["prefer_ids"] = prefer

        vector_on = bool(settings.rag_vector_enabled)
        retriever = get_retriever(vector_on)
        rerank_on = bool(getattr(settings, "rag_rerank_enabled", False))
        cand_n = max(top_k, int(getattr(settings, "rag_rerank_candidates", 12) or 12))
        recall_k = cand_n if rerank_on else top_k

        score_ctx = (
            trace.span(
                "retrieve_score",
                query=(query or "")[:80],
                backend=retriever.name,
                rewritten=(query != original_query),
                original_query=(original_query[:80] if query != original_query else None),
            )
            if trace
            else nullcontext()
        )
        with score_ctx as score_span:
            # TF-IDF, FastEmbed and JSON index work are synchronous. Keep them
            # off FastAPI's event loop so concurrent SSE chats remain responsive.
            rank_uid = (
                int(user_id)
                if user_id is not None and int(user_id) > 0
                else None
            )
            results = await asyncio.to_thread(
                retriever.rank,
                query,
                documents,
                top_k=max(recall_k, len(prefer) + recall_k),
                chunk_size=chunk_size,
                overlap=overlap,
                max_chunks=max_chunks,
                settings=settings,
                lexical_scorer=_score,
                user_id=rank_uid,
            )

            # Composer 附加文档：强制注入本轮优先文档的最佳片段，避免被差旅等旧库顶掉
            if prefer:
                by_id = {d.id: d for d in documents}
                preferred_hits: list[dict[str, Any]] = []
                for pid in prefer:
                    doc = by_id.get(pid)
                    if not doc:
                        continue
                    sc, chunk, _ci, _ct = _best_chunk_score(
                        original_query or query,
                        doc.title or "",
                        doc.content or "",
                    )
                    body = (chunk or (doc.content or ""))[:1200]
                    if len(body.strip()) < 8:
                        continue
                    src = (getattr(doc, "source_type", None) or "document").lower()
                    preferred_hits.append(
                        {
                            "id": doc.id,
                            "title": doc.title or "",
                            "content": body,
                            "score": max(float(sc), 5.0) + 4.0,
                            "source": src,
                            "source_type": src,
                            "retrieval": "prefer_id",
                        }
                    )
                if preferred_hits:
                    seen = {h["id"] for h in preferred_hits}
                    rest = [h for h in results if h.get("id") not in seen]
                    results = preferred_hits + rest

            # 「刚上传的文档 / 这份文件讲什么」：关键词对不上英文原文时，强制带上最近用户文档
            if (not results or float(results[0].get("score") or 0) < 3.0) and _RECENT_DOC_HINT.search(
                original_query
            ):
                skip_src = {"auto_wiki", "faq_extract", "web"}
                recent_hits: list[dict[str, Any]] = []
                for doc in documents:
                    src = (getattr(doc, "source_type", None) or "").lower()
                    if src in skip_src:
                        continue
                    title = doc.title or ""
                    if title.endswith(" FAQ") or "FAQ" in title:
                        continue
                    body = (doc.content or "")[:1200]
                    if len(body.strip()) < 12:
                        continue
                    recent_hits.append(
                        {
                            "id": doc.id,
                            "title": title,
                            "content": body,
                            "score": 7.0,
                            "source": src or "document",
                            "source_type": src or "document",
                            "retrieval": "recent_upload",
                        }
                    )
                    if len(recent_hits) >= 3:
                        break
                if recent_hits:
                    seen = {h["id"] for h in recent_hits}
                    results = recent_hits + [h for h in results if h.get("id") not in seen]

            if score_span is not None:
                score_span.meta.update(
                    backend=retriever.name,
                    vector_enabled=vector_on,
                    docs_scanned=len(documents),
                    hits=len(results),
                    top_score=results[0]["score"] if results else 0,
                    retrieval=(results[0].get("retrieval") if results else retriever.name),
                    top_titles=[(r.get("title") or "")[:40] for r in results[:5]],
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                    recall_k=recall_k,
                    prefer_ids=prefer or None,
                )

        if rerank_on and results:
            rerank_meta: dict[str, Any] = {}
            rerank_ctx = (
                trace.span("retrieve_rerank", model=getattr(settings, "rag_rerank_model", ""))
                if trace
                else nullcontext()
            )
            with rerank_ctx as rerank_span:
                from app.rag.rerank import llm_rerank

                results = await llm_rerank(
                    query,
                    results,
                    top_k=top_k,
                    trace_meta=rerank_meta,
                )
                if rerank_span is not None:
                    rerank_span.meta.update(rerank_meta)
        else:
            results = results[:top_k]

        return results

    async def learn(
        self,
        title: str,
        content: str,
        source_type: str = "text",
        *,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        validate_content_length(content, settings.doc_max_chars)
        session_maker = get_session_maker()
        async with session_maker() as db:
            doc = await crud.create_document(
                db,
                title,
                content,
                source_type=source_type or "text",
                user_id=user_id,
            )
            await db.commit()
            await db.refresh(doc)
            saved = {
                "id": doc.id,
                "title": doc.title,
                "content": doc.content,
                "source_type": doc.source_type,
            }
        # P4: optional graph extract — failure must not break learn
        try:
            from app.rag.graph_extract import maybe_extract_after_learn

            await maybe_extract_after_learn(
                saved["id"], saved["title"], saved["content"], settings=settings
            )
        except Exception:  # noqa: BLE001
            pass
        # T8-3: FAQ extract companion doc — fail-soft
        try:
            from app.rag.faq_extract import maybe_extract_faq_after_learn

            faq_meta = await maybe_extract_faq_after_learn(
                saved["id"], saved["title"], saved["content"], settings=settings
            )
            if faq_meta.get("ok"):
                saved["faq"] = faq_meta
        except Exception:  # noqa: BLE001
            pass
        return saved

    async def list_all(
        self, limit: int = 50, *, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        session_maker = get_session_maker()
        async with session_maker() as db:
            documents = await crud.list_documents(db, limit=limit, user_id=user_id)
        return [
            {
                "id": d.id,
                "title": d.title,
                "content": d.content,
                "created_at": d.created_at.isoformat(),
            }
            for d in documents
        ]

    def format_context(self, hits: list[dict[str, Any]], *, max_chars: int = 1200) -> str:
        if not hits:
            return ""
        blocks = []
        for i, hit in enumerate(hits, 1):
            body = (hit.get("excerpt") or hit.get("content") or "").strip()
            if len(body) > max_chars:
                body = body[: max_chars - 1].rstrip() + "…"
            chunk_id = hit.get("chunk_id")
            chunk_total = hit.get("chunk_total", 0)
            if chunk_id is not None and chunk_id >= 0 and chunk_total:
                blocks.append(f"[{i}] 《{hit['title']}》第{chunk_id + 1}/{chunk_total}段\n{body}")
            elif chunk_id is not None and chunk_id >= 0:
                blocks.append(f"[{i}] 《{hit['title']}》第{chunk_id + 1}段\n{body}")
            else:
                blocks.append(f"[{i}] 《{hit['title']}》\n{body}")
        return "\n\n".join(blocks)
