"""Hybrid retrieval: lexical overlap + TF-IDF cosine (no LangChain / no heavy embedding model)."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable


_STOP = {
    "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
    "介绍", "一下", "问题", "相关", "的", "了", "吗", "呢", "是", "在",
}


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = re.findall(r"[a-z0-9_]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    for i in range(len(chinese) - 1):
        tokens.append(chinese[i] + chinese[i + 1])
    for i in range(len(chinese) - 2):
        tokens.append(chinese[i] + chinese[i + 1] + chinese[i + 2])
    return [t for t in tokens if t not in _STOP and len(t) >= 2]


def _tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    c = Counter(tokens)
    n = float(len(tokens))
    return {k: v / n for k, v in c.items()}


def build_idf(docs_tokens: Iterable[list[str]]) -> dict[str, float]:
    docs = list(docs_tokens)
    n = max(1, len(docs))
    df: Counter[str] = Counter()
    for toks in docs:
        df.update(set(toks))
    return {t: math.log((1 + n) / (1 + df[t])) + 1.0 for t in df}


def tfidf_vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = _tf(tokens)
    return {t: tf[t] * idf.get(t, 0.0) for t in tf}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def hybrid_score(
    lexical: float,
    query_tokens: list[str],
    doc_tokens: list[str],
    idf: dict[str, float],
    *,
    lexical_weight: float = 0.55,
    vector_weight: float = 0.45,
) -> float:
    """Combine keyword score with TF-IDF cosine (scaled to similar magnitude)."""
    qv = tfidf_vec(query_tokens, idf)
    dv = tfidf_vec(doc_tokens, idf)
    vec = cosine(qv, dv) * 12.0  # map [0,1] → ~[0,12] like lexical
    return lexical_weight * lexical + vector_weight * vec
