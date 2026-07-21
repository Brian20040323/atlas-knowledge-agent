"""Tests for the ReAct agent loop utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.loop import (
    LoopState,
    _loads,
    _guess_expr,
    build_react_thinking,
)
from app.agents.planner import AgentPlan, Intent


def test_loop_state_init():
    plan = AgentPlan(intent=Intent.LOCAL, query="test query", steps=["search", "answer"])
    state = LoopState(query="test query", plan=plan)
    assert state.query == "test query"
    assert state.observations == []
    assert state.hits == []
    assert state.researched is False
    assert state.webbed is False


def test_loop_state_add_observation():
    plan = AgentPlan(intent=Intent.LOCAL, query="test", steps=["search"])
    state = LoopState(query="test", plan=plan)
    state.add_observation("search_knowledge", {"count": 3})
    assert len(state.observations) == 1
    assert state.observations[0]["tool"] == "search_knowledge"
    assert state.observations[0]["content"]["count"] == 3


def test_loads_valid_json():
    result = _loads('{"key": "value"}')
    assert result == {"key": "value"}


def test_loads_invalid_json():
    result = _loads("not json at all")
    assert result == {}


def test_guess_expr():
    assert "12+30" in _guess_expr("璁＄畻 12+30")
    assert any(ch.isdigit() for ch in _guess_expr("hello world"))


def test_build_react_thinking():
    plan = AgentPlan(
        intent=Intent.LOCAL,
        query="娴嬭瘯闂",
        steps=["search_knowledge", "synthesize"],
    )
    state = LoopState(query="娴嬭瘯闂", plan=plan)
    thinking = build_react_thinking(state)
    assert "娴嬭瘯闂" in thinking
    assert "search_knowledge" in thinking
    assert "synthesize" in thinking


def test_build_react_thinking_with_observations():
    plan = AgentPlan(intent=Intent.LOCAL, query="test", steps=["search", "answer"])
    state = LoopState(query="test", plan=plan)
    state.add_observation("search_knowledge", {"count": 2})
    thinking = build_react_thinking(state)
    assert "search_knowledge" in thinking