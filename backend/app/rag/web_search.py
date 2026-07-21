"""Open-web search for answering questions online (no API key required)."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.config import get_settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 120.0


def wants_online_search(question: str) -> bool:
    """True only for explicit web intent or clear real-time topics (not bare 今天/目前)."""
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()
    explicit = (
        "联网",
        "网上",
        "上网",
        "搜索",
        "搜一下",
        "查一下",
        "百度",
        "谷歌",
        "google",
    )
    if any(k in ql for k in explicit):
        return True
    # Time-sensitive topics must be explicit enough (avoid forcing web on 今天 alone)
    realtime = ("新闻", "时事", "股价", "天气", "汇率", "实时", "热点", "头条")
    if any(k in q for k in realtime):
        return True
    if "最新" in q and not is_policy_ish(q):
        return True
    return False


def is_policy_ish(text: str) -> bool:
    from app.rag.policy_intent import is_policy_question

    return is_policy_question(text)


def parse_web_search_intent(text: str) -> str | None:
    stripped = text.strip()
    patterns = (
        r"^(?:请|帮我)?(?:联网|网上|上网)(?:搜索|查询|查一下|搜一下)?[：:\s]*(.+)$",
        r"^(?:请|帮我)?(?:搜索|搜一下|查一下)[：:\s]*(.+)$",
        r"^web\s*search[：:\s]*(.+)$",
    )
    for pat in patterns:
        m = re.match(pat, stripped, re.I | re.S)
        if m:
            topic = m.group(1).strip(" ？?。.!！")
            if topic:
                return topic[:200]
    return None


async def _ddg_instant(query: str) -> list[dict[str, str]]:
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    headers = {"User-Agent": USER_AGENT}
    timeout = float(get_settings().http_timeout_web)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    out: list[dict[str, str]] = []
    abstract = (data.get("AbstractText") or "").strip()
    if abstract:
        out.append(
            {
                "title": data.get("Heading") or query,
                "url": data.get("AbstractURL") or "https://duckduckgo.com/",
                "snippet": abstract[:800],
                "source": "ddg_instant",
            }
        )
    for topic in data.get("RelatedTopics") or []:
        if not isinstance(topic, dict) or "Topics" in topic:
            continue
        text = (topic.get("Text") or "").strip()
        link = topic.get("FirstURL") or ""
        if text and link:
            out.append(
                {
                    "title": text.split(" - ", 1)[0][:120],
                    "url": link,
                    "snippet": text[:500],
                    "source": "ddg_related",
                }
            )
        if len(out) >= 4:
            break
    return out


def _reset_ddgs_executor(ddgs_cls: Any) -> None:
    """ddgs 使用类级 ThreadPoolExecutor；被 shutdown 后需置空才能重建。"""
    ex = getattr(ddgs_cls, "_executor", None)
    if ex is not None:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            try:
                ex.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    try:
        ddgs_cls._executor = None
    except Exception:  # noqa: BLE001
        pass


def _normalize_ddgs_rows(items: Any, source: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = item.get("href") or item.get("link") or item.get("url") or ""
        if not str(url).startswith("http"):
            continue
        rows.append(
            {
                "title": (item.get("title") or "")[:200],
                "url": str(url),
                "snippet": (item.get("body") or item.get("snippet") or item.get("content") or "")[
                    :500
                ],
                "source": source,
            }
        )
    return rows


def _import_ddgs() -> Any | None:
    try:
        from ddgs import DDGS as _DDGS  # type: ignore

        return _DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS as _DDGS  # type: ignore

            return _DDGS
        except ImportError:
            return None


async def _ddg_package(
    query: str,
    max_results: int = 6,
    *,
    prefer_news: bool = False,
) -> list[dict[str, str]]:
    DDGS = _import_ddgs()
    if DDGS is None:
        return []

    def _run(reset_first: bool = False) -> list[dict[str, str]]:
        if reset_first:
            _reset_ddgs_executor(DDGS)
        # 不要调用 ddgs.close()：会关掉类级 ThreadPoolExecutor
        client = DDGS(timeout=20)
        if prefer_news and hasattr(client, "news"):
            try:
                items = client.news(query, max_results=max_results)
                rows = _normalize_ddgs_rows(items, "ddgs_news")
                if rows:
                    return rows
            except Exception:  # noqa: BLE001
                pass
        items = client.text(query, max_results=max_results)
        return _normalize_ddgs_rows(items, "ddgs")

    # DDG 在国内/受限网络常偏慢，过短超时会导致 count=0
    timeout = max(18.0, float(get_settings().http_timeout_web) * 2.0)
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run, False), timeout=timeout)
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "shutdown" not in msg and "executor" not in msg:
            raise
        return await asyncio.wait_for(asyncio.to_thread(_run, True), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        # to_thread 外层也可能包一层；线程内 RuntimeError 直接冒出
        msg = str(exc).lower()
        if "shutdown" in msg or "executor" in msg:
            return await asyncio.wait_for(asyncio.to_thread(_run, True), timeout=timeout)
        raise


async def _html_fallback_search(query: str, max_results: int = 6) -> list[dict[str, str]]:
    """不依赖 ddgs 线程池：Bing HTML + DDG HTML 兜底。"""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    timeout = max(12.0, float(get_settings().http_timeout_web))
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        # Bing
        try:
            resp = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "setlang": "zh-Hans", "mkt": "zh-CN"},
            )
            if resp.status_code == 200:
                html = resp.text
                for m in re.finditer(
                    r'class="b_algo"[^>]*>[\s\S]*?<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>([\s\S]*?)</a>'
                    r'[\s\S]*?(?:class="b_caption"[^>]*>[\s\S]*?<p[^>]*>([\s\S]*?)</p>)?',
                    html,
                    re.I,
                ):
                    url = m.group(1)
                    title = re.sub(r"<[^>]+>", "", m.group(2) or "").strip()
                    snip = re.sub(r"<[^>]+>", "", m.group(3) or "").strip()
                    if url in seen or not title:
                        continue
                    seen.add(url)
                    out.append(
                        {
                            "title": title[:200],
                            "url": url,
                            "snippet": (snip or title)[:500],
                            "source": "bing_html",
                        }
                    )
                    if len(out) >= max_results:
                        return out
        except Exception:  # noqa: BLE001
            pass

        # DuckDuckGo HTML
        try:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            if resp.status_code == 200:
                html = resp.text
                for m in re.finditer(
                    r'class="result__a"[^>]+href="(https?://[^"]+)"[^>]*>([\s\S]*?)</a>'
                    r'[\s\S]*?class="result__snippet"[^>]*>([\s\S]*?)</(?:a|td|div)',
                    html,
                    re.I,
                ):
                    url = m.group(1)
                    title = re.sub(r"<[^>]+>", "", m.group(2) or "").strip()
                    snip = re.sub(r"<[^>]+>", "", m.group(3) or "").strip()
                    if url in seen or not title:
                        continue
                    seen.add(url)
                    out.append(
                        {
                            "title": title[:200],
                            "url": url,
                            "snippet": (snip or title)[:500],
                            "source": "ddg_html",
                        }
                    )
                    if len(out) >= max_results:
                        break
        except Exception:  # noqa: BLE001
            pass

    return out[:max_results]


def _looks_like_boilerplate(text: str) -> bool:
    if not text or len(text) < 40:
        return False if text and len(text) >= 12 else True
    if text.count("](") >= 8 and len(text) < 1500:
        return True
    return False


def _prefer_score(url: str, title: str, query: str = "") -> float:
    host = (url or "").lower()
    title_l = (title or "").lower()
    bonus = 0.0
    for domain, pts in (
        ("wikipedia.org", 2.0),
        ("baike.baidu.com", 2.5),
        ("edu.cn", 3.5),
        ("uic.edu", 4.0),
        ("bnbu.edu", 4.0),
        ("zhihu.com", 1.2),
    ):
        if domain in host:
            bonus += pts
    q = (query or "").strip()
    if q:
        chars = re.findall(r"[\u4e00-\u9fff]", q)
        for n in (4, 3):
            for i in range(len(chars) - n + 1):
                gram = "".join(chars[i : i + n])
                if gram in title_l:
                    bonus += 2.5 if n >= 4 else 1.2
        for part in re.findall(r"[a-zA-Z]{3,}", q.lower()):
            if part in title_l:
                bonus += 2.0
    return bonus


async def search_web(
    query: str,
    max_results: int = 3,
    fetch_top: int = 0,
) -> dict[str, Any]:
    """Fast open-web search: few results, title-aware ranking, short cache."""
    del fetch_top
    q = query.strip()
    if not q:
        return {"ok": False, "error": "empty query", "results": [], "hits": []}

    # Bust stale bad cache entries when ranking logic changes
    cache_key = f"v4|{q}|{max_results}"
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    results: list[dict[str, str]] = []
    errors: list[str] = []
    search_q = q
    is_news = any(k in q for k in ("新闻", "时事", "今日", "今天", "最新", "热点", "头条"))
    is_tech = any(k in q for k in ("科技", "数码", "互联网", "AI", "人工智能"))
    if any(k in q for k in ("是什么", "什么是", "简介")) and len(q) < 40:
        search_q = f"{q} 百科"
    if any(k in q for k in ("就业", "去向", "毕业生", "录取")):
        search_q = f"{q} 就业 毕业生 去向"
    elif any(k in q for k in ("大学", "学院", "学校")):
        search_q = f"{q} 简介"
    elif is_news and is_tech:
        search_q = "科技新闻 今日 资讯"
    elif is_news:
        search_q = "今日时事新闻 热点"

    queries = [search_q]
    if is_news:
        queries.append("today world news" if not is_tech else "today technology news")
        if search_q != q:
            queries.insert(0, q)

    # 去重保序
    seen_q: set[str] = set()
    uniq_queries: list[str] = []
    for attempt_q in queries:
        if attempt_q and attempt_q not in seen_q:
            seen_q.add(attempt_q)
            uniq_queries.append(attempt_q)

    for attempt_q in uniq_queries:
        try:
            batch = await _ddg_package(
                attempt_q,
                max_results=max(max_results, 6),
                prefer_news=is_news,
            )
            for item in batch:
                if item["url"] not in {r["url"] for r in results}:
                    results.append(item)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ddgs({attempt_q[:24]}): {type(exc).__name__}: {exc}")
            # 线程池挂掉时立刻走 HTML 兜底，避免空转多个 query
            if "shutdown" in str(exc).lower() or "executor" in str(exc).lower():
                break
        # 新闻类多试一轮中文 query，避免英文噪声提前截断
        if len(results) >= max_results and not (is_news and attempt_q == uniq_queries[0]):
            break

    if len(results) < max(2, max_results // 2) or any(
        "shutdown" in e.lower() or "executor" in e.lower() for e in errors
    ):
        try:
            for item in await _html_fallback_search(search_q, max_results=max(max_results, 6)):
                if item["url"] not in {r["url"] for r in results}:
                    results.append(item)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"html_fallback: {type(exc).__name__}: {exc}")

    if len(results) < 2:
        try:
            for item in await _ddg_instant(search_q):
                if item["url"] not in {r["url"] for r in results}:
                    results.append(item)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"instant: {type(exc).__name__}: {exc}")

    results.sort(
        key=lambda r: -(
            _prefer_score(r.get("url", ""), r.get("title", ""), q)
            + min(len(r.get("snippet") or ""), 200) / 200
        )
    )

    hits = []
    chars = re.findall(r"[\u4e00-\u9fff]", q)
    grams3 = {"".join(chars[j : j + 3]) for j in range(max(0, len(chars) - 2))}
    news_hosts = (
        "ithome.com",
        "36kr.com",
        "qq.com",
        "sina.com",
        "163.com",
        "sohu.com",
        "xinhuanet.com",
        "people.com.cn",
        "chinanews.com",
        "thepaper.cn",
        "guancha.cn",
        "cctv.com",
        "china.com",
        "bbc.",
        "reuters",
        "techcrunch",
        "theverge",
    )
    for i, r in enumerate(results[: max(max_results + 4, 8)]):
        snip = (r.get("snippet") or r.get("title") or "").strip()
        if not snip or _looks_like_boilerplate(snip):
            continue
        clean = re.sub(r"\s+", " ", snip).strip()
        if len(clean) < 12:
            continue
        title_boost = _prefer_score(r.get("url", ""), r.get("title", ""), q)
        host = (r.get("url") or "").lower()
        if is_news and any(h in host for h in news_hosts):
            title_boost += 2.0
        blob = f"{r.get('title', '')} {clean}"
        # 新闻类放宽：开放搜索标题常不含用户原句三字词
        if (
            not is_news
            and title_boost < 1.2
            and grams3
            and not any(g in blob for g in grams3)
        ):
            continue
        hits.append(
            {
                "title": r["title"] or "网页结果",
                "content": clean[:900] + (f"\n\n来源：{r['url']}" if r.get("url") else ""),
                "excerpt": clean[:280],
                "score": round(11.0 - i * 0.4 + title_boost, 2),
                "source": r.get("url", ""),
                "source_type": "web",
            }
        )
        if len(hits) >= max_results:
            break

    out = {
        "ok": bool(hits),
        "query": q,
        "results": results[:max_results],
        "hits": hits,
        "count": len(hits),
        "errors": errors,
        "search_url": f"https://duckduckgo.com/?q={quote_plus(search_q)}",
    }
    # 仅缓存成功结果，避免空结果把服务进程锁死数分钟
    if hits:
        _CACHE[cache_key] = (time.time(), out)
    return out
