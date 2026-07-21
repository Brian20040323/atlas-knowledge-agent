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
        }
        if self.meta:
            payload["meta"] = self.meta
        return payload


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


def list_recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    return _RECENT[: min(limit, _max_recent())]


def get_run(run_id: str) -> dict[str, Any] | None:
    for item in _RECENT:
        if item.get("run_id") == run_id:
            return item
    return None


def dumps_compact(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
