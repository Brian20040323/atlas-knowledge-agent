"""P4 rule-based graph extraction (no LLM by default; fail-soft)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.db.session import get_session_maker
from app.rag.graph_schema import KNOWN_TERMS, RELATION_TYPES, SCHEMA_VERSION
from app.rag import graph_store

logger = logging.getLogger(__name__)

_IS_A = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff ·]{1,40}?)"
    r"\s*(?:是|属于|为)\s*"
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff ·]{1,60})"
)
_USES = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff ·]{1,40}?)"
    r"\s*(?:基于|使用|采用|依赖)\s*"
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff ·]{1,60})"
)
_LIST_ITEM = re.compile(
    r"(?:^|[;；\n])\s*(?:\d+[\)）.、]|[一二三四五六七八九十]+[、.）)]|\(\d+\))\s*"
    r"([^;；\n]{2,80})"
)
_EN_TERM = re.compile(r"\b([A-Z][A-Za-z0-9+/_-]{1,30}|[A-Z]{2,12})\b")
_CN_PHRASE = re.compile(r"[\u4e00-\u9fff]{2,12}")

_STOP = {
    "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
    "介绍", "一下", "问题", "相关", "核心", "知识", "内容", "包括", "以及",
    "适合", "构建", "应用", "开发", "学习", "回答", "用户", "目前", "材料",
}


@dataclass
class ExtractedTriple:
    from_name: str
    to_name: str
    rel_type: str
    evidence: str
    confidence: float
    from_type: str = "Concept"
    to_type: str = "Concept"


@dataclass
class ExtractPlan:
    entities: dict[str, str] = field(default_factory=dict)  # name -> type
    triples: list[ExtractedTriple] = field(default_factory=list)


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip(" ：:，,。.;；、|")).strip()[:200]


def _guess_type(name: str) -> str:
    key = name.lower().strip()
    if key in KNOWN_TERMS:
        return KNOWN_TERMS[key]
    for term, etype in KNOWN_TERMS.items():
        if term in key or key in term:
            return etype
    if re.search(r"[A-Za-z]", name):
        return "Technology"
    return "Concept"


def _add_entity(plan: ExtractPlan, name: str, entity_type: str | None = None) -> str | None:
    clean = _norm_name(name)
    if len(clean) < 2 or clean in _STOP:
        return None
    if clean.isdigit():
        return None
    etype = entity_type or _guess_type(clean)
    plan.entities.setdefault(clean, etype)
    return clean


def _add_triple(
    plan: ExtractPlan,
    frm: str,
    to: str,
    rel_type: str,
    evidence: str,
    confidence: float,
) -> None:
    a = _add_entity(plan, frm)
    b = _add_entity(plan, to)
    if not a or not b or a == b:
        return
    rel = rel_type if rel_type in RELATION_TYPES else "related_to"
    plan.triples.append(
        ExtractedTriple(
            from_name=a,
            to_name=b,
            rel_type=rel,
            evidence=(evidence or "")[:240],
            confidence=float(confidence),
            from_type=plan.entities.get(a, "Concept"),
            to_type=plan.entities.get(b, "Concept"),
        )
    )


def plan_extract(title: str, content: str, *, max_entities: int, max_relations: int) -> ExtractPlan:
    """Pure function: title+content → entities/triples (no I/O)."""
    plan = ExtractPlan()
    title_n = _add_entity(plan, title or "未命名", "Topic")
    text = f"{title or ''}\n{content or ''}"

    for m in _IS_A.finditer(text):
        _add_triple(plan, m.group(1), m.group(2), "is_a", m.group(0)[:200], 0.75)
    for m in _USES.finditer(text):
        _add_triple(plan, m.group(1), m.group(2), "uses", m.group(0)[:200], 0.7)

    if title_n:
        for m in _LIST_ITEM.finditer(text):
            item = _norm_name(m.group(1))
            # Keep leading keyword before punctuation
            item = re.split(r"[：:（(]", item, maxsplit=1)[0].strip()
            # Split "A 与 B" / "A / B"
            parts = re.split(r"[/、]|与|和|及", item)
            heads = [p for p in (parts if len(parts) > 1 else [item]) if p]
            for head in heads[:3]:
                head = _norm_name(head)
                if len(head) < 2:
                    continue
                # Prefer short concept labels
                if len(head) > 24:
                    head = head[:24]
                child = _add_entity(plan, head)
                if child and title_n:
                    _add_triple(plan, child, title_n, "part_of", m.group(0)[:200], 0.65)

    # Lexicon hits → mentions from title
    lower = text.lower()
    if title_n:
        for term, etype in KNOWN_TERMS.items():
            if term in lower or term in text:
                display = term.upper() if term.isascii() and len(term) <= 4 else term
                # Prefer casing from text for English
                en = re.search(re.escape(term), text, flags=re.I)
                if en:
                    display = en.group(0)
                ent = _add_entity(plan, display, etype)
                if ent and ent != title_n:
                    _add_triple(plan, title_n, ent, "mentions", term, 0.55)

    # English proper-ish tokens
    for m in _EN_TERM.finditer(text):
        tok = m.group(1)
        if tok.lower() in {"api", "id", "http", "url", "sse", "json"}:
            continue
        ent = _add_entity(plan, tok)
        if ent and title_n and ent != title_n:
            _add_triple(plan, title_n, ent, "mentions", tok, 0.5)

    # Cap
    names = list(plan.entities.keys())[: max(1, max_entities)]
    keep = set(names)
    plan.entities = {k: plan.entities[k] for k in names}
    capped: list[ExtractedTriple] = []
    for t in plan.triples:
        if t.from_name in keep and t.to_name in keep:
            capped.append(t)
        if len(capped) >= max_relations:
            break
    plan.triples = capped
    return plan


async def extract_document_to_graph(
    doc_id: int,
    title: str,
    content: str,
    *,
    settings: Settings | None = None,
    replace_doc_edges: bool = True,
) -> dict[str, Any]:
    """
    Extract entities/relations for one document into SQLite.
    Never raises to callers of the optional path — returns status dict.
    """
    settings = settings or get_settings()
    if not settings.rag_graph_enabled:
        return {"status": "graph_disabled", "entities": 0, "relations": 0}

    max_ent = max(1, int(settings.rag_graph_max_entities_per_doc))
    max_rel = max(1, int(settings.rag_graph_max_relations_per_doc))
    min_conf = float(settings.rag_graph_min_confidence)
    schema_v = int(settings.rag_graph_schema_version or SCHEMA_VERSION)

    try:
        plan = plan_extract(title, content, max_entities=max_ent, max_relations=max_rel)
        session_maker = get_session_maker()
        async with session_maker() as db:
            if replace_doc_edges and doc_id:
                await graph_store.delete_relations_for_doc(db, doc_id)

            name_to_id: dict[str, int] = {}
            for name, etype in plan.entities.items():
                ent = await graph_store.upsert_entity(
                    db,
                    name=name,
                    entity_type=etype,
                    source_doc_id=int(doc_id or 0),
                    schema_version=schema_v,
                )
                name_to_id[name] = ent.id

            rel_count = 0
            for t in plan.triples:
                if t.confidence < min_conf:
                    continue
                fid = name_to_id.get(t.from_name)
                tid = name_to_id.get(t.to_name)
                if not fid or not tid:
                    continue
                rel = await graph_store.add_relation(
                    db,
                    from_id=fid,
                    to_id=tid,
                    rel_type=t.rel_type,
                    evidence_span=t.evidence,
                    confidence=t.confidence,
                    source_doc_id=int(doc_id or 0),
                    schema_version=schema_v,
                )
                if rel is not None:
                    rel_count += 1

            await db.commit()
            return {
                "status": "ok",
                "document_id": doc_id,
                "entities": len(name_to_id),
                "relations": rel_count,
                "schema_version": schema_v,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph extract failed doc_id=%s: %s", doc_id, exc)
        return {"status": "error", "error": str(exc)[:200], "entities": 0, "relations": 0}


async def maybe_extract_after_learn(
    doc_id: int,
    title: str,
    content: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Hook for ingest/learn: no-op when graph off or extract-on-learn off."""
    settings = settings or get_settings()
    if not settings.rag_graph_enabled or not settings.rag_graph_extract_on_learn:
        return {"status": "skipped"}
    return await extract_document_to_graph(doc_id, title, content, settings=settings)


async def extract_all_documents(*, settings: Settings | None = None, limit: int = 200) -> dict[str, Any]:
    """Batch extract for eval / manual rebuild."""
    from app.db import crud

    settings = settings or get_settings()
    if not settings.rag_graph_enabled:
        return {"status": "graph_disabled", "documents": 0}

    session_maker = get_session_maker()
    async with session_maker() as db:
        docs = await crud.list_documents(db, limit=limit)
    ok = 0
    errors = 0
    entities = 0
    relations = 0
    for doc in docs:
        result = await extract_document_to_graph(
            doc.id, doc.title, doc.content, settings=settings
        )
        if result.get("status") == "ok":
            ok += 1
            entities += int(result.get("entities") or 0)
            relations += int(result.get("relations") or 0)
        elif result.get("status") == "error":
            errors += 1
    return {
        "status": "ok",
        "documents": ok,
        "errors": errors,
        "entities": entities,
        "relations": relations,
    }
