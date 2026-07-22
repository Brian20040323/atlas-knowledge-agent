"""T8-3: 入库后用 LLM 抽取 FAQ，写成可检索附属文档。

拓宽覆盖 = 原文入库 + FAQ 问法入库；禁止编造原文没有的数字/条款。
失败 fail-soft，不影响主文档写入。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.db import crud
from app.db.session import get_session_maker

logger = logging.getLogger(__name__)


def _parse_faq_json(raw: str) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    # strip markdown fence
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    pairs: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or item.get("question") or item.get("query") or "").strip()
        a = str(item.get("a") or item.get("answer") or "").strip()
        if len(q) >= 2 and len(a) >= 2:
            pairs.append({"q": q[:200], "a": a[:800]})
    return pairs


def _format_faq_doc(source_title: str, pairs: list[dict[str, str]]) -> str:
    lines = [
        f"本文档由《{source_title}》自动抽取的常见问法，仅含原文依据内的信息。",
        "",
    ]
    for i, p in enumerate(pairs, 1):
        lines.append(f"Q{i}：{p['q']}")
        lines.append(f"A{i}：{p['a']}")
        lines.append("")
    return "\n".join(lines).strip()


async def _llm_extract_faq(
    title: str,
    content: str,
    *,
    settings: Settings,
    max_pairs: int,
) -> list[dict[str, str]]:
    if settings.use_mock or not (settings.llm_api_key or "").strip():
        return []
    model = (getattr(settings, "rag_faq_model", "") or "").strip() or settings.llm_model
    body_content = (content or "")[:3500]
    system = (
        "你是企业知识库 FAQ 抽取器。只根据给定原文生成问答对。"
        "禁止编造原文未出现的数字、额度、比例或制度条款。"
        f"最多 {max_pairs} 条。只输出 JSON 数组："
        '[{"q":"用户口语问法","a":"依据原文的简短回答"}]'
    )
    user = f"标题：{title}\n\n原文：\n{body_content}\n\n请输出 JSON 数组。"
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    timeout = float(getattr(settings, "llm_timeout_seconds", 90) or 90)
    async with httpx.AsyncClient(timeout=min(timeout, 60.0)) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.warning("faq extract http %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json()
        raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return _parse_faq_json(raw)[:max_pairs]


async def maybe_extract_faq_after_learn(
    doc_id: int,
    title: str,
    content: str,
    *,
    settings: Settings | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """After a document is saved, optionally create 《title》FAQ companion doc."""
    settings = settings or get_settings()
    result: dict[str, Any] = {"ok": False, "skipped": True, "faq_id": None, "pairs": 0}

    if not bool(getattr(settings, "rag_faq_extract_on_learn", True)):
        result["reason"] = "disabled"
        return result
    if settings.use_mock or not (settings.llm_api_key or "").strip():
        result["reason"] = "no_llm"
        return result

    title = (title or "").strip() or "未命名"
    content = (content or "").strip()
    if title.endswith("FAQ") or "常见问法" in title:
        result["reason"] = "already_faq"
        return result
    if len(content) < 40:
        result["reason"] = "too_short"
        return result

    max_pairs = max(1, min(int(getattr(settings, "rag_faq_max_pairs", 6) or 6), 12))
    try:
        pairs = await _llm_extract_faq(title, content, settings=settings, max_pairs=max_pairs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("faq extract failed for doc %s: %s", doc_id, exc)
        result["reason"] = "llm_error"
        result["error"] = str(exc)[:160]
        return result

    if not pairs:
        result["reason"] = "empty_pairs"
        return result

    faq_title = f"{title} FAQ"
    faq_body = _format_faq_doc(title, pairs)
    session_maker = get_session_maker()
    try:
        async with session_maker() as db:
            # Replace previous FAQ with same title if exists
            existing = await crud.list_documents(db, limit=200, user_id=user_id)
            old = next((d for d in existing if d.title == faq_title), None)
            if old is not None:
                old.content = faq_body
                old.source_type = "faq_extract"
                await db.commit()
                await db.refresh(old)
                faq_id = old.id
            else:
                doc = await crud.create_document(
                    db,
                    faq_title,
                    faq_body,
                    source_type="faq_extract",
                    user_id=user_id,
                )
                await db.commit()
                await db.refresh(doc)
                faq_id = doc.id
        try:
            from app.rag.answer_cache import invalidate

            invalidate()
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.rag.vector_index import mark_vector_index_dirty

            mark_vector_index_dirty()
        except Exception:  # noqa: BLE001
            pass
        result.update(
            {
                "ok": True,
                "skipped": False,
                "faq_id": faq_id,
                "pairs": len(pairs),
                "source_id": doc_id,
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("faq save failed: %s", exc)
        result["reason"] = "save_error"
        result["error"] = str(exc)[:160]
        return result
