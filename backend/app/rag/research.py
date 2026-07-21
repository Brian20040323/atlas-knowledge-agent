"""Multi-aspect research + autonomous learning from open web sources."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.db import crud
from app.db.session import get_session_maker

# Domains Atlas can expand into when researching a topic
DOMAIN_FACETS: list[tuple[str, tuple[str, ...], str]] = [
    ("地理", ("地理", "位置", "气候", "地形", "国家", "城市", "河流", "山脉", "海洋"), "地理"),
    ("历史", ("历史", "朝代", "战争", "年代", "古代", "近代", "事件", "人物传记"), "历史"),
    ("数学", ("数学", "公式", "定理", "方程", "几何", "代数", "概率", "微积分"), "数学"),
    ("科学", ("物理", "化学", "生物", "科学", "宇宙", "量子", "基因"), "科学"),
    ("行业", ("行业", "产业", "市场", "经济", "公司", "商业", "发展", "趋势"), "行业发展"),
    ("技术", ("技术", "编程", "算法", "人工智能", "互联网", "工程"), "技术"),
    ("文化", ("文化", "艺术", "文学", "哲学", "宗教", "语言"), "文化"),
]

USER_AGENT = "AtlasKnowledgeBot/1.0 (local learning assistant; educational use)"


def expand_research_queries(question: str, max_facets: int = 4) -> list[str]:
    """Turn one question into several aspect-oriented search queries."""
    q = question.strip()
    if not q:
        return []

    q = re.sub(r"^(请|帮我|麻烦)?(自主学习|去学|学习一下|了解一下|查一下|搜索)[：:\s]*", "", q)
    q = q.strip("？?。.!！ ")
    if not q:
        return []

    core = re.sub(r"^(什么是|介绍一下|讲讲|说说|解释一下)\s*", "", q).strip()

    matched: list[str] = []
    for _name, keys, facet_label in DOMAIN_FACETS:
        if any(k in q for k in keys):
            if facet_label not in matched:
                matched.append(facet_label)

    # Strip facet words to get a cleaner topic, e.g. 丝绸之路的历史与地理 → 丝绸之路
    topic = core
    for _name, keys, facet_label in DOMAIN_FACETS:
        for k in (*keys, facet_label):
            topic = topic.replace(k, " ")
    topic = re.sub(r"[的与和及\s]+", " ", topic).strip(" 的与和及")
    if len(topic) < 2:
        topic = core

    queries: list[str] = [topic]
    if topic != core:
        queries.append(core)

    if matched:
        for label in matched[:max_facets]:
            queries.append(f"{topic} {label}")
    else:
        for label in ("概述", "历史", "影响", "发展"):
            queries.append(f"{topic} {label}")

    seen: set[str] = set()
    out: list[str] = []
    for item in queries:
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[: max(4, max_facets + 1)]


def filter_relevant_hits(
    question: str, hits: list[dict[str, Any]], min_keep: int = 1
) -> list[dict[str, Any]]:
    """Drop off-topic KB hits. Return empty if nothing truly matches."""
    if not hits:
        return []
    # Web results are already ranked by the search backend; don't kill them with
    # strict local-KB bigram overlap (news titles rarely mirror the user query).
    web_hits = [h for h in hits if (h.get("source_type") or "") == "web"]
    local_hits = [h for h in hits if (h.get("source_type") or "") != "web"]
    if web_hits and not local_hits:
        return web_hits[: max(min_keep, 5)]

    chars = re.findall(r"[\u4e00-\u9fff]", question)
    focus = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    focus.update(chars[i] + chars[i + 1] + chars[i + 2] for i in range(len(chars) - 2))
    focus.update(re.findall(r"[a-zA-Z0-9_]{3,}", question.lower()))
    stop = {
        "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
        "学习", "介绍", "一下", "历史", "地理", "知识", "开发", "相关", "问题",
    }
    focus = {t for t in focus if t not in stop and len(t) >= 2}
    if not focus:
        return hits

    ranked: list[tuple[int, dict[str, Any]]] = []
    for h in local_hits or hits:
        title = (h.get("title") or "").lower()
        blob = f"{title} {(h.get('content') or '')[:500]}".lower()
        strong = sum(2 for t in focus if len(t) >= 3 and t in blob)
        weak = sum(1 for t in focus if len(t) == 2 and t in title)
        ranked.append((strong + weak, h))
    ranked.sort(key=lambda x: x[0], reverse=True)
    kept = [h for s, h in ranked if s >= 2]
    if kept:
        # Prefer local matches; append leftover web snippets if any
        out = kept[: max(min_keep, 5)]
        for wh in web_hits:
            if wh not in out and len(out) < 5:
                out.append(wh)
        return out
    if web_hits:
        return web_hits[: max(min_keep, 5)]
    return []


def needs_external_research(hits: list[dict[str, Any]], question: str) -> bool:
    """Decide whether local KB is too thin or off-topic for the question."""
    if not hits:
        return True

    best = float(hits[0].get("score") or 0)
    chars = re.findall(r"[\u4e00-\u9fff]", question)
    focus = {chars[i] + chars[i + 1] + chars[i + 2] for i in range(len(chars) - 2)}
    focus.update(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    focus.update(re.findall(r"[a-zA-Z0-9_]{3,}", question.lower()))
    stop = {
        "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
        "学习", "介绍", "一下", "知识", "开发",
    }
    focus = {t for t in focus if t not in stop and len(t) >= 2}

    def strong_overlap(hit: dict[str, Any]) -> int:
        blob = f"{hit.get('title', '')} {hit.get('content', '')[:400]}".lower()
        return sum(1 for t in focus if len(t) >= 3 and t in blob)

    top_strong = strong_overlap(hits[0]) if hits else 0
    if focus and top_strong <= 0:
        return True
    if best < 3.5:
        return True

    domain_cues = (
        "地理", "历史", "数学", "朝代", "国家", "城市", "战争", "公式",
        "定理", "产业", "经济", "气候", "河流", "山脉", "古代", "近代",
        "丝绸之路", "工业", "革命", "勾股", "微积分", "物理", "化学",
        "大学", "就业", "学校", "专业", "录取", "高考", "公司", "股价",
        "天气", "新闻",
    )
    if any(c in question for c in domain_cues):
        blob = " ".join(
            f"{h.get('title', '')} {h.get('content', '')[:160]}" for h in hits[:3]
        )
        if not any(c in blob for c in domain_cues if c in question):
            return True
    return False


def _clean_wiki_text(text: str) -> str:
    """Strip Wikipedia math/markup noise for readable answers."""
    text = re.sub(r"\{\\displaystyle\s*", "", text)
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


async def _wiki_search(query: str, lang: str = "zh", limit: int = 3) -> list[dict[str, str]]:
    api = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": str(limit),
        "format": "json",
        "utf8": "1",
    }
    headers = {"User-Agent": USER_AGENT}
    timeout = float(get_settings().http_timeout_research)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await client.get(api, params=params)
        resp.raise_for_status()
        data = resp.json()
    results = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title") or ""
        if title:
            results.append({"title": title, "lang": lang})
    return results


async def _wiki_extract(title: str, lang: str = "zh") -> dict[str, str] | None:
    api = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "extracts",
        "exintro": "1",
        "explaintext": "1",
        "titles": title,
        "format": "json",
        "utf8": "1",
    }
    headers = {"User-Agent": USER_AGENT}
    timeout = float(get_settings().http_timeout_research)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await client.get(api, params=params)
        resp.raise_for_status()
        data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        if page.get("missing") is not None:
            continue
        extract = (page.get("extract") or "").strip()
        page_title = page.get("title") or title
        if extract and len(extract) >= 40:
            url = f"https://{lang}.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
            return {
                "title": page_title,
                "content": _clean_wiki_text(extract)[:1800],
                "url": url,
                "lang": lang,
            }
    return None


async def fetch_topic_snippets(query: str, per_query: int = 1) -> list[dict[str, str]]:
    """Search Wikipedia zh first (skip en unless empty) — fewer round-trips."""
    snippets: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for lang in ("zh", "en"):
        try:
            hits = await _wiki_search(query, lang=lang, limit=per_query)
        except Exception:  # noqa: BLE001
            continue
        # Parallel extract
        import asyncio

        pages = await asyncio.gather(
            *[_wiki_extract(h["title"], lang=lang) for h in hits],
            return_exceptions=True,
        )
        for page in pages:
            if not isinstance(page, dict) or not page:
                continue
            key = page["title"].lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            snippets.append(page)
            if len(snippets) >= per_query:
                return snippets
        if snippets:
            return snippets
    return snippets


async def learn_if_new(title: str, content: str, source_type: str = "auto_wiki") -> dict[str, Any] | None:
    """Save to KB unless an identical title already exists."""
    session_maker = get_session_maker()
    async with session_maker() as db:
        existing = await crud.find_document_by_title(db, title)
        if existing:
            return None
        doc = await crud.create_document(
            db,
            title=title[:200],
            content=content,
            source_type=source_type,
        )
        await db.commit()
        await db.refresh(doc)
        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "source_type": doc.source_type,
        }


async def research_and_learn(
    question: str,
    max_pages: int = 2,
    auto_save: bool = True,
) -> dict[str, Any]:
    """
    Multi-aspect research (fast path): 1–2 queries, zh wiki first, optional learn.
    """
    import asyncio

    queries = expand_research_queries(question, max_facets=2)[:2]
    topic = queries[0] if queries else question
    collected: list[dict[str, str]] = []
    learned: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []

    # Parallel fetch for the (few) aspect queries
    async def _one(q: str) -> list[dict[str, str]]:
        try:
            return await fetch_topic_snippets(q, per_query=1)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"fetch:{exc}"[:160])
            return []

    batches = await asyncio.gather(*[_one(q) for q in queries]) if queries else []

    for snippets in batches:
        for snip in snippets:
            key = snip["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append(snip)
            if auto_save:
                saved = await learn_if_new(
                    snip["title"],
                    f"{snip['content']}\n\n来源：{snip.get('url', 'Wikipedia')}",
                    source_type="auto_wiki",
                )
                if saved:
                    learned.append({"id": saved["id"], "title": saved["title"]})
            if len(collected) >= max_pages:
                break
        if len(collected) >= max_pages:
            break

    collected.sort(
        key=lambda c: (
            0 if topic in c["title"] or c["title"] in topic else 1,
            -len(c.get("content") or ""),
        )
    )

    hits = [
        {
            "title": c["title"],
            "content": c["content"],
            "excerpt": c["content"][:300],
            "score": 12.0 if (topic in c["title"] or c["title"] in topic) else 8.0,
            "source": c.get("url", ""),
            "source_type": "auto_wiki",
        }
        for c in collected
    ]

    return {
        "ok": bool(hits) or not errors,
        "queries": queries,
        "hits": hits,
        "learned": learned,
        "count": len(hits),
        "learned_count": len(learned),
        "errors": errors,
    }


def parse_auto_learn_intent(text: str) -> str | None:
    """Parse '自主学习：丝绸之路' / '去学一下量子力学'."""
    stripped = text.strip()
    patterns = (
        r"^(?:请|帮我)?自主学习[：:\s]*(.+)$",
        r"^(?:请|帮我)?(?:去学|学习一下|了解一下|查一下)[：:\s]*(.+)$",
        r"^扩展知识[：:\s]*(.+)$",
    )
    for pat in patterns:
        m = re.match(pat, stripped, re.S)
        if m:
            topic = m.group(1).strip(" ？?。.!！")
            if topic:
                return topic[:200]
    return None
