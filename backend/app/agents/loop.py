"""
ReAct-style tool loop — optimized for latency (parallel web/research, skip duplicates).
P2: external consecutive-failure circuit breaker + tool timing spans.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, TYPE_CHECKING

from app.agents.planner import AgentPlan, Intent
from app.config import get_settings
from app.rag.circuit import ExternalCircuit, external_call_failed
from app.tools import run_tool

if TYPE_CHECKING:
    from app.observability.traces import AgentTrace


@dataclass
class LoopState:
    """Working memory for one turn (short-term agent scratchpad)."""

    query: str
    plan: AgentPlan
    observations: list[dict[str, Any]] = field(default_factory=list)
    hits: list[dict[str, Any]] = field(default_factory=list)
    researched: bool = False
    webbed: bool = False
    answer_hint: str = ""
    circuit: ExternalCircuit | None = None

    def add_observation(self, tool: str, content: Any) -> None:
        self.observations.append({"tool": tool, "content": content})


MergeFn = Any


def _record_external(
    state: LoopState,
    tool: str,
    payload: dict[str, Any],
    *,
    trace: "AgentTrace | None",
    started: float,
) -> None:
    circuit = state.circuit
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    failed = external_call_failed(payload)
    if circuit is not None:
        if failed:
            reason = ""
            if payload.get("error"):
                reason = str(payload["error"])[:80]
            elif payload.get("errors"):
                reason = str(payload["errors"][0])[:80]
            else:
                reason = "empty_hits"
            circuit.record_failure(tool, reason)
        else:
            circuit.record_success()
    if trace is not None:
        meta: dict[str, Any] = {
            "tool": tool,
            "ok": not failed,
            "count": payload.get("count", len(payload.get("hits") or [])),
            "duration_ms": duration_ms,
        }
        if failed:
            meta["failed"] = True
        with trace.span(f"tool_{tool}", **meta) as span:
            if failed:
                span.error = "external_failed"
            if circuit is not None and circuit.opened:
                span.meta["circuit_opened"] = True


async def run_react_retrieval(
    state: LoopState,
    *,
    merge_hits: MergeFn,
    max_steps: int = 4,
    trace: "AgentTrace | None" = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Execute retrieval steps. Local search is skipped if prelim hits exist.
    research_topics + web_search run in parallel when both are planned.
    Consecutive external failures open the circuit and skip further web calls.
    """
    settings = get_settings()
    if state.circuit is None:
        state.circuit = ExternalCircuit(threshold=int(settings.web_circuit_fail_threshold))

    steps = [s for s in state.plan.steps if s not in {"synthesize", "confirm", "answer"}]
    steps = steps[:max_steps]

    # Skip duplicate local search when planner already retrieved
    if "search_knowledge" in steps and state.hits:
        steps = [s for s in steps if s != "search_knowledge"]
        state.add_observation("search_knowledge", {"count": len(state.hits), "cached": True})

    need_research = "research_topics" in steps
    need_web = "web_search" in steps or "optional_web_search" in steps
    if "optional_web_search" in steps and not state.plan.force_web:
        if state.hits and float(state.hits[0].get("score") or 0) >= 8 and len(state.hits) >= 2:
            need_web = False
            steps = [s for s in steps if s != "optional_web_search"]

    # --- Parallel batch: research + web ---
    if need_research and need_web:
        allow_r = state.circuit.allow("research_topics")
        allow_w = state.circuit.allow("web_search")
        if not allow_r and not allow_w:
            state.add_observation(
                "circuit_open",
                {"skipped": ["research_topics", "web_search"], **state.circuit.to_meta()},
            )
            if trace is not None:
                with trace.span("circuit_skip", tools=["research_topics", "web_search"], **state.circuit.to_meta()):
                    pass
            steps = [
                s
                for s in steps
                if s not in {"research_topics", "web_search", "optional_web_search"}
            ]
        else:
            tasks: list[Any] = []
            names: list[str] = []
            if allow_r:
                yield {"type": "tool_start", "name": "research_topics"}
                tasks.append(
                    run_tool(
                        "research_topics",
                        {"query": state.query, "max_pages": 2, "auto_save": True},
                    )
                )
                names.append("research_topics")
            else:
                state.add_observation("research_topics", {"skipped": True, "reason": "circuit_open"})
            if allow_w:
                yield {"type": "tool_start", "name": "web_search"}
                tasks.append(
                    run_tool(
                        "web_search",
                        {"query": state.query, "max_results": 3, "fetch_top": 2},
                    )
                )
                names.append("web_search")
            else:
                state.add_observation("web_search", {"skipped": True, "reason": "circuit_open"})

            t0 = time.perf_counter()
            raws = await asyncio.gather(*tasks) if tasks else []
            by_name = dict(zip(names, raws))

            if "research_topics" in by_name:
                research_raw = by_name["research_topics"]
                yield {"type": "tool_result", "name": "research_topics", "content": research_raw}
                research = _loads(research_raw)
                _record_external(state, "research_topics", research, trace=trace, started=t0)
                if research.get("hits"):
                    state.researched = True
                    state.hits = merge_hits(research["hits"], state.hits)[:8]
                state.add_observation(
                    "research_topics",
                    {
                        "learned": research.get("learned_count", 0),
                        "count": research.get("count", 0),
                    },
                )

            if "web_search" in by_name:
                web_raw = by_name["web_search"]
                yield {"type": "tool_result", "name": "web_search", "content": web_raw}
                web = _loads(web_raw)
                _record_external(state, "web_search", web, trace=trace, started=t0)
                if web.get("hits"):
                    state.webbed = True
                    if state.plan.force_web or state.plan.intent == Intent.WEB:
                        state.hits = merge_hits(web["hits"], state.hits)[:8]
                    else:
                        state.hits = merge_hits(state.hits, web["hits"])[:8]
                state.add_observation("web_search", {"count": web.get("count", 0)})

            steps = [
                s
                for s in steps
                if s not in {"research_topics", "web_search", "optional_web_search"}
            ]

    for step in steps:
        if step == "search_knowledge":
            yield {"type": "tool_start", "name": "search_knowledge"}
            t0 = time.perf_counter()
            raw = await run_tool("search_knowledge", {"query": state.query, "top_k": 5})
            yield {"type": "tool_result", "name": "search_knowledge", "content": raw}
            data = _loads(raw)
            local_hits = data.get("results") or []
            state.hits = merge_hits(state.hits, local_hits)[:8]
            state.add_observation("search_knowledge", {"count": len(local_hits)})
            if trace is not None:
                with trace.span(
                    "tool_search_knowledge",
                    count=len(local_hits),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                ):
                    pass

        elif step == "research_topics":
            if not state.circuit.allow("research_topics"):
                state.add_observation("research_topics", {"skipped": True, "reason": "circuit_open"})
                if trace is not None:
                    with trace.span("circuit_skip", tools=["research_topics"], **state.circuit.to_meta()):
                        pass
                continue
            yield {"type": "tool_start", "name": "research_topics"}
            t0 = time.perf_counter()
            raw = await run_tool(
                "research_topics",
                {"query": state.query, "max_pages": 2, "auto_save": True},
            )
            yield {"type": "tool_result", "name": "research_topics", "content": raw}
            data = _loads(raw)
            _record_external(state, "research_topics", data, trace=trace, started=t0)
            if data.get("hits"):
                state.researched = True
                state.hits = merge_hits(data["hits"], state.hits)[:8]
            state.add_observation(
                "research_topics",
                {"learned": data.get("learned_count", 0), "count": data.get("count", 0)},
            )

        elif step in {"web_search", "optional_web_search"}:
            if not state.circuit.allow("web_search"):
                state.add_observation("web_search", {"skipped": True, "reason": "circuit_open"})
                if trace is not None:
                    with trace.span("circuit_skip", tools=["web_search"], **state.circuit.to_meta()):
                        pass
                continue
            yield {"type": "tool_start", "name": "web_search"}
            t0 = time.perf_counter()
            raw = await run_tool(
                "web_search",
                {"query": state.query, "max_results": 3, "fetch_top": 2},
            )
            yield {"type": "tool_result", "name": "web_search", "content": raw}
            data = _loads(raw)
            _record_external(state, "web_search", data, trace=trace, started=t0)
            if data.get("hits"):
                state.webbed = True
                if state.plan.force_web or state.plan.intent == Intent.WEB:
                    state.hits = merge_hits(data["hits"], state.hits)[:8]
                else:
                    state.hits = merge_hits(state.hits, data["hits"])[:8]
            state.add_observation("web_search", {"count": data.get("count", 0)})

        elif step == "get_current_time":
            yield {"type": "tool_start", "name": "get_current_time"}
            raw = await run_tool("get_current_time", {"timezone": "Asia/Shanghai"})
            yield {"type": "tool_result", "name": "get_current_time", "content": raw}
            state.add_observation("get_current_time", _loads(raw))
            state.answer_hint = "time"

        elif step == "calculator":
            expr = _guess_expr(state.query)
            yield {"type": "tool_start", "name": "calculator"}
            raw = await run_tool("calculator", {"expression": expr})
            yield {"type": "tool_result", "name": "calculator", "content": raw}
            state.add_observation("calculator", _loads(raw))
            state.answer_hint = "calc"

        elif step == "learn_knowledge" and state.plan.learn_payload:
            title, content = state.plan.learn_payload
            yield {"type": "tool_start", "name": "learn_knowledge"}
            raw = await run_tool("learn_knowledge", {"title": title, "content": content})
            yield {"type": "tool_result", "name": "learn_knowledge", "content": raw}
            state.add_observation("learn_knowledge", _loads(raw))
            state.answer_hint = "learn"

        elif step == "search_graph":
            # P4: graph failure / disabled → empty triples; document hits untouched
            yield {"type": "tool_start", "name": "search_graph"}
            t0 = time.perf_counter()
            raw = await run_tool(
                "search_graph",
                {
                    "query": state.query,
                    "hops": int(settings.rag_graph_hops),
                    "top_k": 6,
                },
            )
            yield {"type": "tool_result", "name": "search_graph", "content": raw}
            data = _loads(raw)
            status = data.get("status") or "ok"
            triples = data.get("triples") or []
            if status == "ok" and triples:
                try:
                    from app.rag.graph_query import triples_to_hits

                    graph_hits = triples_to_hits(triples, limit=6)
                    # Prefer document hits; append graph as supplement
                    state.hits = merge_hits(state.hits, graph_hits)[:8]
                except Exception:  # noqa: BLE001
                    pass
            state.add_observation(
                "search_graph",
                {"status": status, "count": len(triples)},
            )
            if trace is not None:
                with trace.span(
                    "tool_search_graph",
                    status=status,
                    count=len(triples),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                ):
                    pass


def _loads(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _guess_expr(text: str) -> str:
    expr = "12+30"
    for token in text.replace("＝", "=").split():
        if any(ch.isdigit() for ch in token) and any(op in token for op in "+-*/"):
            return token
    return expr


def build_react_thinking(state: LoopState) -> str:
    """Compact Thought/Action/Observation for deep-think UI (keep short for speed)."""
    lines = [
        f"意图：{state.plan.intent.value}｜问题：{state.query[:80]}",
        f"计划：{' → '.join(state.plan.steps)}",
    ]
    for obs in state.observations[:4]:
        tool = obs.get("tool")
        content = obs.get("content")
        if isinstance(content, dict):
            summary = json.dumps(content, ensure_ascii=False)[:80]
        else:
            summary = str(content)[:80]
        lines.append(f"{tool} → {summary}")
    if state.circuit and state.circuit.opened:
        lines.append(f"外网熔断已开启（连续失败 {state.circuit.fail_streak}）→ 仅用本地材料。")
    lines.append(f"材料 {len(state.hits)} 条 → 综合改写为面向问题的回答。")
    return "\n".join(lines)
