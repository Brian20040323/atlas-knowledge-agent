"""
T7-2: 复合问题分解 — 规则化拆句子为独立子查询。

面试追问 Q6：「薪资和员工制度如何，社招和校招有什么区别」
→ ["员工制度", "薪资制度", "社招和校招区别"]
"""

from __future__ import annotations

import re


# 常见连接词模式
_COMPOSITE_SEPARATORS = [
    "和", "与", "以及", "还有", "另外", "同时",
    "以及同时", "与此同时",
]

# 对比类后缀提示词
_CONTRAST_KEYWORDS = ["区别", "不同", "差异", "对比", "比较", "异同", "好坏", "优劣"]


def decompose_composite_query(text: str) -> list[str]:
    """
    将复合查询拆分为独立子查询列表。

    拆解策略（纯规则，无 LLM 依赖）：
    1. 按问号(?)分句
    2. 在连接词处切分
    3. 识别对比后缀（如「有什么区别」）→ 提取主题对
    4. 去重、去空、返回
    """
    text = (text or "").strip()
    if not text:
        return [text]

    # 步骤 1: 按问号分句
    raw_parts = [p.strip() for p in re.split(r"[？?。！!，,；;]", text) if p.strip()]

    sub_queries: list[str] = []

    for part in raw_parts:
        # 步骤 2: 在连接词处切分
        pieces = _split_on_separators(part)

        # 步骤 3: 识别对比短语，提取主题对
        for piece in pieces:
            result = _extract_contrast_topics(piece)
            if result:
                sub_queries.extend(result)
            else:
                # 清理问句标记
                cleaned = _clean_query(piece)
                if cleaned and len(cleaned) >= 2:
                    sub_queries.append(cleaned)

    # 去重（保留顺序）
    seen: set[str] = set()
    unique: list[str] = []
    for sq in sub_queries:
        if sq not in seen:
            seen.add(sq)
            unique.append(sq)

    # 至少保留原查询
    if not unique:
        unique.append(_clean_query(text))

    return unique


def _split_on_separators(text: str) -> list[str]:
    """在连接词处切分，返回多段。"""
    text = text.strip()
    for sep in _COMPOSITE_SEPARATORS:
        idx = text.find(sep)
        if idx >= 2:  # 连接词前面至少有 2 个字符
            left = text[:idx].strip()
            right = text[idx + len(sep):].strip()
            if len(left) >= 2 and len(right) >= 2:
                # 递归处理右侧（可能还有更多连接词）
                right_pieces = _split_on_separators(right)
                return [left] + right_pieces
    return [text]


def _extract_contrast_topics(text: str) -> list[str] | None:
    """识别「社招和校招有什么区别」→ ['社招', '校招', '社招和校招区别']"""
    for kw in _CONTRAST_KEYWORDS:
        if kw in text:
            # 找到对比关键词之前的部分
            prefix = text[:text.index(kw)].strip()
            # 在 prefix 中找对比对象
            for sep in _COMPOSITE_SEPARATORS:
                if sep in prefix:
                    parts = prefix.split(sep, 1)
                    a = _clean_query(parts[0])
                    b = _clean_query(parts[1])
                    if a and b and len(a) >= 1 and len(b) >= 1:
                        return [a, b, f"{a}和{b}{kw}"]
            # 如果只有一个主题，返回原句
            return None
    return None


def _clean_query(text: str) -> str:
    """去掉问号、如何、怎么 等问句前缀/后缀，保留核心主题词。"""
    text = text.strip()
    # 去尾部问号
    text = re.sub(r"[？?。！!]+$", "", text).strip()
    # 去常见前缀
    text = re.sub(r"^(请问|我想问|问一下|我想知道|告诉我|帮我查|查一下)\s*", "", text)
    # 去常见后缀问法
    text = re.sub(r"(如何|怎么|怎么样|是什么|有哪些|有什么区别|的区别|的区别是什么|的差异)$", "", text)
    text = text.strip()
    return text
