# Changelog

## 0.3.0 (2025-07)

- Deep thinking: reasoning chain visualization before answer
- Chunk-level citation tracing (T7-5)
- Progressive degradation matrix (T7-7): 4-path fallback
- Policy/inference layer v3 with SYSTEM_PROMPT + query_rewrite (T7-8)
- Prompt injection guard (T7-6)
- Composite query decomposition (T7-2)
- Short-query clarification (T7-1)
- Dialogue slots for multi-turn context tracking (T4-3)

## 0.2.0

- Agent planner + ReAct loop with parallel tool execution
- Hybrid RAG: TF-IDF + lexical + optional vector/graph
- Self-learning: wiki research + auto-save to KB
- Web search: DuckDuckGo + content fetching
- MCP Server/Client for Cursor integration
- TTS (XTTS voice clone + ElevenLabs) / STT (Whisper)
- SQLite persistence for conversations, messages, documents
- Optional knowledge graph (SQLite entities/relations)

## 0.1.0

- Initial release: FastAPI + SSE streaming chat
- Tool calling (time, calculator)
- Mock mode: runs without API key
- Static frontend chat UI
- Basic knowledge base with document upload