"""Deep thinking and question-grounded answer synthesis."""

from __future__ import annotations

import json
import re
from typing import Any

from app.rag.dialogue_slots import enrich_followup_query
from app.rag.policy_intent import is_policy_question


def build_search_query(messages: list[dict[str, str]]) -> str:
    """Expand short follow-ups via dialogue slots (T4-3), not full answer dump."""
    user = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            user = (m.get("content") or "").strip()
            break
    if not user:
        return ""
    return enrich_followup_query(user, messages) or user


def build_thinking_steps(
    question: str,
    hits: list[dict[str, Any]] | None = None,
    extra_notes: list[str] | None = None,
) -> str:
    lines = [f"理解问题：{question or '（空）'}"]
    if hits:
        titles = "、".join(f"《{h['title']}》" for h in hits[:5])
        lines.append(f"可用材料 {len(hits)} 条：{titles}")
        lines.append("抽取与问题直接相关的事实，合并冲突信息，组织成连贯回答。")
    else:
        lines.append("暂无足够库内证据；将如实说明缺口并给出可执行的补充方式。")
    if extra_notes:
        lines.extend(extra_notes)
    lines.append("输出：先结论，再要点，文末给参考；避免模板套话。")
    return "\n".join(lines)


def _hit_text(hit: dict[str, Any]) -> str:
    return (hit.get("content") or hit.get("excerpt") or "").strip()


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}", text))
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.update(chinese)
    for i in range(len(chinese) - 1):
        tokens.add(chinese[i] + chinese[i + 1])
    return {t for t in tokens if t}


def _split_points(text: str) -> list[str]:
    """Split knowledge into answerable points, preserving original order."""
    text = text.strip()
    if not text:
        return []

    # Allow digits inside a point (e.g. 「上限 500 元」); only split on N) / N. markers.
    inline = re.findall(
        r"(\d+)\s*[)）.、]\s*(.*?)(?=\s*\d+\s*[)）.、]|$)",
        text,
        flags=re.DOTALL,
    )
    if len(inline) >= 2:
        strip_chars = " ；;，,。 \n"
        return [f"{n}) {body.strip(strip_chars)}" for n, body in inline]

    parts = re.split(r"(?:^|\n)\s*(?:\d+[)）.、]|[-*•])\s*", text)
    parts = [p.strip() for p in parts if p and p.strip()]
    if len(parts) >= 2:
        return parts

    parts = re.split(r"(?<=[。！？；;])\s*", text)
    parts = [p.strip() for p in parts if len(p.strip()) >= 6]
    return parts or [text]


def _rank_points(question: str, hits: list[dict[str, Any]]) -> list[tuple[float, str, str]]:
    q_tokens = _tokenize(question)
    ranked: list[tuple[float, str, str]] = []
    for hit in hits:
        title = hit.get("title", "未命名")
        for point in _split_points(_hit_text(hit)):
            overlap = len(q_tokens & _tokenize(point + " " + title))
            score = overlap + float(hit.get("score") or 0) * 0.05
            if score > 0 or len(hits) <= 2:
                ranked.append((score, title, point))
    ranked.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    unique: list[tuple[float, str, str]] = []
    for item in ranked:
        key = item[2][:40]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _extract_ordered_from_best_hit(
    question: str, hits: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    if not hits:
        return []
    # Prefer the hit that actually contains answer cues (e.g. 经济舱), not FAQ question-only chunks
    boost_keys: list[str] = []
    if any(k in question for k in ("机票", "舱", "飞机")):
        boost_keys.extend(["经济舱", "机票", "实报实销"])
    if any(k in question for k in ("住宿", "房费", "酒店", "宾馆")):
        boost_keys.extend(["住宿费", "500", "上限"])
    if any(k in question for k in ("附件", "材料", "单据", "发票")):
        boost_keys.extend(["发票", "行程单", "审批单"])

    def _hit_rank(h: dict[str, Any]) -> float:
        text = _hit_text(h)
        return float(h.get("score") or 0) + sum(4.0 for b in boost_keys if b in text)

    best = max(hits[:5], key=_hit_rank)
    # Web snippets: keep as whole paragraphs, don't split markdown menus
    if best.get("source_type") == "web" or str(best.get("source") or "").startswith("http"):
        return []
    title = best.get("title", "未命名")
    points = _split_points(_hit_text(best))
    if len(points) < 2:
        return []
    # Only dump the full ordered list for genuinely broad / roadmap questions
    broad = any(
        k in question
        for k in ("学习哪些", "学习路线", "怎么学", "知识地图", "整体要点", "制度全文", "包含哪些知识")
    )
    if broad:
        return [(title, p) for p in points]

    q_tokens = {t for t in _tokenize(question) if len(t) >= 2}
    stop = {"什么", "怎么", "如何", "哪些", "可以", "需要", "多少", "是否", "一个", "这个", "那个"}
    q_tokens -= stop

    # Domain boosts: colloquial 「标准」 must not lose to 「超标准」
    boosts: list[str] = []
    if any(k in question for k in ("住宿", "房费", "酒店", "宾馆", "一晚")) and any(
        k in question for k in ("标准", "上限", "额度", "限额", "多少", "报")
    ):
        boosts.extend(["住宿费", "上限", "500"])
    if any(k in question for k in ("机票", "舱", "飞机")):
        boosts.extend(["经济舱", "机票"])
    if any(k in question for k in ("附件", "材料", "单据", "发票", "行程单", "审批单")):
        boosts.extend(["发票", "行程单", "审批单"])
    if any(k in question for k in ("超标", "超过", "超了")):
        boosts.extend(["超标准", "书面说明"])
    if any(k in question for k in ("适用", "谁", "正式员工", "临时工", "外包")):
        boosts.extend(["正式员工", "境内"])

    scored: list[tuple[int, str, str]] = []
    for p in points:
        # Score against point body only — title tokens would match every clause
        p_tokens = {t for t in _tokenize(p) if len(t) >= 2}
        overlap = len(q_tokens & p_tokens)
        for b in boosts:
            if b in p:
                overlap += 3
        # Penalize weak 「标准」 hit that only comes from 「超标准」 when asking lodging cap
        if "标准" in question and "超标准" in p and "住宿" in question and "住宿费" not in p:
            overlap = max(0, overlap - 2)
        # Prefer concrete answers over FAQ question stems
        if p.strip().startswith("Q") and "？" in p and not any(b in p for b in boosts if b != "机票"):
            overlap = max(0, overlap - 2)
        scored.append((overlap, title, p))
    scored.sort(key=lambda x: x[0], reverse=True)

    specific = any(
        k in question
        for k in (
            "上限",
            "标准",
            "多少",
            "能否",
            "可以吗",
            "要不要",
            "必须",
            "谁",
            "适用",
            "附件",
            "材料",
            "发票",
            "机票",
            "舱",
            "超标",
            "境内",
        )
    )
    best_score = scored[0][0] if scored else 0
    if specific and best_score > 0:
        # Keep the strongest clause(s); avoid dumping the whole policy
        kept = [(t, p) for s, t, p in scored if s >= best_score]
        return kept[:2]

    selected = [(t, p) for s, t, p in scored if s > 0]
    if selected:
        return selected[:3]
    return [(title, p) for p in points[:3]]


def _prev_assistant(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    for m in reversed(history):
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""


def _direct_block(prev: str) -> str:
    """Extract the main answer body from a previous assistant message."""
    text = prev or ""
    if "【直接回答】" in text:
        block = text.split("【直接回答】", 1)[1]
        for stop in ("【依据】", "【不确定点】", "【下一步】", "【说明】", "【参考】"):
            if stop in block:
                block = block.split(stop, 1)[0]
        return block.strip()
    # New markdown style: drop trailing 参考 section
    for stop in ("\n## 参考", "\n### 参考", "\n参考来源", "\n**参考**"):
        if stop in text:
            text = text.split(stop, 1)[0]
    return text.strip()


def _followup_point_index(question: str) -> int | None:
    m = re.search(r"第\s*([0-9一二三四五六七八九十]+)\s*点", question)
    if not m:
        m = re.search(r"(?:展开|详细|说说)\s*([0-9一二三四五六七八九十]+)", question)
    if not m:
        return None
    raw = m.group(1)
    mapping = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    return mapping.get(raw) or (int(raw) if raw.isdigit() else None)


def _extract_numbered_point(prev: str, idx: int) -> str | None:
    direct_block = _direct_block(prev)
    points = re.findall(
        r"(?:^|\n)\s*(\d+)\s*[)）.、]\s*(.+?)(?=(?:\n\s*\d+\s*[)）.、])|$)",
        direct_block,
        re.S,
    )
    for num, body in points:
        if int(num) == idx:
            return re.sub(r"（来源：.*?）\s*$", "", body.strip()).strip()
    inline = re.findall(
        r"(\d+)\s*[)）.、]\s*([^0-9\n]+?)(?=\s*\d+\s*[)）.、]|$)",
        direct_block,
    )
    for num, body in inline:
        if int(num) == idx:
            return body.strip(" ；;，,")
    return None


def _followup_from_history(question: str, history: list[dict[str, str]] | None) -> str | None:
    """Handle '展开第N点' by expanding the matching point from last answer."""
    prev = _prev_assistant(history)
    if not prev:
        return None
    idx = _followup_point_index(question)
    if not idx:
        return None
    point = _extract_numbered_point(prev, idx)
    if not point:
        return None
    return (
        f"针对上一轮第 {idx} 点，可以这样理解：\n\n"
        f"{point}\n\n"
        "如果你想继续深挖，可以直接问「为什么…」或「怎么落地…」。"
    )


def _focus_topic(question: str, history: list[dict[str, str]] | None) -> str | None:
    """For why/how follow-ups, focus on the topic mentioned or last expanded point."""
    why_keys = ("为什么", "怎么", "如何", "为何", "详细", "具体")
    if not any(k in question for k in why_keys):
        return None

    # Prefer explicit topic in the question after the cue word
    for cue in why_keys:
        if cue in question:
            after = question.split(cue, 1)[1]
            after = re.sub(r"^(需要|要|是|了|呢|啊|吗|的)+", "", after).strip(" ？?。.!！")
            if len(after) >= 2:
                return after

    prev = _prev_assistant(history)
    if not prev:
        return None
    # Last answer was a single-point expansion
    if "针对上一轮" in prev or "针对你追问的内容" in prev:
        block = _direct_block(prev)
        line = re.sub(r"^针对[^\n：:]*[：:]\s*", "", block).strip().split("\n", 1)[0]
        line = re.sub(r"（来源：.*?）\s*$", "", line).strip()
        if line:
            return line
    return None


def _answer_focused_topic(topic: str, hits: list[dict[str, Any]]) -> str | None:
    """Build a focused answer around one topic using matching knowledge snippets."""
    topic_tokens = _tokenize(topic)
    if not topic_tokens:
        return None

    matched: list[tuple[str, str]] = []
    for hit in hits:
        title = hit.get("title", "未命名")
        text = _hit_text(hit)
        topic_body = {t for t in topic_tokens if len(t) >= 2}
        for point in _split_points(text):
            p_tokens = {t for t in _tokenize(point) if len(t) >= 2}
            if topic_body & p_tokens:
                matched.append((title, point))
        if topic_body & {t for t in _tokenize(text) if len(t) >= 2} and len(_split_points(text)) < 2:
            matched.append((title, text))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for title, point in matched:
        key = point[:48]
        if key in seen:
            continue
        seen.add(key)
        unique.append((title, point))

    if not unique:
        return None

    cited_hits: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for title, _point in unique[:5]:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        match = next((h for h in hits if (h.get("title") or "") == title), None)
        cited_hits.append(match or {"title": title})
    refs = _format_refs(cited_hits) if cited_hits else "、".join(f"《{t}》" for t, _ in unique[:5])

    if len(unique) == 1:
        title, point = unique[0]
        body = f"依据《{title}》，{_clean_point_text(point)}。"
    else:
        lead = f"**{topic}**：结合现有材料，核心可以概括如下。"
        bullets = "\n".join(f"- {_clean_point_text(p)}" for _, p in unique[:5])
        body = f"{lead}\n\n{bullets}"

    if refs.startswith("-") or "document_id=" in refs:
        return f"{body}\n\n**参考**\n{refs}"
    return f"{body}\n\n**参考：** {refs}"


def _clean_point_text(point: str) -> str:
    return re.sub(r"^\d+\s*[)）.、]\s*", "", point).strip()


_GENERAL_FRAMEWORKS: list[tuple[tuple[str, ...], str]] = [
    (
        ("agent", "智能体", "多智能体", "multi-agent"),
        "系统学习 Agent 时，除了模型调用本身，通常还要补齐：评测集、Tracing、权限与安全边界、部署运维。",
    ),
]


def _general_supplement(question: str) -> str:
    q = question.lower()
    for keys, text in _GENERAL_FRAMEWORKS:
        if any(k in q for k in keys):
            return text
    return ""


def _clean_snippet(text: str, limit: int = 280) -> str:
    body = re.sub(r"\n*来源：\S+\s*$", "", text).strip()
    body = re.sub(r"(?i)published time:\s*[^\n]+", "", body).strip()
    body = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    return body


def _format_refs(hits: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for h in hits[:5]:
        title = h.get("title") or "未命名"
        src = (h.get("source") or "").strip()
        doc_id = h.get("id")
        chunk_id = h.get("chunk_id")
        chunk_total = h.get("chunk_total", 0)

        # 分块溯源（T7-5）
        chunk_suffix = ""
        if chunk_id is not None and chunk_id >= 0:
            if chunk_total:
                chunk_suffix = f" 第{chunk_id + 1}/{chunk_total}段"
            else:
                chunk_suffix = f" 第{chunk_id + 1}段"

        id_suffix = f"（document_id={doc_id}）" if doc_id is not None else ""
        if src.startswith("http"):
            lines.append(f"- [{title}]({src}){chunk_suffix}{id_suffix}")
        else:
            lines.append(f"- 《{title}》{chunk_suffix}{id_suffix}")
    return "\n".join(lines)


def synthesize_knowledge_answer(
    question: str,
    hits: list[dict[str, Any]],
    history: list[dict[str, str]] | None = None,
) -> str:
    """Synthesize a GPT-like answer from retrieved snippets (mock / offline path)."""
    follow = _followup_from_history(question, history)
    if follow:
        return follow

    topic = _focus_topic(question, history)
    if topic:
        focused = _answer_focused_topic(topic, hits)
        if focused:
            return focused

    supplement = _general_supplement(question)
    if not hits:
        from app.rag.web_search import parse_web_search_intent, wants_online_search

        if wants_online_search(question) or parse_web_search_intent(question):
            topic = parse_web_search_intent(question) or question
            return (
                f"目前掌握的材料还不足以完整回答「{topic}」。\n\n"
                "已尝试联网检索，但当前没有拿到可用网页摘要"
                "（开放搜索接口在本地环境常被限流或超时）。\n\n"
                "建议：稍后再试、把问题写得更具体，或在 `.env` 配置 `LLM_API_KEY` "
                "后用真实模型做摘要。制度类问题仍请优先查本地知识库。"
            )
        if is_policy_question(question):
            parts = [
                f"目前掌握的材料还不足以完整回答「{question}」。",
                "不能凭推测给出制度条款或具体额度。请补充相关制度文档"
                "（上传或「记住：标题|内容」），或向 HR/行政确认。",
            ]
        else:
            parts = [
                f"目前掌握的材料还不足以完整回答「{question}」。",
                "你可以导入相关文件，或用「记住：标题|内容」「自主学习：主题」「联网：主题」补充后再问。",
            ]
        if supplement:
            parts.append(supplement)
        return "\n\n".join(parts)

    webby = any(
        h.get("source_type") == "web"
        or str(h.get("source") or "").startswith("http")
        or "来源：http" in _hit_text(h)
        for h in hits[:4]
    )
    ordered = [] if webby else _extract_ordered_from_best_hit(question, hits)
    focus = _tokenize(question)
    stop = {
        "什么", "怎么", "如何", "哪些", "一个", "这个", "那个", "可以", "需要",
        "学习", "介绍", "一下", "历史", "地理", "的", "与", "和", "及",
    }
    focus = {t for t in focus if t not in stop and len(t) >= 2}

    cited = [hits[0]]
    for hit in hits[1:]:
        title = hit.get("title", "")
        text = _hit_text(hit)
        if not focus or len(focus & _tokenize(title + " " + text[:300])) >= 2:
            cited.append(hit)
    cited = cited[:5]

    if ordered:
        if len(ordered) == 1:
            title, point = ordered[0]
            answer = f"依据《{title}》，{_clean_point_text(point)}。"
        else:
            lead = f"关于「{question}」，可以按下面几条来把握："
            body = "\n".join(
                f"{i}. {_clean_point_text(point)}" for i, (_title, point) in enumerate(ordered, 1)
            )
            answer = f"{lead}\n\n{body}"
            if len(ordered) >= 3:
                answer += "\n\n想深入某一条，直接说「展开第N点」即可。"
    elif webby:
        lead = f"结合公开网页检索，关于「{question}」目前较一致的信息是："
        bullets: list[str] = []
        for h in cited:
            body = _clean_snippet(_hit_text(h), 240)
            if len(body) < 18:
                continue
            title = h.get("title") or "网页"
            bullets.append(f"- **{title}**：{body}")
        if not bullets:
            answer = f"检索到了相关网页，但摘要过短，暂时无法可靠概括「{question}」。"
        else:
            answer = lead + "\n\n" + "\n".join(bullets[:5])
    else:
        ranked = _rank_points(question, hits)[:6]
        if ranked:
            lead = f"针对「{question}」，综合知识库后的要点如下："
            body = "\n".join(
                f"{i}. {_clean_point_text(point)}"
                for i, (_s, _title, point) in enumerate(ranked, 1)
            )
            answer = f"{lead}\n\n{body}"
        else:
            chunks = [
                f"- **{h.get('title', '未命名')}**：{_clean_snippet(_hit_text(h), 180)}"
                for h in cited[:4]
            ]
            answer = f"与「{question}」相关的材料如下：\n\n" + "\n".join(chunks)

    refs = _format_refs(cited)
    if refs:
        answer += f"\n\n**参考**\n{refs}"

    weak = float(cited[0].get("score") or 0) < 5 if cited else True
    if weak and not webby:
        answer += "\n\n*现有材料相关度一般，结论可能不完整；补充文档后可以再问得更准。*"
    if supplement and (not ordered or len(ordered) < 3):
        answer += f"\n\n{supplement}"
    return answer


def synthesize_tool_answer(tool_name: str, tool_data: dict[str, Any]) -> str:
    if tool_name == "get_current_time":
        return f"现在是 **{tool_data.get('readable')}**（{tool_data.get('timezone')}）。"
    if tool_name == "calculator":
        return f"**{tool_data.get('expression')} = {tool_data.get('result')}**"
    return json.dumps(tool_data, ensure_ascii=False)


THINKING_PROMPT_VERSION = "thinking_append_v1"
PROMPT_SYNTH_VERSION = "policy_synth_v1"
THINKING_SYSTEM_APPEND = """
【深度思考模式】
请用以下标签包裹输出（标签本身不要展示给用户）：
<thinking>
用简短要点写出：问题本质、可用证据、取舍与风险。不要写流水账。
</thinking>
<answer>
用自然、专业的 Markdown 回答：
1) 开头直接给结论；
2) 中间展开关键论据与结构；
3) 文末用「**参考**」列出标题/链接。
涉及本公司制度时：无检索依据不得编造条款或数字。
禁止使用【直接回答】【依据】【下一步】等固定套话标题；不要复述内部规划或工具调用过程。
</answer>
"""


class ThinkingStreamParser:
    """Incremental parser for <thinking> and <answer> blocks."""

    OPEN_TAGS = {"thinking": "<thinking>", "answer": "<answer>"}
    CLOSE_TAGS = {"thinking": "</thinking>", "answer": "</answer>"}

    def __init__(self) -> None:
        self.buffer = ""
        self.section: str | None = None

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.buffer += chunk
        events: list[tuple[str, str]] = []

        while self.buffer:
            if self.section is None:
                opened = self._try_open()
                if opened:
                    self.section = opened
                    events.append((f"{opened}_start", ""))
                    continue
                if len(self.buffer) > 30:
                    self.buffer = self.buffer[-20:]
                break

            close_tag = self.CLOSE_TAGS[self.section]
            lower_buf = self.buffer.lower()
            close_idx = lower_buf.find(close_tag)
            if close_idx == -1:
                keep = len(close_tag) - 1
                emit_len = max(0, len(self.buffer) - keep)
                if emit_len:
                    token = self.buffer[:emit_len]
                    self.buffer = self.buffer[emit_len:]
                    event_type = "thinking_token" if self.section == "thinking" else "token"
                    events.append((event_type, token))
                break

            token = self.buffer[:close_idx]
            if token:
                event_type = "thinking_token" if self.section == "thinking" else "token"
                events.append((event_type, token))
            self.buffer = self.buffer[close_idx + len(close_tag) :]
            events.append((f"{self.section}_done", ""))
            self.section = None

        return events

    def flush(self) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if self.buffer and self.section:
            event_type = "thinking_token" if self.section == "thinking" else "token"
            events.append((event_type, self.buffer))
            events.append((f"{self.section}_done", ""))
            self.buffer = ""
            self.section = None
        return events

    def _try_open(self) -> str | None:
        lower = self.buffer.lower()
        for name, tag in self.OPEN_TAGS.items():
            idx = lower.find(tag)
            if idx != -1:
                self.buffer = self.buffer[idx + len(tag) :]
                return name
        return None


def split_thinking_response(text: str) -> tuple[str, str]:
    thinking_match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL | re.IGNORECASE)
    answer_match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    thinking = thinking_match.group(1).strip() if thinking_match else ""
    answer = answer_match.group(1).strip() if answer_match else text.strip()
    return thinking, sanitize_assistant_text(answer)


def sanitize_assistant_text(text: str) -> str:
    """Strip leaked tool-call markup (DeepSeek DSML / XML) so users never see raw invoke blocks."""
    if not text:
        return ""
    t = str(text)
    # DeepSeek DSML (incl. spaced forms like `< | DSML | invoke ...>`)
    t = re.sub(
        r"<\s*\|\s*DSML\s*\|[\s\S]*?(?:</\s*\|\s*DSML\s*\|?>|$)",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"<\|?\s*DSML\s*\|?>[\s\S]*?(?:</\|?\s*DSML\s*\|?>|$)", " ", t, flags=re.I)
    t = re.sub(r"</?\s*\|\s*DSML\s*\|[^>\n]*>", " ", t, flags=re.I)
    t = re.sub(r"</?\|?\s*DSML\s*\|?[^>\n]*>", " ", t, flags=re.I)
    # DeepSeek / Qwen style: <tool_calls> ... </tool_calls> or bare tool_calls blocks
    t = re.sub(r"<tool_calls?>[\s\S]*?</tool_calls?>", " ", t, flags=re.I)
    t = re.sub(r"</?tool_calls?>", " ", t, flags=re.I)
    t = re.sub(r"<tool_call>[\s\S]*?</tool_call>", " ", t, flags=re.I)
    t = re.sub(r"<function_call>[\s\S]*?</function_call>", " ", t, flags=re.I)
    t = re.sub(
        r"(?is)<tool_calls?>[\s\S]*?(?:name\s*=\s*\"[^\"]+\"[\s\S]*)?(?:</tool_calls?>|$)",
        " ",
        t,
    )
    t = re.sub(r"(?im)^\s*tool_calls?\s*$", " ", t)
    t = re.sub(r"invoke\s+name\s*=\s*\"[^\"]+\"", " ", t, flags=re.I)
    t = re.sub(r"parameter\s+name\s*=\s*\"[^\"]+\"[^>\n]*>", " ", t, flags=re.I)
    t = re.sub(r"</\s*\|\s*DSML\s*\|?\s*parameter>", " ", t, flags=re.I)
    t = re.sub(r"</\|?\s*DSML\s*\|?\s*parameter>", " ", t, flags=re.I)
    t = re.sub(r'name\s*=\s*"(?:web_search|search_knowledge|research_topics)"', " ", t, flags=re.I)
    t = re.sub(r'(?:max_results|fetch_top|top_k)\s*=\s*"?\d+"?', " ", t, flags=re.I)
    # Fenced source / tool schema dumps
    t = re.sub(
        r"```(?:python|json|xml|dsml|typescript|javascript)?\s*[\s\S]*?(?:invoke\s+name|search_knowledge|DSML|tool_calls|web_search)[\s\S]*?```",
        " ",
        t,
        flags=re.I,
    )
    # Truncated stream: drop unfinished tool markup to end of string
    t = re.sub(r"<\s*\|\s*[\s\S]*$", "", t)
    t = re.sub(r"<tool_calls?[\s\S]*$", "", t, flags=re.I)
    t = re.sub(r"invoke\s+name\s*=[\s\S]*$", "", t, flags=re.I)
    t = re.sub(r"parameter\s+name\s*=[\s\S]*$", "", t, flags=re.I)
    if "search_knowledge" in t.lower() and ("top_k" in t.lower() or "parameter" in t.lower()):
        t = re.sub(r"(?i)search_knowledge[\s\S]{0,400}", " ", t)
    if "web_search" in t.lower() and ("max_results" in t.lower() or "query=" in t.lower()):
        t = re.sub(r"(?is)web_search[\s\S]{0,500}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    compact = re.sub(r"\s+", "", t)
    if not compact or (
        len(compact) < 40
        and any(
            k in t.lower()
            for k in ("search_knowledge", "web_search", "top_k", "invoke", "parameter name", "dsml", "tool_calls")
        )
    ):
        return ""
    return t


def looks_like_tool_leak(text: str) -> bool:
    """True when the model dumped tool-call syntax instead of an answer."""
    if not text:
        return False
    low = text.lower()
    markers = (
        "<|dsml|",
        "<| dsml",
        "< | dsml",
        "invoke name=",
        "parameter name=",
        "<tool_call>",
        "<tool_calls>",
        "search_knowledge",
        "web_search",
        'name="web_search"',
        "max_results=",
    )
    hits = sum(1 for m in markers if m in low)
    if hits >= 2:
        return True
    if "dsml" in low and ("invoke" in low or "parameter" in low):
        return True
    if "tool_calls" in low and ("web_search" in low or "search_knowledge" in low):
        return True
    return False


def honest_web_empty_reply(query: str) -> str:
    """Honest user-facing reply when open-web search returned zero usable hits."""
    q = (query or "").strip() or "该主题"
    return (
        f"联网检索未找到与「{q}」相关的可靠公开结果，材料不足，"
        "暂时无法给出具体办学/机构细节或未核实的数据。"
        "你可以补充城市、全称或官网链接后再问。"
    )


def policy_no_evidence_reply(query: str) -> str:
    """User-facing refuse when KB has no matching policy material."""
    q = (query or "").strip() or "该问题"
    return (
        f"知识库里没有与「{q}」直接对应的制度材料，因此无法给出可依据的办理说明。"
        "请补充相关制度文档后再问，或联系人事/行政确认正式流程。"
    )


def synthesize_degraded_rich(
    query: str,
    local_hits: list[dict[str, Any]],
    web_hits: list[dict[str, Any]] | None = None,
    research_hits: list[dict[str, Any]] | None = None,
    policy_strict: bool = False,
) -> str:
    """
    T7-7 P1 降级：LLM 不可用，但有多来源素材。
    规则式综合本地+联网+研究，分节展示，标注来源。
    """
    parts: list[str] = []
    has_any = False

    if local_hits:
        has_any = True
        parts.append("### 📋 本地知识库")
        for h in local_hits[:3]:
            title = h.get("title", "未命名")
            body = (h.get("excerpt") or h.get("content") or "")[:200]
            chunk_id = h.get("chunk_id")
            chunk_mark = f"（第{chunk_id + 1}段）" if chunk_id is not None and chunk_id >= 0 else ""
            if body:
                parts.append(f"- **《{title}》**{chunk_mark}：{body}")

    if web_hits:
        for wh in web_hits:
            if isinstance(wh, dict):
                results = wh.get("hits") or wh.get("results") or []
            else:
                results = []
            if results:
                has_any = True
                parts.append("### 🌐 联网检索")
                for r in results[:2]:
                    title = r.get("title", "网页")
                    snippet = (r.get("snippet") or r.get("content") or "")[:200]
                    if snippet:
                        parts.append(f"- **{title}**：{snippet}")

    if research_hits:
        for rh in research_hits:
            if isinstance(rh, dict):
                results = rh.get("hits") or []
            else:
                results = []
            if results:
                has_any = True
                parts.append("### 📚 百科研究")
                for r in results[:2]:
                    title = r.get("title", "条目")
                    body = (r.get("excerpt") or r.get("content") or "")[:200]
                    if body:
                        parts.append(f"- **{title}**：{body}")

    if not has_any:
        return (
            f"目前无法回答「{query}」。\n\n"
            "系统当前处于降级模式（LLM 不可用），且所有检索来源均为空。\n"
            "建议：稍后重试，或上传/补充本地文档后重新提问。"
        )

    header = f"关于「{query}」：\n\n"
    disclaimer = (
        "\n\n---\n"
        "*⚠️ LLM 服务暂不可用，以上为检索结果直接展示。回答未经过语言模型综合处理，可能存在不连贯之处。*"
    )

    body = "\n\n".join(parts)
    return header + body + disclaimer
