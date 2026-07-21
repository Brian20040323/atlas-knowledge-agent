"""T8-1: 闲聊 / 寒暄分流 — 不进检索与 research。

OpenClaw 审查 P0：问候走 RAG 延迟高、回复生硬。
"""

from __future__ import annotations

import re

# Exact or near-exact greetings / politeness (after strip)
_EXACT = {
    "你好",
    "您好",
    "哈喽",
    "hello",
    "hi",
    "hey",
    "在吗",
    "在不在",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "早",
    "晚安",
    "谢谢",
    "多谢",
    "感谢",
    "谢谢你",
    "谢谢您",
    "辛苦了",
    "拜拜",
    "再见",
    "bye",
    "ok",
    "好的",
    "收到",
    "嗯嗯",
    "哈哈",
    "嘿嘿",
}

_REPEAT_GREET = re.compile(r"^(你好)+$|^(您好)+$|^(哈喽)+$", re.I)
_POLITE = re.compile(
    r"^(谢谢|多谢|感谢|辛苦)(你|您|啦|了|哈)?[!！.。~～]*$",
)


def is_chitchat(text: str) -> bool:
    """True if message is pure social/greeting and should skip RAG."""
    t = (text or "").strip()
    if not t:
        return False
    # Strip common punctuation / emoji noise
    compact = re.sub(r"[\s!！?？.。,~～、]+", "", t)
    if not compact:
        return False
    low = compact.lower()
    if low in _EXACT or compact in _EXACT:
        return True
    if _REPEAT_GREET.match(compact):
        return True
    if _POLITE.match(compact):
        return True
    # Very short non-policy filler
    if len(compact) <= 2 and compact in {"嗯", "哦", "额", "啊", "呢"}:
        return True
    return False


def chitchat_reply(text: str) -> str:
    """Template reply — no LLM, no retrieval."""
    t = (text or "").strip()
    compact = re.sub(r"[\s!！?？.。,~～、]+", "", t)
    low = compact.lower()

    if any(k in compact for k in ("谢谢", "多谢", "感谢", "辛苦")):
        return "不客气。制度、知识或一般问题都可以继续问。"

    if any(k in compact for k in ("拜拜", "再见")) or low in {"bye"}:
        return "再见。需要查制度或问其它问题时随时找我。"

    if compact in {"好的", "收到", "ok", "嗯嗯"} or low == "ok":
        return "好的。直接发问题即可——制度优先，一般问题也能答。"

    # Default greeting
    return (
        "你好，我是 Atlas：优先帮你查企业内部制度与知识库，"
        "也可以回答数学、编程、时事等一般问题。\n\n"
        "试试例如：\n"
        "- 差旅住宿费上限是多少？\n"
        "- 报销要哪些附件？\n"
        "- 求函数 f(x)=x² 的导数\n\n"
        "短问也可以，不清楚时我会先确认你的意图。"
    )
