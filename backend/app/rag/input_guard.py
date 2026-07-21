"""
T7-6: 用户输入注入检测 — 规则匹配，零延迟，不依赖 LLM。

防护分层：
  L1: 输入检测（正则匹配注入模式 → 拒绝请求）
  L2: System prompt 护栏（反注入条款）
  L3: 输出过滤（Mock 模式下制度数字检查，已有 forbid_phrases）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# 注入模式（按危险程度排序）
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # 角色/指令劫持（中文）
    (
        "角色劫持",
        r"(?:忽略|无视|忘记|覆盖|清除|删除|跳过|别管)\s*(?:之前|上面|所有|一切|上述|以下)\s*(?:的?\s*)?(?:指令|规则|约束|限制|提示|prompt|要求|设定|指示)",
    ),
    (
        "开发者模式",
        r"(?:开发者|开发人员|管理员|admin|developer|root)\s*(?:模式|权限|后门|控制台)",
    ),
    (
        "系统重定义",
        r"(?:你现在是|你从现在开始是|你假装|你扮演|你作为|你的新角色是)\s*(?:一[个位名]|新的)",
    ),
    (
        "越狱",
        r"(?:DAN|jailbreak|越狱|sandbox|沙盒)\s*(?:模式|指令|prompt)?",
    ),
    (
        "输出约束绕过",
        r"(?:不要|禁止|别|不可以|不准)\s*(?:说|提|提及|告诉|用)\s*(?:你|自己)\s*(?:是|为)\s*(?:AI|助手|机器人|模型|程序)",
    ),
    (
        "输出格式重写",
        r"(?:用|以)\s*(?:json|xml|markdown|raw|原文)\s*(?:格式|模式|输出)",
    ),
    # 隐私获取
    (
        "隐私获取",
        r"(?:说出|告诉我|列出|泄露|导出|打印|显示)\s*(?:所有|全部|每个)\s*(?:员工|用户|人)\s*(?:的)?\s*(?:工资|薪资|密码|密钥|key|secret|token|身份证)",
    ),
    # 制度绕过
    (
        "制度绕过",
        r"(?:以\s*(?:内|外|开发|测试)\s*(?:部|模式)?\s*(?:视角|身份|名义|环境))",
    ),
    (
        "脱离约束",
        r"(?:脱离制度约束|不受\s*(?:制度|规则|条款)\s*(?:约束|限制)|无论制度什么)",
    ),
    # 英文注入
    (
        "EN injection",
        r"(?i)(?:ignore\s*(?:all|previous|above|the)\s*instructions?|disregard\s*(?:all|prior)\s*(?:rules?|constraints?|instructions?)|forget\s*(?:everything|all)\s*(?:you|we|i)\s*(?:said|discussed|told|were))",
    ),
    (
        "EN override",
        r"(?i)(?:you\s*(?:are|must|should|will)\s*(?:now\s*)?(?:act\s*(?:as|like)|pretend\s*(?:to\s*be|you\s*are)|be\s*(?:a\s*)?))",
    ),
    (
        "EN role",
        r"(?i)(?:from\s*now\s*on|starting\s*now|new\s*instructions?|new\s*prompt)",
    ),
]


@dataclass
class GuardResult:
    safe: bool = True
    reason: str = ""
    matched_category: str = ""
    blocked_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe": self.safe,
            "reason": self.reason,
            "matched_category": self.matched_category,
        }


def check_user_input(text: str) -> GuardResult:
    """检测用户输入是否包含 prompt injection 指令。

    Args:
        text: 用户原始输入文本

    Returns:
        GuardResult: safe=True 表示通过，safe=False 表示拦截
    """
    if not text or not text.strip():
        return GuardResult(safe=True)

    text_stripped = text.strip()

    for category, pattern in _INJECTION_PATTERNS:
        match = re.search(pattern, text_stripped)
        if match:
            start = max(0, match.start() - 8)
            end = min(len(text_stripped), match.end() + 8)
            snippet = text_stripped[start:end]
            return GuardResult(
                safe=False,
                reason=f"检测到潜在注入指令（{category}）",
                matched_category=category,
                blocked_snippet=snippet,
            )

    return GuardResult(safe=True)
