"""Tests for the reasoning / answer synthesis module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.reasoning import (
    _tokenize,
    _split_points,
    _hit_text,
    build_thinking_steps,
)


def test_tokenize_english():
    tokens = _tokenize("BM25 ranking function for information retrieval")
    assert "bm25" in tokens
    assert "ranking" in tokens
    assert "retrieval" in tokens


def test_tokenize_chinese():
    tokens = _tokenize("娣峰悎妫€绱㈡彁鍗囨晥鏋?)
    assert len(tokens) > 0
    # With bigram, we should get at least some multi-char tokens
    combined = "".join(tokens)
    assert len(combined) > 0


def test_tokenize_mixed():
    tokens = _tokenize("BM25鍜孴F-IDF娣峰悎")
    assert "bm25" in tokens
    assert len(tokens) > 2


def test_split_points_numbered():
    text = "1) 绗竴鏉¤鐐?2) 绗簩鏉¤鐐?3) 绗笁鏉¤鐐?
    points = _split_points(text)
    assert len(points) == 3
    assert "绗竴鏉¤鐐? in points[0]
    assert "绗簩鏉¤鐐? in points[1]


def test_split_points_bullet():
    text = "- 鍔熻兘A
- 鍔熻兘B
- 鍔熻兘C"
    points = _split_points(text)
    assert len(points) == 3
    assert all("鍔熻兘" in p for p in points)


def test_split_points_single():
    text = "杩欐槸涓€涓病鏈夊垎鐐圭殑娈佃惤銆?
    points = _split_points(text)
    assert len(points) >= 1


def test_hit_text():
    hit = {"content": "This is the full content", "excerpt": "short"}
    assert _hit_text(hit) == "This is the full content"

    hit2 = {"excerpt": "only excerpt"}
    assert _hit_text(hit2) == "only excerpt"


def test_build_thinking_steps():
    hits = [{"title": "RAG鍏ラ棬"}, {"title": "BM25璇﹁В"}, {"title": "RRF铻嶅悎"}]
    steps = build_thinking_steps("浠€涔堟槸RAG", hits)
    assert "RAG鍏ラ棬" in steps
    assert "BM25璇﹁В" in steps
    assert "鍙敤鏉愭枡" in steps
    assert "3 鏉? in steps


def test_build_thinking_steps_empty():
    steps = build_thinking_steps("鏈煡闂", [])
    assert "鏆傛棤瓒冲" in steps
    assert "濡傚疄璇存槑" in steps


def test_build_thinking_steps_with_notes():
    steps = build_thinking_steps("test", extra_notes=["娉ㄦ剰锛氳繖鏄祴璇?])
    assert "娉ㄦ剰锛氳繖鏄祴璇? in steps