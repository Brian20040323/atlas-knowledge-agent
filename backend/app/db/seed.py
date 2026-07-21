"""Seed default knowledge into SQLite when empty."""

from __future__ import annotations

from app.db import crud
from app.db.session import get_session_maker

SEED_DOCS = [
    (
        "FastAPI入门",
        "FastAPI 是 Python 异步 Web 框架，基于 Starlette 与 Pydantic，适合构建高性能 API 与 LLM 应用后端。",
    ),
    (
        "LangGraph",
        "LangGraph 是有状态的多 Agent 编排框架，用图结构管理复杂工作流、分支与 Human-in-the-loop。",
    ),
    (
        "RAG检索增强",
        "RAG（Retrieval-Augmented Generation）先检索知识库相关文档，再把上下文交给大模型生成回答，减少幻觉。",
    ),
    (
        "Agent开发知识地图",
        "Agent 开发核心知识：1) LLM 与 Prompt/Tool Calling；2) 记忆与状态；3) 工具与 MCP；"
        "4) RAG 检索；5) 多 Agent 编排；6) 评测与可观测性；7) 安全与权限；8) 全栈部署。",
    ),
    (
        "记忆与状态",
        "记忆与状态让 Agent 跨轮次保留上下文：短期记忆存对话，长期记忆存用户偏好与事实；"
        "状态机/检查点用于工具调用中断恢复，避免每轮从零开始。",
    ),
    (
        "差旅报销制度",
        "差旅报销制度要点：1) 住宿费上限 500 元/晚；2) 机票经济舱实报实销；"
        "3) 报销须附发票、行程单与审批单；4) 超标准部分需书面说明并经部门负责人审批。"
        "本制度仅适用于本公司正式员工境内差旅费用。",
    ),
]


async def seed_knowledge_if_empty() -> int:
    session_maker = get_session_maker()
    async with session_maker() as db:
        existing = await crud.list_documents(db, limit=1)
        if existing:
            return 0
        for title, content in SEED_DOCS:
            await crud.create_document(db, title, content)
        await db.commit()
        return len(SEED_DOCS)


async def ensure_agent_seed() -> None:
    """Ensure seed docs exist; refresh content when title already present."""
    session_maker = get_session_maker()
    async with session_maker() as db:
        docs = await crud.list_documents(db, limit=200)
        by_title = {d.title: d for d in docs}
        changed = 0
        for title, content in SEED_DOCS:
            existing = by_title.get(title)
            if existing is None:
                await crud.create_document(db, title, content)
                changed += 1
            elif (existing.content or "") != content:
                existing.content = content
                changed += 1
                from app.rag.vector_index import mark_vector_index_dirty

                mark_vector_index_dirty()
        if changed:
            await db.commit()
