"""Built-in tools for the starter agent."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Awaitable, Callable, Dict, Union

from app.config import get_settings
from app.rag.ingest import IngestLimitError
from app.rag.knowledge import KnowledgeService
from app.rag.research import research_and_learn
from app.rag.web_search import search_web

# Windows 常缺 IANA 时区库；优先 ZoneInfo，失败则回退固定偏移
_FALLBACK_OFFSETS = {
    "Asia/Shanghai": 8,
    "Asia/Hong_Kong": 8,
    "UTC": 0,
    "America/New_York": -5,
}

_knowledge = KnowledgeService()


def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """Return the current local time for a timezone."""
    hours = _FALLBACK_OFFSETS.get(timezone, 8)
    label = timezone if timezone in _FALLBACK_OFFSETS else f"UTC+{hours}"
    now = datetime.now(dt_timezone(timedelta(hours=hours)))
    return json.dumps(
        {
            "timezone": label,
            "iso": now.isoformat(timespec="seconds"),
            "readable": now.strftime("%Y-%m-%d %H:%M:%S"),
        },
        ensure_ascii=False,
    )


def calculator(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression."""
    allowed = set("0123456789+-*/().% ")
    if not expression or any(ch not in allowed for ch in expression):
        return json.dumps({"error": "仅支持数字与 + - * / ( ) %"}, ensure_ascii=False)
    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    return json.dumps({"expression": expression, "result": result}, ensure_ascii=False)


async def search_knowledge(
    query: str, top_k: int = 6, user_id: int | None = None
) -> str:
    """Search the self-learned knowledge base."""
    settings = get_settings()
    hits = await _knowledge.search(
        query,
        top_k=max(1, min(int(top_k or 3), int(settings.rag_top_k_max))),
        user_id=user_id,
    )
    return json.dumps({"query": query, "results": hits, "count": len(hits)}, ensure_ascii=False)


async def learn_knowledge(
    title: str, content: str, user_id: int | None = None
) -> str:
    """Save new knowledge into the local knowledge base."""
    try:
        saved = await _knowledge.learn(title, content, user_id=user_id)
    except IngestLimitError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    return json.dumps(
        {"status": "learned", "id": saved["id"], "title": saved["title"]},
        ensure_ascii=False,
    )


async def research_topics(query: str, max_pages: int = 5, auto_save: bool = False) -> str:
    """Multi-aspect encyclopedia research and optional auto-learn into KB."""
    result = await research_and_learn(
        query,
        max_pages=max(1, min(int(max_pages or 5), 8)),
        auto_save=bool(auto_save),
    )
    return json.dumps(result, ensure_ascii=False)


async def web_search(query: str, max_results: int = 5, fetch_top: int = 2) -> str:
    """Search the open web and return snippets for answering."""
    result = await search_web(
        query,
        max_results=max(1, min(int(max_results or 5), 8)),
        fetch_top=max(0, min(int(fetch_top or 2), 3)),
    )
    return json.dumps(result, ensure_ascii=False)


async def search_graph(query: str, hops: int = 1, top_k: int = 6) -> str:
    """Optional P4 knowledge-graph subgraph search (no-op when disabled)."""
    from app.rag.graph_query import search_subgraph

    settings = get_settings()
    result = await search_subgraph(
        query,
        hops=max(0, min(int(hops if hops is not None else settings.rag_graph_hops), 3)),
        top_k=max(1, min(int(top_k or 6), 20)),
        settings=settings,
    )
    return json.dumps(result, ensure_ascii=False)


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取指定时区的当前时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA 时区，例如 Asia/Shanghai",
                        "default": "Asia/Shanghai",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "计算简单四则运算表达式",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "例如 (12+8)*3",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "查阅已学习的本地知识库，回答用户问题前先调用",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或问题"},
                    "top_k": {"type": "integer", "description": "返回条数", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_knowledge",
            "description": "将新知识写入本地知识库，供后续查阅",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "知识标题"},
                    "content": {"type": "string", "description": "知识内容"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_topics",
            "description": (
                "当本地知识不足时，从开放百科多方面检索（地理/历史/数学/行业等），"
                "并可自动写入知识库实现自主学习"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "主题或问题"},
                    "max_pages": {
                        "type": "integer",
                        "description": "最多学习页数",
                        "default": 5,
                    },
                    "auto_save": {
                        "type": "boolean",
                        "description": "是否自动写入知识库",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索开放网页（DuckDuckGo），用于回答需要最新信息或本地/百科不足的问题；"
                "返回标题、摘要与链接"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "max_results": {
                        "type": "integer",
                        "description": "返回条数",
                        "default": 5,
                    },
                    "fetch_top": {
                        "type": "integer",
                        "description": "深入抓取前几条网页正文摘要",
                        "default": 2,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_graph",
            "description": (
                "查询可选知识图谱子图（实体关系）；默认关闭。"
                "关闭或失败时返回空结果，不影响文档检索"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "问题或实体关键词"},
                    "hops": {
                        "type": "integer",
                        "description": "子图跳数（0–3）",
                        "default": 1,
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "种子实体上限",
                        "default": 6,
                    },
                },
                "required": ["query"],
            },
        },
    },
]

ToolHandler = Union[
    Callable[..., str],
    Callable[..., Awaitable[str]],
]

TOOL_HANDLERS: Dict[str, ToolHandler] = {
    "get_current_time": get_current_time,
    "calculator": calculator,
    "search_knowledge": search_knowledge,
    "learn_knowledge": learn_knowledge,
    "research_topics": research_topics,
    "web_search": web_search,
    "search_graph": search_graph,
}


async def run_tool(name: str, arguments: Dict[str, Any] | str) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    result = handler(**(arguments or {}))
    if inspect.isawaitable(result):
        return await result
    return result
