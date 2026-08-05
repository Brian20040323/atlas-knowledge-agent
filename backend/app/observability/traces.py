"""Lightweight agent run tracing — internship-friendly observability without Langfuse."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    name: str
    started_at: float
    ended_at: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return round((end - self.started_at) * 1000, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
            "error": self.error,
        }


@dataclass
class AgentTrace:
    run_id: str
    query: str
    started_at: float = field(default_factory=time.perf_counter)
    ended_at: float | None = None
    spans: list[Span] = field(default_factory=list)
    intent: str = ""
    mode: str = ""
    hit_count: int = 0
    answer_chars: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def span(self, name: str, **meta: Any) -> "_SpanCtx":
        return _SpanCtx(self, name, meta)

    def finish(self, *, mode: str = "", answer: str = "") -> dict[str, Any]:
        self.ended_at = time.perf_counter()
        self.mode = mode or self.mode
        self.answer_chars = len(answer or "")
        return self.to_dict()

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return round((end - self.started_at) * 1000, 1)

    def to_graph(self) -> dict[str, Any]:
        """Execution graph for UI (observe a run — not a Flowise-style editor)."""
        return run_payload_to_graph(
            {
                "run_id": self.run_id,
                "query": self.query,
                "intent": self.intent,
                "mode": self.mode,
                "hit_count": self.hit_count,
                "answer_chars": self.answer_chars,
                "duration_ms": self.duration_ms,
                "spans": [s.to_dict() for s in self.spans],
                "meta": self.meta,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "query": self.query[:200],
            "intent": self.intent,
            "mode": self.mode,
            "hit_count": self.hit_count,
            "answer_chars": self.answer_chars,
            "duration_ms": self.duration_ms,
            "spans": [s.to_dict() for s in self.spans],
            "graph": self.to_graph(),
        }
        if self.meta:
            payload["meta"] = self.meta
        return payload


STAGE_ORDER = ("input", "reason", "execute", "answer")
_DETAIL_WHITELIST = ("query_summary", "result_count", "model", "fallback", "error_type")
_ERROR_MAX = 300


def _span_type(name: str) -> str:
    n = (name or "").lower()
    if n.startswith("retrieve") or n in {"rag", "search_knowledge", "search_graph"}:
        return "retrieve"
    if n == "plan" or n.startswith("plan_"):
        return "plan"
    if n.startswith("tool_") or n in {
        "web_search",
        "research_topics",
        "learn_knowledge",
        "calculator",
        "get_current_time",
    }:
        return "tool"
    if n in {"synthesize", "answer", "draft", "llm"} or n.startswith("synth") or n.startswith("llm_"):
        return "step"
    if "guard" in n:
        return "guard"
    return "step"


def _stage_for_type(ntype: str, name: str = "") -> str:
    n = (name or "").lower()
    if ntype == "input":
        return "input"
    if ntype in {"plan", "guard"}:
        return "reason"
    if n.startswith("llm_") or n in {"synthesize", "answer_cache"} or ntype in {"reflect", "answer"}:
        return "answer"
    if ntype in {"tool", "retrieve", "step"}:
        return "execute"
    return "execute"


def _whitelisted_detail(meta: Any, error: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(meta, dict):
        if meta.get("query") is not None:
            out["query_summary"] = str(meta.get("query"))[:120]
        if meta.get("result_count") is not None:
            out["result_count"] = meta.get("result_count")
        if meta.get("model") is not None:
            out["model"] = str(meta.get("model"))[:80]
        if meta.get("fallback") is not None:
            out["fallback"] = bool(meta.get("fallback"))
    if error:
        out["error_type"] = str(error).split(":", 1)[0][:80]
        out["error_type"] = out["error_type"][:_ERROR_MAX]
    return {k: v for k, v in out.items() if k in _DETAIL_WHITELIST and v is not None}


def _has_cycle(edges: list[dict[str, str]]) -> bool:
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e["target"])
    visiting: set[str] = set()
    done: set[str] = set()

    def dfs(n: str) -> bool:
        if n in done:
            return False
        if n in visiting:
            return True
        visiting.add(n)
        for nxt in adj.get(n, []):
            if dfs(nxt):
                return True
        visiting.remove(n)
        done.add(n)
        return False

    return any(dfs(n) for n in list(adj))


def normalize_graph(payload: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    nodes_in = list(payload.get("nodes") or [])
    edges_in = list(payload.get("edges") or [])
    by_id: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for i, raw in enumerate(nodes_in):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or f"n{i}")
        ntype = str(raw.get("type") or "step")
        if ntype in {"start"}:
            ntype = "input"
        if ntype in {"final", "llm"}:
            ntype = "answer" if ntype == "final" else "step"
        if ntype not in {"input", "plan", "retrieve", "tool", "reflect", "answer", "guard", "step"}:
            ntype = "step"
        stage = str(raw.get("stage") or _stage_for_type(ntype))
        if stage not in STAGE_ORDER:
            stage = _stage_for_type(ntype)
        status = str(raw.get("status") or "success")
        if status in {"ok", "done"}:
            status = "success"
        if status == "fail":
            status = "error"
        if status not in {"pending", "running", "success", "error", "skipped"}:
            status = "success"
        detail_raw = raw.get("detail")
        if isinstance(detail_raw, dict):
            detail = {k: detail_raw[k] for k in _DETAIL_WHITELIST if k in detail_raw}
        else:
            detail = {}
        node = {
            "id": nid,
            "type": ntype,
            "stage": stage,
            "label": str(raw.get("label") or nid)[:160],
            "status": status,
            "started_ms": raw.get("started_ms") if raw.get("started_ms") is not None else 0,
            "duration_ms": raw.get("duration_ms") if raw.get("duration_ms") is not None else raw.get("ms"),
            "group_id": raw.get("group_id"),
            "detail": detail,
        }
        by_id[nid] = node
        nodes.append(node)

    edges: list[dict[str, str]] = []
    for raw in edges_in:
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            src, tgt, rel = str(raw[0]), str(raw[1]), "sequence"
        elif isinstance(raw, dict):
            src, tgt = str(raw.get("source") or ""), str(raw.get("target") or "")
            rel = str(raw.get("relation") or "sequence")
            if rel not in {"sequence", "parallel"}:
                rel = "sequence"
        else:
            continue
        if src not in by_id or tgt not in by_id:
            notes.append(f"dropped dangling edge {src}->{tgt}")
            continue
        edges.append({"source": src, "target": tgt, "relation": rel})

    if _has_cycle(edges):
        notes.append("cycle detected; UI should fall back to stage list")

    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    tool_count = int(
        summary.get("tool_count")
        if summary.get("tool_count") is not None
        else sum(1 for n in nodes if n["type"] in {"tool", "retrieve"})
    )
    failed_count = int(
        summary.get("failed_count")
        if summary.get("failed_count") is not None
        else sum(1 for n in nodes if n["status"] == "error")
    )
    out: dict[str, Any] = {
        "schema_version": "1.0",
        "run": {
            "id": str(run.get("id") or payload.get("run_id") or ""),
            "status": str(run.get("status") or ("error" if failed_count else "success")),
            "duration_ms": run.get("duration_ms") if run.get("duration_ms") is not None else payload.get("duration_ms"),
            "stop_reason": str(run.get("stop_reason") or payload.get("mode") or ""),
        },
        "summary": {"tool_count": tool_count, "failed_count": failed_count},
        "nodes": nodes,
        "edges": edges,
    }
    if notes:
        out["compat_notes"] = notes
    return out


def stages_from_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    g = normalize_graph(graph)
    buckets: dict[str, list[dict[str, Any]]] = {s: [] for s in STAGE_ORDER}
    for n in g["nodes"]:
        stage = n.get("stage") if n.get("stage") in STAGE_ORDER else _stage_for_type(str(n.get("type") or "step"))
        buckets[stage].append(n)
    labels = {"input": "Input", "reason": "Reason", "execute": "Execute", "answer": "Answer"}
    return [{"id": sid, "label": labels[sid], "nodes": buckets[sid]} for sid in STAGE_ORDER if buckets[sid]]


def run_payload_to_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """Build / rebuild ExecutionGraph v1 from a stored run dict."""
    embedded = payload.get("graph")
    if isinstance(embedded, dict) and embedded.get("schema_version") == "1.0" and embedded.get("nodes"):
        return normalize_graph(embedded)

    nodes: list[dict[str, Any]] = [
        {
            "id": "input",
            "type": "input",
            "stage": "input",
            "label": str(payload.get("query") or "")[:120] or "query",
            "status": "success",
            "started_ms": 0,
            "duration_ms": 0,
            "group_id": None,
            "detail": {"query_summary": str(payload.get("query") or "")[:120]},
        }
    ]
    edges: list[dict[str, str]] = []
    prev_ids = ["input"]
    failed = 0
    tool_count = 0

    intent = str(payload.get("intent") or "").strip()
    if intent:
        nodes.append(
            {
                "id": "intent",
                "type": "plan",
                "stage": "reason",
                "label": intent,
                "status": "success",
                "started_ms": 0,
                "duration_ms": 0,
                "group_id": None,
                "detail": {},
            }
        )
        for p in prev_ids:
            edges.append({"source": p, "target": "intent", "relation": "sequence"})
        prev_ids = ["intent"]

    for i, raw in enumerate(payload.get("spans") or []):
        name = str(raw.get("name") or f"span_{i}")
        # Skip duplicate plan span when intent node already represents planning.
        if name == "plan" and intent:
            continue
        node_id = f"s{i}"
        ntype = _span_type(name)
        stage = _stage_for_type(ntype, name)
        err = raw.get("error")
        status = "error" if err else "success"
        if err:
            failed += 1
        if ntype in {"tool", "retrieve"}:
            tool_count += 1
        meta = raw.get("meta") or {}
        label = name
        if isinstance(meta, dict) and meta.get("query"):
            label = f"{name}: {str(meta.get('query'))[:40]}"
        nodes.append(
            {
                "id": node_id,
                "type": ntype,
                "stage": stage,
                "label": label,
                "status": status,
                "started_ms": 0,
                "duration_ms": raw.get("duration_ms"),
                "group_id": None,
                "detail": _whitelisted_detail(meta, str(err) if err else None),
            }
        )
        for p in prev_ids:
            edges.append({"source": p, "target": node_id, "relation": "sequence"})
        prev_ids = [node_id]

    mode = str(payload.get("mode") or "").strip() or "done"
    run_status = "error" if failed else "success"
    nodes.append(
        {
            "id": "answer",
            "type": "answer",
            "stage": "answer",
            "label": mode,
            "status": run_status,
            "started_ms": 0,
            "duration_ms": 0,
            "group_id": None,
            "detail": {
                "result_count": payload.get("hit_count"),
            },
        }
    )
    # drop None from detail
    nodes[-1]["detail"] = {k: v for k, v in nodes[-1]["detail"].items() if v is not None}
    for p in prev_ids:
        edges.append({"source": p, "target": "answer", "relation": "sequence"})

    return normalize_graph(
        {
            "schema_version": "1.0",
            "run": {
                "id": str(payload.get("run_id") or ""),
                "status": run_status,
                "duration_ms": payload.get("duration_ms"),
                "stop_reason": mode,
            },
            "summary": {"tool_count": tool_count, "failed_count": failed},
            "nodes": nodes,
            "edges": edges,
        }
    )


class _SpanCtx:
    def __init__(self, trace: AgentTrace, name: str, meta: dict[str, Any]):
        self.trace = trace
        self.span_obj = Span(name=name, started_at=time.perf_counter(), meta=dict(meta))

    def __enter__(self) -> Span:
        return self.span_obj

    def __exit__(self, exc_type, exc, tb) -> None:
        self.span_obj.ended_at = time.perf_counter()
        if exc:
            self.span_obj.error = str(exc)[:300]
        self.trace.spans.append(self.span_obj)
        return False


def new_trace(query: str) -> AgentTrace:
    return AgentTrace(run_id=uuid.uuid4().hex[:12], query=query or "")


_RECENT: list[dict[str, Any]] = []
_MAX_RECENT = 40


def _max_recent() -> int:
    try:
        from app.config import get_settings

        return max(1, int(get_settings().trace_max_recent))
    except Exception:  # noqa: BLE001
        return _MAX_RECENT


def remember_run(payload: dict[str, Any]) -> None:
    _RECENT.insert(0, payload)
    del _RECENT[_max_recent() :]


def list_recent_runs(limit: int = 20, user_id: int | None = None) -> list[dict[str, Any]]:
    items = _RECENT[: min(limit * 3, _max_recent())] if user_id is not None else _RECENT
    out: list[dict[str, Any]] = []
    for item in items:
        if user_id is not None:
            meta = item.get("meta") or {}
            if meta.get("user_id") != user_id:
                continue
        out.append(item)
        if len(out) >= min(limit, _max_recent()):
            break
    return out


def get_run(run_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    for item in _RECENT:
        if item.get("run_id") != run_id:
            continue
        if user_id is not None:
            meta = item.get("meta") or {}
            if meta.get("user_id") != user_id:
                return None
        return item
    return None


def dumps_compact(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
