"""答辩 / 作品集演示脚本（场景 S1–S5 + 制度金标准）。

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\demo_scenarios.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> int:
    from app.agents.planner import plan_turn
    from app.agents.reasoning import synthesize_knowledge_answer
    from app.config import get_settings
    from app.db.seed import ensure_agent_seed
    from app.db.session import init_db
    from app.rag.knowledge import KnowledgeService
    from app.tools import run_tool

    await init_db()
    await ensure_agent_seed()
    settings = get_settings()
    knowledge = KnowledgeService()

    print("=== Atlas 场景演示（S1–S5 + 制度金标准）===\n")
    print(f"MOCK_MODE → use_mock={settings.use_mock}")
    print(f"RAG_VECTOR_ENABLED={settings.rag_vector_enabled}")
    print(f"RAG_GRAPH_ENABLED={settings.rag_graph_enabled}\n")

    # S1 会话检索并引用
    q1 = "agent开发需要学习哪些知识"
    hits = await knowledge.search(q1, top_k=3)
    plan = plan_turn(q1, hits=hits)
    answer = synthesize_knowledge_answer(q1, hits)
    print(f"[S1] intent={plan.intent.value} hits={len(hits)}")
    print(f"     answer_has_ref={'**参考**' in answer and 'document_id=' in answer}")
    print(f"     preview: {answer[:160].replace(chr(10), ' ')}…\n")

    # S2 显式学习
    learn_raw = await run_tool(
        "learn_knowledge",
        {"title": "演示条目", "content": "这是答辩演示写入的一条知识。"},
    )
    print(f"[S2] learn → {learn_raw[:120]}\n")

    # S3 自主学习意图（不强制外网成功）
    plan3 = plan_turn("自主学习：工业革命", hits=[])
    print(f"[S3] intent={plan3.intent.value} steps={plan3.steps}\n")

    # S4 上传上限（不实际上传文件，校验门禁）
    from app.rag.ingest import IngestLimitError, validate_upload_size

    try:
        validate_upload_size(b"x" * (settings.upload_max_mb * 1024 * 1024 + 1), settings.upload_max_mb)
        print("[S4] upload limit FAILED (should reject)")
    except IngestLimitError as exc:
        print(f"[S4] upload oversize rejected OK: {exc}\n")

    # S5 无 Key / Mock
    print(f"[S5] mock path available: use_mock={settings.use_mock} (缺 Key 时可演示全流程)\n")

    # 制度金标准：有据命中
    q_policy = "差旅住宿费上限是多少？"
    hits_p = await knowledge.search(q_policy, top_k=3)
    plan_p = plan_turn(q_policy, hits=hits_p)
    ans_p = synthesize_knowledge_answer(q_policy, hits_p)
    titles_p = " ".join(h.get("title", "") for h in hits_p)
    print(f"[Policy-HIT] intent={plan_p.intent.value} hits={len(hits_p)} titles≈{titles_p[:40]}")
    print(
        f"             ok_ref={'**参考**' in ans_p and 'document_id=' in ans_p and '500' in ans_p}"
    )
    print(f"             preview: {ans_p[:140].replace(chr(10), ' ')}…\n")

    # 制度金标准：知识缺失拒绝
    q_miss = "完全虚构制度条款ZXQMED999股权激励行权税率是多少"
    hits_m = await knowledge.search(q_miss, top_k=3)
    ans_m = synthesize_knowledge_answer(q_miss, hits_m)
    refuse_ok = ("不足以" in ans_m) and ("一般为" not in ans_m)
    print(f"[Policy-MISS] hits={len(hits_m)} refuse_ok={refuse_ok}")
    print(f"              preview: {ans_m[:140].replace(chr(10), ' ')}…\n")

    print("完成。规范入口：规范文档/README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
