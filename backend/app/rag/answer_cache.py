"""In-memory answer cache for LOCAL KB hits (cost / latency ROI).

依据：规范文档 04 §2.5 — 高频制度问答缓存；文档变更时失效。
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

from app.rag.query_rewrite import rewrite_search_query

_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}
_KB_FINGERPRINT: str = ""


def _normalize_query(query: str) -> str:
    q = rewrite_search_query((query or "").strip())
    q = re.sub(r"\s+", " ", q).strip().lower()
    return q


def set_kb_fingerprint(fingerprint: str) -> None:
    global _KB_FINGERPRINT
    with _LOCK:
        if fingerprint != _KB_FINGERPRINT:
            _KB_FINGERPRINT = fingerprint
            _CACHE.clear()


def invalidate() -> None:
    """Drop all cached answers (call after knowledge learn/upload)."""
    with _LOCK:
        _CACHE.clear()
        global _KB_FINGERPRINT
        _KB_FINGERPRINT = ""


def compute_kb_fingerprint(documents: list[Any]) -> str:
    """Cheap fingerprint: count + max id + title hash."""
    if not documents:
        return "empty"
    max_id = 0
    titles: list[str] = []
    for d in documents:
        did = int(getattr(d, "id", 0) or 0)
        if did > max_id:
            max_id = did
        titles.append(str(getattr(d, "title", "") or ""))
    blob = f"{len(documents)}|{max_id}|{'|'.join(sorted(titles))}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


async def refresh_kb_fingerprint() -> str:
    """Load docs and update fingerprint (clears cache when KB changes)."""
    from app.db import crud
    from app.db.session import get_session_maker

    session_maker = get_session_maker()
    async with session_maker() as db:
        docs = await crud.list_documents(db, limit=500)
    fp = compute_kb_fingerprint(docs)
    set_kb_fingerprint(fp)
    return fp


def make_key(query: str, *, intent: str = "local") -> str:
    fp = _KB_FINGERPRINT or "nofp"
    return f"{intent}|{fp}|{_normalize_query(query)}"


def get(query: str, *, intent: str = "local") -> dict[str, Any] | None:
    key = make_key(query, intent=intent)
    with _LOCK:
        hit = _CACHE.get(key)
        return dict(hit) if hit else None


def put(
    query: str,
    answer: str,
    *,
    intent: str = "local",
    hit_titles: list[str] | None = None,
) -> None:
    if not answer or not answer.strip():
        return
    if intent != "local":
        return
    key = make_key(query, intent=intent)
    with _LOCK:
        if len(_CACHE) >= 256:
            # Drop arbitrary oldest-ish entries
            for k in list(_CACHE.keys())[:64]:
                _CACHE.pop(k, None)
        _CACHE[key] = {
            "answer": answer,
            "intent": intent,
            "hit_titles": list(hit_titles or []),
        }
