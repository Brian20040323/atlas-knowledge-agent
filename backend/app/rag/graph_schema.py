"""P4 knowledge-graph schema (versioned entity / relation types)."""

from __future__ import annotations

SCHEMA_VERSION = 1

# Minimal typed vocabulary for MVP rule extraction / query
ENTITY_TYPES = frozenset({"Concept", "Technology", "Topic", "Skill", "Framework"})
RELATION_TYPES = frozenset({"is_a", "part_of", "related_to", "uses", "mentions"})

# Seed / domain lexicon → preferred entity type (helps Chinese + English mixed docs)
KNOWN_TERMS: dict[str, str] = {
    "fastapi": "Framework",
    "langgraph": "Framework",
    "rag": "Technology",
    "agent": "Concept",
    "llm": "Technology",
    "mcp": "Technology",
    "prompt": "Skill",
    "tool calling": "Skill",
    "工具调用": "Skill",
    "记忆": "Topic",
    "状态": "Topic",
    "检索": "Technology",
    "评测": "Topic",
    "可观测": "Topic",
    "部署": "Topic",
    "whisper": "Technology",
    "xtts": "Technology",
}
