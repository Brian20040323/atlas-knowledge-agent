"""从现有知识库用 DeepSeek V4 Pro 扩写口语问法 → data/expanded_questions.jsonl + .md

Usage:
  .venv\\Scripts\\python.exe scripts\\expand_kb_questions.py --limit 8
  .venv\\Scripts\\python.exe scripts\\expand_kb_questions.py --titles 差旅报销制度,Agent开发知识地图
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def chat(env: dict[str, str], prompt: str) -> str:
    key = env.get("LLM_API_KEY", "")
    base = env.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = env.get("RAG_EXPAND_MODEL") or env.get("RAG_FAQ_MODEL") or "deepseek-v4-pro"
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是企业知识库扩写助手。根据制度/知识原文生成多样化用户问法。"
                        "禁止编造原文没有的数字/条款。只输出 JSON 数组："
                        '[{"query":"...","must_contain":["关键词"]}]'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 900,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["choices"][0]["message"].get("content") or "").strip()


def parse_queries(raw: str) -> list[dict]:
    text = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip())
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("query"):
            out.append(
                {
                    "query": str(item["query"]).strip(),
                    "must_contain": item.get("must_contain") or [],
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"query": item.strip(), "must_contain": []})
    return out


async def main_async(limit: int, titles: list[str] | None) -> None:
    from app.db import crud
    from app.db.session import get_session_maker

    env = load_env()
    if not env.get("LLM_API_KEY"):
        print("LLM_API_KEY missing in .env")
        return

    sm = get_session_maker()
    async with sm() as db:
        docs = await crud.list_documents(db, limit=300)

    # Prefer seed-like / policy / agent docs; skip tiny / FAQ companions
    preferred = []
    others = []
    title_filter = {t.strip() for t in (titles or []) if t.strip()}
    for d in docs:
        title = d.title or ""
        content = d.content or ""
        if title.endswith("FAQ") or "常见问法" in title:
            continue
        if len(content) < 40:
            continue
        if title_filter and title not in title_filter:
            continue
        bucket = preferred if any(
            k in title for k in ("差旅", "Agent", "RAG", "FastAPI", "LangGraph", "记忆", "制度")
        ) else others
        bucket.append(d)

    selected = (preferred + others)[:limit]
    out_jsonl = ROOT / "data" / "expanded_questions.jsonl"
    out_md = ROOT / "data" / "expanded_questions.md"
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    with out_jsonl.open("w", encoding="utf-8") as f:
        for doc in selected:
            title = doc.title or ""
            content = (doc.content or "")[:1400]
            prompt = (
                f"文档标题：{title}\n正文：\n{content}\n\n"
                "生成 6 条口语化问法（含短问、场景问、追问式）。只输出 JSON。"
            )
            try:
                raw = chat(env, prompt)
                queries = parse_queries(raw)
            except Exception as exc:  # noqa: BLE001
                print("FAIL", title, exc)
                continue
            rec = {"title": title, "doc_id": doc.id, "queries": queries, "raw": raw}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rows.append(rec)
            print("OK", title, "n=", len(queries))

    md = ["# 知识库扩写问法（DeepSeek V4 Pro）", ""]
    for rec in rows:
        md.append(f"## 《{rec['title']}》")
        for i, q in enumerate(rec.get("queries") or [], 1):
            md.append(f"{i}. {q.get('query')}")
        md.append("")
    out_md.write_text("\n".join(md), encoding="utf-8")
    print("wrote", out_jsonl)
    print("wrote", out_md)
    print("docs", len(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--titles", type=str, default="")
    args = ap.parse_args()
    titles = [t for t in args.titles.split(",") if t.strip()] or None
    asyncio.run(main_async(args.limit, titles))
