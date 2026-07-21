"""Tests for the intent planner routing logic."""

import sys
from pathlib import Path

# Ensure backend/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.planner import (
    Intent,
    AgentPlan,
    plan_turn,
    _needs_clarification,
    _is_composite_query,
    _route_normal,
)


def test_learn_intent():
    plan = plan_turn("璁颁綇锛欶astAPI鍏ラ棬|FastAPI鏄疨ython寮傛Web妗嗘灦")
    assert plan.intent == Intent.LEARN


def test_auto_learn_intent():
    plan = plan_turn("鑷富瀛︿範锛氬伐涓氶潻鍛?)
    assert plan.intent == Intent.AUTO_LEARN


def test_web_intent():
    plan = plan_turn("鑱旂綉锛氫粖澶╃鎶€鏂伴椈")
    assert plan.intent == Intent.WEB
    assert plan.force_web is True


def test_tool_time_intent():
    plan = plan_turn("鐜板湪鍑犵偣浜?)
    assert plan.intent == Intent.TOOL_TIME


def test_tool_calc_intent():
    plan = plan_turn("璁＄畻 12+30")
    assert plan.intent == Intent.TOOL_CALC


def test_chitchat_intent():
    plan = plan_turn("浣犲ソ")
    assert plan.intent == Intent.CHITCHAT


def test_clarify_short_query():
    assert _needs_clarification("ReAct", []) is True


def test_clarify_long_query():
    assert _needs_clarification("浠€涔堟槸ReAct浠ｇ悊妯″紡", None) is False


def test_composite_query():
    result = _is_composite_query("浠€涔堟槸RAG锛熶互鍙奙CP鍗忚鎬庝箞鐢紵")
    assert result is True


def test_not_composite():
    result = _is_composite_query("瑙ｉ噴涓€涓婻AG妫€绱㈠寮虹敓鎴?)
    assert result is False


def test_local_intent():
    # With hits, should route to local
    hits = [{"title": "RAG", "score": 8.5, "content": "RAG is..."}]
    plan = plan_turn("RAG鏄粈涔?, hits=hits)
    assert plan.intent in {Intent.LOCAL, Intent.GENERAL}


def test_plan_to_dict():
    plan = AgentPlan(intent=Intent.LOCAL, query="test", steps=["search", "answer"])
    d = plan.to_dict()
    assert d["intent"] == "local"
    assert d["query"] == "test"