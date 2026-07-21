# T7-5 · Chunk 级别溯源方案

> 状态：📋 方案 · 2026-07-21  
> 依据：[06](06-架构分层与迭代计划.md) §4.4 · [09](09-面试追问对照手册.md) Q3 · 字节审查 Q5  
> 目标：引用从「文档级」（《差旅报销制度》）提升到「段落级」（document_id + chunk_id + 原文片段）

---

## 1. 痛点

当前引用格式：
```
**参考**
- 《差旅报销制度》（document_id=p001）
```

面试官会问：「这个 500 元标准具体写在哪一段？能精确指回原文吗？」

**不能。** `document_id` 只能定位到整篇文档，无法定位到具体段落。

---

## 2. 方案设计

### 2.1 核心思路：不改 DB schema，用计算式 chunk_id

当前 chunks 是每次检索时动态切割的（`chunk_text(text, 280, 40)`），不在数据库中存储。因此不需要新增 `chunks` 表。

**方案：记录 chunk 在原文中的索引和内容指纹。**

```python
# 检索结果中新增字段
hit = {
    "title": "差旅报销制度",
    "content": "...",
    "score": 8.5,
    "source_type": "text",
    "id": 1,
    # 🆕 新增
    "chunk_id": 3,          # 分块序号（0-based，相对于该文档）
    "chunk_text": "境内一般地区住宿标准为每人每晚500元以内。...",  # 该分块的原文
}
```

### 2.2 改动范围（3 个文件，~50 行）

| 文件 | 改动 | 行数 |
|------|------|------|
| `rag/knowledge.py` | `search()` 结果中追加 `chunk_id` + `chunk_text` | +8 |
| `rag/knowledge.py` | `format_context()` 格式改为包含分块标记 | +5 |
| `agents/reasoning.py` | `_format_refs()` 引用格式升级 | +5 |
| `agents/reasoning.py` | `synthesize_knowledge_answer()` 用到的新字段 | +3 |
| `rag/hybrid.py` | `_best_chunk_score()` 返回 chunk_index | +5 |

### 2.3 改动细节

#### Step 1: `_best_chunk_score` 返回 chunk_index

```python
# 现在：返回 (score, chunk_text)
# 改为：返回 (score, chunk_text, chunk_index)

def _best_chunk_score(query: str, title: str, content: str) -> tuple[float, str, int]:
    chunks = chunk_text(content, chunk_size=280, overlap=40)
    if not chunks:
        return 0.0, "", -1
    best_score = 0.0
    best_chunk = chunks[0]
    best_idx = 0
    for i, ch in enumerate(chunks):
        s = _score(query, title, ch)
        if s > best_score:
            best_score = s
            best_chunk = ch
            best_idx = i
    full = _score(query, title, content)
    total_chunks = len(chunks)
    if full > best_score:
        return full, content[:500], -1  # -1 = 全文匹配
    return best_score, best_chunk, best_idx
```

#### Step 2: `KnowledgeService.search()` 传递 chunk_id

```python
# 在 search() 的结果构建中
best_score, best_chunk, best_idx = _best_chunk_score(query, doc.title, doc.content)
results.append({
    "id": doc.id,
    "title": doc.title,
    "content": doc.content,
    "excerpt": best_chunk,
    "score": best_score,
    "source_type": doc.source_type,
    "chunk_id": best_idx,       # 🆕
    "chunk_total": total_chunks # 🆕
})
```

#### Step 3: `format_context()` 显示分块标记

```python
# 现在：
blocks.append(f"[{i}] 《{hit['title']}》\n{body}")
# 改为：
chunk_id = hit.get("chunk_id")
if chunk_id is not None and chunk_id >= 0:
    blocks.append(f"[{i}] 《{hit['title']}》§{chunk_id}\n{body}")
else:
    blocks.append(f"[{i}] 《{hit['title']}》\n{body}")
```

#### Step 4: `_format_refs()` 引用格式升级

```python
# 现在：
lines.append(f"- 《{title}》（document_id={doc_id}）")
# 改为：
chunk_id = h.get("chunk_id")
chunk_total = h.get("chunk_total", 0)
if chunk_id is not None and chunk_id >= 0:
    if chunk_total:
        lines.append(f"- 《{title}》第{chunk_id+1}/{chunk_total}段（document_id={doc_id}）")
    else:
        lines.append(f"- 《{title}》第{chunk_id+1}段（document_id={doc_id}）")
else:
    lines.append(f"- 《{title}》（document_id={doc_id}）")
```

#### Step 5: 回答中展示原文片段

在 `synthesize_knowledge_answer` 里，当有 chunk 信息时，附加原文引用：

```python
# 在 _clean_point_text 处理后附加片段引用
if h.get("chunk_id") is not None and h.get("chunk_id") >= 0:
    chunk_text = h.get("chunk_text") or h.get("excerpt", "")
    if len(chunk_text) > 100:
        chunk_text = chunk_text[:100] + "…"
    answer += f"\n\n> 原文：「…{chunk_text}…」"
```

---

## 3. 验收标准

| 编号 | 测试 | 预期 |
|------|------|------|
| A | 问「住宿标准」 | 回答中引用含 `第N/M段` 或 chunk 标记 |
| B | `GET /api/runs` | Trace 中 `top_titles` 包含 chunk 信息 |
| C | `_format_refs` 回归 | 无 chunk 的 hit 仍显示旧格式，不崩溃 |
| D | `run_eval` | 126 基准不退化 |

---

## 4. 风险

| 风险 | 缓解 |
|------|------|
| chunk 边界可能切坏（一句话跨两 chunk） | 重叠 40 字已在用；chunk 标记仅供参考 |
| 全文匹配（chunk_id=-1）时引用格式需特殊处理 | 兜底为旧格式 |
| retriever 接口需同时兼容新旧返回 | `_best_chunk_score` 返回 3 元组，调用侧兼容 |

---

## 5. 回滚策略

- 将 `_best_chunk_score` 改回返回 2 元组
- 删除引用格式中的 chunk 字段
- 不影响检索质量，纯展示层改动
