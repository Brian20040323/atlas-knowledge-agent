"""P4 subgraph query + GraphRAG light fusion helpers."""

from __future__ import annotations

import logging
import re
from contextlib import nullcontext
from typing import Any, TYPE_CHECKING

from app.config import Settings, get_settings
from app.db.session import get_session_maker
from app.rag import graph_store
from app.rag.graph_schema import SCHEMA_VERSION

if TYPE_CHECKING:
    from app.observability.traces import AgentTrace

logger = logging.getLogger(__name__)


def _tokenize_query(text: str) -> set[str]:
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}", text))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chinese) - 1):
        tokens.add(chinese[i] + chinese[i + 1])
    for i in range(len(chinese) - 2):
        tokens.add(chinese[i] + chinese[i + 1] + chinese[i + 2])
    return {t for t in tokens if len(t) >= 2}


def _entity_matches(query: str, name: str, aliases: list[str]) -> float:
    q = (query or "").strip().lower()
    if not q:
        return 0.0
    candidates = [name] + list(aliases or [])
    best = 0.0
    q_tokens = _tokenize_query(query)
    for cand in candidates:
        c = (cand or "").strip()
        if not c:
            continue
        cl = c.lower()
        if cl in q or q in cl:
            best = max(best, 3.0 + min(len(c), 20) * 0.05)
            continue
        c_tokens = _tokenize_query(c)
        overlap = q_tokens & c_tokens
        if overlap:
            score = sum(1.2 if len(t) >= 3 else 0.4 for t in overlap)
            best = max(best, score)
    return best


async def search_subgraph(
    query: str,
    *,
    hops: int | None = None,
    top_k: int = 8,
    settings: Settings | None = None,
    trace: "AgentTrace | None" = None,
) -> dict[str, Any]:
    """
    Match entities from the question, expand k-hop neighborhood, serialize triples.
    When disabled or on failure: returns empty triples with status (never raises).
    """
    settings = settings or get_settings()
    if not settings.rag_graph_enabled:
        if trace is not None:
            with trace.span("graph_disabled", reason="RAG_GRAPH_ENABLED=false"):
                pass
        return {
            "status": "graph_disabled",
            "query": query,
            "triples": [],
            "entities": [],
            "count": 0,
            "schema_version": int(settings.rag_graph_schema_version or SCHEMA_VERSION),
        }

    hops = max(0, min(int(hops if hops is not None else settings.rag_graph_hops), 3))
    top_k = max(1, min(int(top_k or 8), 20))
    min_conf = float(settings.rag_graph_min_confidence)

    try:
        score_ctx = (
            trace.span("graph_query", query=(query or "")[:80], hops=hops)
            if trace
            else nullcontext()
        )
        with score_ctx as span:
            session_maker = get_session_maker()
            async with session_maker() as db:
                all_ents = await graph_store.list_entities(db, limit=500)
                scored: list[tuple[float, Any]] = []
                for ent in all_ents:
                    aliases: list[str] = []
                    try:
                        import json

                        raw_aliases = json.loads(ent.aliases or "[]")
                        if isinstance(raw_aliases, list):
                            aliases = [str(a) for a in raw_aliases]
                    except Exception:  # noqa: BLE001
                        aliases = []
                    score = _entity_matches(query, ent.name, aliases)
                    if score > 0:
                        scored.append((score, ent))
                scored.sort(key=lambda x: x[0], reverse=True)
                seeds = [e for _, e in scored[: max(1, min(top_k, 6))]]

                if not seeds:
                    if span is not None:
                        span.meta.update(hits=0, seeds=0)
                    return {
                        "status": "ok",
                        "query": query,
                        "triples": [],
                        "entities": [],
                        "count": 0,
                        "schema_version": int(
                            settings.rag_graph_schema_version or SCHEMA_VERSION
                        ),
                    }

                frontier = {e.id for e in seeds}
                visited = set(frontier)
                collected_rels: list[Any] = []
                for _ in range(max(0, hops)):
                    rels = await graph_store.list_relations_for_entities(
                        db, list(frontier), limit=400
                    )
                    next_ids: set[int] = set()
                    for rel in rels:
                        if float(rel.confidence or 0) < min_conf:
                            continue
                        collected_rels.append(rel)
                        for nid in (rel.from_id, rel.to_id):
                            if nid not in visited:
                                next_ids.add(nid)
                    visited |= next_ids
                    frontier = next_ids
                    if not frontier:
                        break

                if hops == 0:
                    collected_rels = await graph_store.list_relations_for_entities(
                        db, [e.id for e in seeds], limit=200
                    )
                    collected_rels = [
                        r
                        for r in collected_rels
                        if float(r.confidence or 0) >= min_conf
                    ]

                id_map = await graph_store.get_entities_by_ids(db, list(visited))
                seen_rel: set[tuple[int, int, str]] = set()
                triples: list[dict[str, Any]] = []
                for rel in collected_rels:
                    key = (rel.from_id, rel.to_id, rel.rel_type)
                    if key in seen_rel:
                        continue
                    seen_rel.add(key)
                    frm = id_map.get(rel.from_id)
                    to = id_map.get(rel.to_id)
                    if not frm or not to:
                        continue
                    triples.append(
                        {
                            "from": frm.name,
                            "from_type": frm.entity_type,
                            "to": to.name,
                            "to_type": to.entity_type,
                            "rel_type": rel.rel_type,
                            "evidence_span": rel.evidence_span,
                            "confidence": float(rel.confidence or 0),
                            "source_doc_id": rel.source_doc_id,
                            "schema_version": rel.schema_version,
                        }
                    )
                    if len(triples) >= top_k * 3:
                        break

                entities_out = [
                    {
                        "id": e.id,
                        "name": e.name,
                        "type": e.entity_type,
                        "score": next((s for s, ent in scored if ent.id == e.id), 0.0),
                    }
                    for e in seeds
                ]

                if span is not None:
                    span.meta.update(
                        seeds=len(seeds),
                        hops=hops,
                        triples=len(triples),
                        hits=len(triples),
                    )

                return {
                    "status": "ok",
                    "query": query,
                    "triples": triples,
                    "entities": entities_out,
                    "count": len(triples),
                    "schema_version": int(
                        settings.rag_graph_schema_version or SCHEMA_VERSION
                    ),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph query failed: %s", exc)
        if trace is not None:
            with trace.span("graph_query", error=True) as span:
                span.error = str(exc)[:160]
        return {
            "status": "error",
            "error": str(exc)[:200],
            "query": query,
            "triples": [],
            "entities": [],
            "count": 0,
        }


def triples_to_hits(triples: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Serialize triples into RAG-hit shaped dicts for synthesis / context fusion."""
    hits: list[dict[str, Any]] = []
    for t in triples[: max(1, limit)]:
        frm = t.get("from") or "?"
        to = t.get("to") or "?"
        rel = t.get("rel_type") or "related_to"
        evidence = (t.get("evidence_span") or "").strip()
        doc_id = int(t.get("source_doc_id") or 0)
        conf = float(t.get("confidence") or 0)
        body = f"({frm})-[{rel}]->({to})"
        if evidence:
            body += f"；依据片段：{evidence}"
        if doc_id:
            body += f"；document_id={doc_id}"
        hits.append(
            {
                "id": doc_id or None,
                "document_id": doc_id or None,
                "title": f"图谱关系：{frm} {rel} {to}",
                "content": body,
                "excerpt": body[:280],
                "score": round(5.0 + conf * 5.0, 3),
                "source_type": "graph",
                "source": "graph",
                "retrieval": "graph",
            }
        )
    return hits
