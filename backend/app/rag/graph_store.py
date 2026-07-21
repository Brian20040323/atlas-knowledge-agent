"""SQLite property-graph persistence for P4 (entities + relations)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GraphEntity, GraphRelation
from app.rag.graph_schema import SCHEMA_VERSION


def _loads_list(raw: str | None) -> list[Any]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _dumps_list(items: list[Any]) -> str:
    return json.dumps(items, ensure_ascii=False)


def entity_to_dict(ent: GraphEntity) -> dict[str, Any]:
    return {
        "id": ent.id,
        "name": ent.name,
        "type": ent.entity_type,
        "aliases": _loads_list(ent.aliases),
        "source_doc_ids": [int(x) for x in _loads_list(ent.source_doc_ids) if str(x).isdigit() or isinstance(x, int)],
        "schema_version": ent.schema_version,
    }


def relation_to_dict(rel: GraphRelation) -> dict[str, Any]:
    return {
        "id": rel.id,
        "from_id": rel.from_id,
        "to_id": rel.to_id,
        "rel_type": rel.rel_type,
        "evidence_span": rel.evidence_span,
        "confidence": float(rel.confidence or 0),
        "source_doc_id": rel.source_doc_id,
        "schema_version": rel.schema_version,
    }


async def upsert_entity(
    session: AsyncSession,
    *,
    name: str,
    entity_type: str = "Concept",
    aliases: list[str] | None = None,
    source_doc_id: int = 0,
    schema_version: int = SCHEMA_VERSION,
) -> GraphEntity:
    clean = (name or "").strip()[:200]
    if not clean:
        raise ValueError("empty entity name")
    result = await session.execute(
        select(GraphEntity).where(GraphEntity.name == clean).limit(1)
    )
    ent = result.scalar_one_or_none()
    alias_set = {a.strip() for a in (aliases or []) if a and a.strip()}
    if ent is None:
        ent = GraphEntity(
            name=clean,
            entity_type=(entity_type or "Concept")[:40],
            aliases=_dumps_list(sorted(alias_set)[:20]),
            source_doc_ids=_dumps_list([source_doc_id] if source_doc_id else []),
            schema_version=schema_version,
        )
        session.add(ent)
        await session.flush()
        return ent

    existing_aliases = set(_loads_list(ent.aliases))
    existing_aliases |= alias_set
    ent.aliases = _dumps_list(sorted(existing_aliases)[:20])
    docs = set(int(x) for x in _loads_list(ent.source_doc_ids) if str(x).isdigit() or isinstance(x, int))
    if source_doc_id:
        docs.add(int(source_doc_id))
    ent.source_doc_ids = _dumps_list(sorted(docs)[:40])
    if entity_type and ent.entity_type == "Concept":
        ent.entity_type = entity_type[:40]
    await session.flush()
    return ent


async def add_relation(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
    rel_type: str,
    evidence_span: str = "",
    confidence: float = 0.5,
    source_doc_id: int = 0,
    schema_version: int = SCHEMA_VERSION,
) -> GraphRelation | None:
    if from_id == to_id:
        return None
    # Dedup identical edge from same doc
    result = await session.execute(
        select(GraphRelation)
        .where(
            GraphRelation.from_id == from_id,
            GraphRelation.to_id == to_id,
            GraphRelation.rel_type == (rel_type or "related_to")[:40],
            GraphRelation.source_doc_id == int(source_doc_id or 0),
        )
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if confidence > float(existing.confidence or 0):
            existing.confidence = float(confidence)
            existing.evidence_span = (evidence_span or existing.evidence_span)[:500]
            await session.flush()
        return existing

    rel = GraphRelation(
        from_id=from_id,
        to_id=to_id,
        rel_type=(rel_type or "related_to")[:40],
        evidence_span=(evidence_span or "")[:500],
        confidence=float(confidence),
        source_doc_id=int(source_doc_id or 0),
        schema_version=schema_version,
    )
    session.add(rel)
    await session.flush()
    return rel


async def delete_relations_for_doc(session: AsyncSession, doc_id: int) -> int:
    result = await session.execute(
        delete(GraphRelation).where(GraphRelation.source_doc_id == int(doc_id))
    )
    return int(result.rowcount or 0)


async def list_entities(session: AsyncSession, limit: int = 500) -> list[GraphEntity]:
    result = await session.execute(select(GraphEntity).limit(max(1, limit)))
    return list(result.scalars().all())


async def get_entities_by_ids(
    session: AsyncSession, ids: list[int]
) -> dict[int, GraphEntity]:
    if not ids:
        return {}
    result = await session.execute(select(GraphEntity).where(GraphEntity.id.in_(ids)))
    return {e.id: e for e in result.scalars().all()}


async def list_relations_for_entities(
    session: AsyncSession, entity_ids: list[int], limit: int = 400
) -> list[GraphRelation]:
    if not entity_ids:
        return []
    result = await session.execute(
        select(GraphRelation)
        .where(
            (GraphRelation.from_id.in_(entity_ids))
            | (GraphRelation.to_id.in_(entity_ids))
        )
        .limit(max(1, limit))
    )
    return list(result.scalars().all())


async def count_graph(session: AsyncSession) -> dict[str, int]:
    ents = await session.execute(select(GraphEntity.id))
    rels = await session.execute(select(GraphRelation.id))
    return {"entities": len(list(ents.scalars().all())), "relations": len(list(rels.scalars().all()))}
