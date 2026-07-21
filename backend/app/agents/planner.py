"""
Lightweight intent planner — inspired by Agentic RAG routers and LangGraph
conditional edges (JoshuaC215/agent-service-toolkit), rewritten for Atlas.

We do NOT depend on LangGraph/LangChain; this is a small, explicit router.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.config import get_settings
from app.rag.knowledge import parse_learn_intent
from app.rag.policy_intent import POLICY_KEYWORDS, is_policy_question
from app.rag.research import filter_relevant_hits, needs_external_research, parse_auto_learn_intent
from app.rag.web_search import parse_web_search_intent, wants_online_search


class Intent(str, Enum):
    LEARN = "learn"  # user teaches knowledge
    AUTO_LEARN = "auto_learn"  # 自主学习：topic
    WEB = "web"  # explicit / time-sensitive web search
    RESEARCH = "research"  # encyclopedia multi-aspect + save
    LOCAL = "local"  # answer from local KB
    GENERAL = "general"  # 通用问答：非制度，模型直接作答（可带工具）
    TOOL_TIME = "tool_time"
    TOOL_CALC = "tool_calc"
    CHITCHAT = "chitchat"  # T8-1: 闲聊/寒暄，跳过检索
    CLARIFY = "clarify"  # T7-1: 短问澄清，反问而非猜测
    COMPOSITE = "composite"  # T7-2: 复合问题分解


# re-export for callers that imported from planner
__all__ = [
    "Intent",
    "AgentPlan",
    "POLICY_KEYWORDS",
    "is_policy_question",
    "plan_turn",
]


def _needs_clarification(query: str, hits: list[dict[str, Any]] | None = None) -> bool:
    """T7-1: 短问（≤3字）且检索命中不足 → 反问而非猜测。"""
    text = (query or "").strip()
    # 过短且非命令式
    if len(text) <= 3 and not any(k in text for k in ("记住", "学习", "联网", "搜索")):
        hits = hits or []
        if not hits or float(hits[0].get("score") or 0) < 5.0:
            return True
    # 纯概念词（无动词、无问号）
    if len(text) <= 4 and not any(k in text for k in ("是", "有", "能", "可", "会", "要", "吗", "？", "多", "少", "几")):
        return True
    return False


def _is_composite_query(text: str) -> bool:
    """T7-2: 检测是否包含多个独立问题。

    规则（由严到宽）：
    1. 问号/逗号/delimiter 分段 ≥2 段 → 复合
    2. 连接词两边都 ≥8 字且各有问句特征 → 复合
    3. 否则不属于复合（避免「X与Y的作用」误判）
    """
    import re as _re

    # 问号/逗号/分号 分段 — 最可靠的复合信号
    parts = [p.strip() for p in _re.split(r"[？?，,；;。]", text) if p.strip()]
    if len(parts) >= 2 and all(len(p) >= 4 for p in parts):
        return True

    # 连接词检测：两边都 ≥8 字 且 各含问句特征
    separators = ["以及", "还有", "另外", "同时", "和", "与"]
    q_indicators = {"什么", "怎么", "如何", "是吗", "能否", "可以吗", "要不要", "会不会", "哪", "区别", "差异"}
    for sep in separators:
        idx = text.find(sep)
        if idx < 0:
            continue
        left = text[:idx].strip()
        right = text[idx + len(sep):].strip()
        if len(left) >= 8 and len(right) >= 8:
            left_q = sum(1 for k in q_indicators if k in left)
            right_q = sum(1 for k in q_indicators if k in right)
            if left_q >= 1 and right_q >= 1:
                return True
    return False


def _local_plan(query: str, *, notes: list[str] | None = None) -> AgentPlan:
    local_steps = ["synthesize"]
    plan_notes = list(notes or ["本地知识足够，直接作答"])
    try:
        if get_settings().rag_graph_enabled:
            local_steps = ["search_graph", "synthesize"]
            if notes is None:
                plan_notes = ["本地知识足够；可选图谱子图增强"]
    except Exception:  # noqa: BLE001
        pass
    return AgentPlan(
        intent=Intent.LOCAL,
        query=query,
        steps=local_steps,
        notes=plan_notes,
    )


@dataclass
class AgentPlan:
    """Execution plan for one user turn (LangGraph-style routing, simplified)."""

    intent: Intent
    query: str
    steps: list[str] = field(default_factory=list)
    force_web: bool = False
    use_research: bool = False
    use_web: bool = False
    learn_payload: tuple[str, str] | None = None
    sub_queries: list[str] = field(default_factory=list)  # T7-2: 复合问题子查询
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "query": self.query,
            "steps": self.steps,
            "force_web": self.force_web,
            "use_research": self.use_research,
            "use_web": self.use_web,
            "notes": self.notes,
        }


def plan_turn(
    user_text: str,
    hits: list[dict[str, Any]] | None = None,
    retrieval_query: str | None = None,
) -> AgentPlan:
    """
    Route the user message to a tool/retrieval strategy.

    Order mirrors common agent graphs:
    special intents → tools → retrieve → research/web → answer

    retrieval_query: optional enriched/rewritten query used for thin/policy checks
    (T4-3 multi-turn); special intents still parse raw user_text.
    """
    text = (user_text or "").strip()
    hits = hits or []

    # T8-1: 闲聊/寒暄 → 不进检索（须在澄清之前，避免「你好」被当成短问澄清）
    from app.rag.chitchat import is_chitchat

    if is_chitchat(text):
        return AgentPlan(
            intent=Intent.CHITCHAT,
            query=text,
            steps=["chitchat"],
            notes=["闲聊分流：跳过 RAG / research"],
        )

    # T7-1: 短问澄清 → 不猜测，反问
    if _needs_clarification(text, hits):
        return AgentPlan(
            intent=Intent.CLARIFY,
            query=text,
            steps=["clarify"],
            notes=["短问且命中不足，反问用户澄清意图"],
        )

    # 学习意图优先于复合分解（避免「记住：X与Y」被误拆）
    learn = parse_learn_intent(text)
    if learn:
        return AgentPlan(
            intent=Intent.LEARN,
            query=text,
            steps=["learn_knowledge", "confirm"],
            learn_payload=learn,
            notes=["用户主动写入知识"],
        )

    auto = parse_auto_learn_intent(text)
    if auto:
        return AgentPlan(
            intent=Intent.AUTO_LEARN,
            query=auto,
            steps=["research_topics", "web_search", "synthesize"],
            use_research=True,
            use_web=True,
            notes=["自主学习：百科与联网并行"],
        )

    # T7-2: 复合问题分解（仅当不是特殊意图且两边都是长问句）
    if _is_composite_query(text):
        from app.rag.query_decompose import decompose_composite_query

        sub_queries = decompose_composite_query(text)
        if len(sub_queries) >= 2:
            return AgentPlan(
                intent=Intent.COMPOSITE,
                query=text,
                steps=["parallel_search"] * len(sub_queries) + ["merge_synthesize"],
                sub_queries=sub_queries,
                notes=[f"复合问题分解为 {len(sub_queries)} 个子查询：{' | '.join(sub_queries)}"],
            )

    return _route_normal(text, hits, retrieval_query)


def _route_normal(
    text: str,
    hits: list[dict[str, Any]] | None = None,
    retrieval_query: str | None = None,
) -> AgentPlan:
    """Standard routing: time/calc → web → research → local."""
    hits = hits or []

    web_topic = parse_web_search_intent(text)
    force_web = bool(web_topic) or wants_online_search(text)
    query = web_topic or text
    focus = (retrieval_query or query).strip() or query

    lower = text.lower()
    if any(k in text for k in ("时间", "几点")) or "time" in lower or "now" in lower:
        if not force_web:
            return AgentPlan(
                intent=Intent.TOOL_TIME,
                query=query,
                steps=["get_current_time", "answer"],
            )

    mathish = any(
        k in text
        for k in ("高数", "微积分", "求导", "积分", "极限", "矩阵", "线性代数", "证明题", "方程")
    ) or bool(re.search(r"\d+\s*[\+\-\*/×÷＝=]\s*\d+", text))
    if any(k in text for k in ("计算", "算一下")) or "calc" in lower or mathish:
        looks_like_math = bool(
            mathish
            or re.search(r"\d+\s*[\+\-\*/×÷＝=]\s*\d+", text)
            or re.search(r"(计算|算一下)\s*\d", text)
            or ("calc" in lower and re.search(r"\d", text))
        )
        if is_policy_question(text) and not looks_like_math:
            pass
        elif looks_like_math and re.search(r"\d", text) and any(
            k in text for k in ("计算", "算一下", "+", "-", "*", "/", "×", "÷", "=")
        ):
            return AgentPlan(
                intent=Intent.TOOL_CALC,
                query=query,
                steps=["calculator", "answer"],
            )
        elif looks_like_math and not is_policy_question(text):
            # 高数/证明等：交给通用 LLM，勿因「非制度」拒答
            return AgentPlan(
                intent=Intent.GENERAL,
                query=query,
                steps=["synthesize"],
                notes=["通用数理问答：模型直接作答"],
            )

    if force_web:
        return AgentPlan(
            intent=Intent.WEB,
            query=query,
            steps=["web_search", "synthesize"],
            force_web=True,
            use_web=True,
            notes=["联网优先（加速）"],
        )

    from app.rag.query_rewrite import rewrite_search_query

    focus_r = rewrite_search_query(focus) or focus
    relevant = filter_relevant_hits(focus_r, hits)
    thin = not relevant or needs_external_research(relevant or hits, focus_r)
    if thin:
        if (
            is_policy_question(focus)
            or is_policy_question(focus_r)
            or is_policy_question(query)
        ):
            return _local_plan(
                query,
                notes=["制度问答：本地无据则拒绝，禁止自动联网编造"],
            )
        if hits and float(hits[0].get("score") or 0) >= 4.0:
            from app.rag.dialogue_slots import is_followup_utterance

            if is_followup_utterance(text):
                return _local_plan(
                    query,
                    notes=["追问且本地已有命中，禁止转外网"],
                )
        if any(k in focus for k in ("大学", "学院", "就业", "录取", "高考", "专业")):
            return AgentPlan(
                intent=Intent.WEB,
                query=query,
                steps=["web_search", "synthesize"],
                force_web=True,
                use_web=True,
                notes=["院校/就业类问题 → 联网检索"],
            )
        # 百科型长问仍走 research；其余通用题直接 LLM（制度优先产品下的通用能力）
        encyclopedic = any(
            k in focus
            for k in ("是什么", "什么是", "简介", "概述", "发展史", "百科", "介绍一下")
        )
        if encyclopedic:
            return AgentPlan(
                intent=Intent.RESEARCH,
                query=query,
                steps=["research_topics", "web_search", "synthesize"],
                use_research=True,
                use_web=True,
                notes=["百科型 → 百科与联网并行"],
            )
        return AgentPlan(
            intent=Intent.GENERAL,
            query=query,
            steps=["synthesize"],
            notes=["通用问答：模型直接作答，需要时再调用工具"],
        )

    return _local_plan(query)
