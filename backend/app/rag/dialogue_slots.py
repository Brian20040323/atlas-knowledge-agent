"""Dialogue slots for multi-turn policy QA (T4-3).

依据：规范文档 04 §2.4 — 槽位保留制度名/主题，追问改写为完整检索 query。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.policy_intent import POLICY_KEYWORDS, is_policy_question

# Known policy document aliases → canonical slot name
_POLICY_ALIASES: tuple[tuple[str, str], ...] = (
    ("差旅报销", "差旅报销"),
    ("差旅", "差旅报销"),
    ("报销制度", "差旅报销"),
    ("员工制度", "员工制度"),
    ("员工手册", "员工制度"),
    ("人事制度", "员工制度"),
    ("考勤", "考勤"),
    ("年假", "年假"),
    ("请假", "请假"),
    ("薪资", "薪资"),
    ("工资", "薪资"),
)

_TOPIC_HINTS: tuple[str, ...] = (
    "住宿",
    "住宿费",
    "机票",
    "附件",
    "发票",
    "审批",
    "上限",
    "额度",
    "超标",
    "超标准",
    "加班",
    "迟到",
    "薪资",
    "工资",
    "社招",
    "校招",
    "社保",
)

_FOLLOW_KEYS = (
    "这个",
    "那个",
    "展开",
    "详细",
    "具体",
    "第",
    "呢",
    "还有",
    "还需要",
    "为什么",
    "怎么",
    "如何",
    "继续",
    "那",
    "那么",
    "这制度",
    "该制度",
    "适用于谁",
    "怎么办",
)


@dataclass
class DialogueSlots:
    policy_name: str = ""
    topic: str = ""

    def summary(self) -> str:
        parts = []
        if self.policy_name:
            parts.append(f"制度={self.policy_name}")
        if self.topic:
            parts.append(f"主题={self.topic}")
        return "；".join(parts)


def _scan_policy_name(text: str) -> str:
    """Prefer concrete policy aliases; avoid bare keywords like「报销」alone."""
    for alias, canon in _POLICY_ALIASES:
        if alias in text:
            return canon
    return ""


def _scan_topic(text: str) -> str:
    for hint in _TOPIC_HINTS:
        if hint in text:
            return hint
    return ""


def extract_slots(messages: list[dict[str, str]] | None) -> DialogueSlots:
    """Fill slots from recent turns (user + assistant), newest wins for topic."""
    slots = DialogueSlots()
    if not messages:
        return slots
    # Walk chronologically so later turns override topic
    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        # Prefer titles in 《》 as policy_name
        for title in re.findall(r"《([^》]+)》", content):
            if is_policy_question(title) or "制度" in title or "报销" in title:
                slots.policy_name = title.replace("制度", "").strip() or title
                if "差旅" in title:
                    slots.policy_name = "差旅报销"
        name = _scan_policy_name(content)
        if name:
            slots.policy_name = name
        topic = _scan_topic(content)
        if topic:
            slots.topic = topic
    return slots


def is_followup_utterance(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Complete questions are not follow-ups even if short
    if re.match(r"^(什么是|怎样|如何|为什么|介绍一下|请说明|请问)", t):
        return False
    if any(k in t for k in ("需要学习", "检索增强", "适合做", "是什么框架")):
        return False
    if any(k in t for k in _FOLLOW_KEYS) and len(t) <= 24:
        return True
    if len(t) <= 12 and any(k in t for k in ("呢", "那", "这个", "那个", "还有")):
        return True
    return False


def _prev_substantive_user(messages: list[dict[str, str]] | None) -> str:
    if not messages:
        return ""
    users = [
        (m.get("content") or "").strip()
        for m in messages
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    if len(users) < 2:
        return ""
    prev = users[-2]
    # Previous turn should be a real question, not another deictic follow-up
    if is_followup_utterance(prev) and len(prev) <= 12:
        return ""
    return prev


def enrich_followup_query(
    user_text: str,
    messages: list[dict[str, str]] | None = None,
) -> str:
    """
    Rewrite short follow-ups into a self-contained retrieval query using slots.
    Example: slots(差旅报销) + 「那机票呢？」→「差旅报销 机票」
    """
    user = (user_text or "").strip()
    if not user:
        return ""

    slots = extract_slots(messages)
    if not is_followup_utterance(user):
        return user

    # Standalone policy question (no prior slot): do not strip down to a topic fragment
    if is_policy_question(user) and not slots.policy_name:
        return user

    # Already self-contained with policy name in the utterance
    if is_policy_question(user) and len(user) >= 6 and slots.policy_name and slots.policy_name in user:
        return user

    topic = _scan_topic(user) or slots.topic
    policy = slots.policy_name

    # Only invent a topic fragment when we already have a policy slot
    if not topic and policy:
        frag = user
        for k in ("那", "那么", "还有", "继续", "呢", "吗", "？", "?", "的", "展开"):
            frag = frag.replace(k, " ")
        frag = re.sub(r"\s+", " ", frag).strip()
        if 1 <= len(frag) <= 16:
            topic = frag

    parts: list[str] = []
    if policy:
        parts.append(policy)
        if topic and topic not in policy:
            parts.append(topic)

    # Non-policy multi-turn: anchor to previous substantive user question
    if not parts:
        prev_user = _prev_substantive_user(messages)
        if prev_user:
            return f"{prev_user} {user}".strip()
        return user

    enriched = " ".join(parts)
    if user not in enriched and len(user) <= 16:
        for token in ("上限", "标准", "怎么", "如何", "多少", "哪些", "超标", "超标准"):
            if token in user and token not in enriched:
                enriched = f"{enriched} {token}"
    return enriched.strip()
