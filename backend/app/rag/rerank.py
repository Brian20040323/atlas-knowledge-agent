"""T8-2: LLM Rerank — 召回候选后用 DeepSeek V4 Pro（可配）精排。

拓宽知识覆盖 ≠ 只换模型：Rerank 提升「已有文档」的排序质量；
知识库条目仍需上传/入库。失败时原序降级，不阻断检索。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings


def _snippet(hit: dict[str, Any], limit: int = 280) -> str:
    text = (hit.get("content") or hit.get("excerpt") or "").strip()
    title = (hit.get("title") or "").strip()
    body = f"【{title}】{text}" if title else text
    return body[:limit] + ("…" if len(body) > limit else "")


def _parse_order(raw: str, n: int) -> list[int] | None:
    """Parse model output into 0-based indices permutation (or prefix)."""
    text = (raw or "").strip()
    if not text:
        return None
    # Prefer JSON array
    try:
        # extract first [...] 
        m = re.search(r"\[[\s\d,]+\]", text)
        if m:
            arr = json.loads(m.group(0))
            if isinstance(arr, list) and arr:
                idxs = [int(x) for x in arr]
                return _normalize_idxs(idxs, n)
    except Exception:  # noqa: BLE001
        pass
    # Fallback: numbers in order
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if not nums:
        return None
    return _normalize_idxs(nums, n)


def _normalize_idxs(idxs: list[int], n: int) -> list[int] | None:
    """Accept 1-based or 0-based; return unique 0-based covering available."""
    if not idxs:
        return None
    # Heuristic: if any index == n or all >=1 and max==n → 1-based
    one_based = max(idxs) >= n or (min(idxs) >= 1 and 0 not in idxs)
    out: list[int] = []
    seen: set[int] = set()
    for x in idxs:
        i = x - 1 if one_based else x
        if 0 <= i < n and i not in seen:
            seen.add(i)
            out.append(i)
    if not out:
        return None
    # append missing in original order
    for i in range(n):
        if i not in seen:
            out.append(i)
    return out


async def llm_rerank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    top_k: int,
    trace_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rerank hits with chat model; on failure return original truncated list."""
    if not hits:
        return []
    settings = get_settings()
    if not getattr(settings, "rag_rerank_enabled", False):
        return hits[:top_k]
    if settings.use_mock or not (settings.llm_api_key or "").strip():
        return hits[:top_k]
    if len(hits) <= 1:
        return hits[:top_k]

    model = (getattr(settings, "rag_rerank_model", "") or "").strip() or settings.llm_model
    timeout = float(getattr(settings, "rag_rerank_timeout_seconds", 20.0) or 20.0)

    lines = []
    for i, h in enumerate(hits):
        lines.append(f"[{i}] score={h.get('score')} {_snippet(h)}")
    catalog = "\n".join(lines)

    system = (
        "你是检索重排序器。根据用户问题，按「回答该问题的相关度」从高到低重排候选片段。"
        "只输出一个 JSON 整数数组，元素为候选编号（方括号内的数字），不要解释。"
        "必须包含全部编号，或至少给出最相关的前若干个（可少于全部）。"
    )
    user = (
        f"用户问题：{query}\n\n"
        f"候选片段：\n{catalog}\n\n"
        f"请输出重排后的编号数组，例如 [2,0,1]。"
    )

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                if trace_meta is not None:
                    trace_meta["rerank_error"] = f"http_{resp.status_code}"
                return hits[:top_k]
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as exc:  # noqa: BLE001
        if trace_meta is not None:
            trace_meta["rerank_error"] = str(exc)[:160]
        return hits[:top_k]

    order = _parse_order(content, len(hits))
    if not order:
        if trace_meta is not None:
            trace_meta["rerank_error"] = "parse_failed"
            trace_meta["rerank_raw"] = content[:120]
        return hits[:top_k]

    reranked = []
    for rank, idx in enumerate(order):
        h = dict(hits[idx])
        h["rerank_rank"] = rank
        h["retrieval"] = f"{h.get('retrieval') or 'hybrid'}+rerank"
        # mild score bump by rank for downstream filters
        base = float(h.get("score") or 0)
        h["score"] = round(base + max(0, (len(order) - rank) * 0.05), 2)
        h["rerank_score"] = round(1.0 - rank / max(len(order), 1), 3)
        reranked.append(h)

    if trace_meta is not None:
        trace_meta["rerank_model"] = model
        trace_meta["rerank_order"] = order[:12]
        trace_meta["rerank_in"] = len(hits)
        trace_meta["rerank_out"] = min(top_k, len(reranked))

    return reranked[:top_k]
