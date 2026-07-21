"""Policy / internal-rules question detection (shared by planner + rewrite)."""

from __future__ import annotations

import re

POLICY_KEYWORDS: tuple[str, ...] = (
    "报销",
    "差旅",
    "考勤",
    "请假",
    "年假",
    "调休",
    "加班",
    "制度",
    "规章",
    "内规",
    "额度",
    "发票",
    "审批",
    "附件",
    "出差",
    "住宿费",
    "房费",
    "行程单",
    "审批单",
    "经济舱",
    "商务舱",
    "机票",
    "入职",
    "离职",
    "社保",
    "公积金",
    "劳动合同",
    "公司规定",
    "本公司规定",
    "福利条款",
    "行权",
    "股权激励",
    "补贴",
    "住房补贴",
    "加班费",
    "补助",
    "年终奖",
)


def is_policy_question(text: str) -> bool:
    """True when the user is asking about internal policy / HR rules."""
    t = (text or "").strip()
    if not t:
        return False
    if any(k in t for k in POLICY_KEYWORDS):
        return True
    # Colloquial reimbursement phrasing without formal keywords
    if any(k in t for k in ("酒店", "宾馆", "房费", "一晚")) and any(
        k in t for k in ("报", "额度", "上限", "标准", "限额")
    ):
        return True
    if any(k in t for k in ("飞机", "机票", "头等舱", "商务舱", "经济舱")) and any(
        k in t for k in ("报", "舱", "报销")
    ):
        return True
    # Transport / meal expense asks — keep local (refuse if no seed), never auto-research
    if any(k in t for k in ("打车", "出租车", "高铁", "火车", "餐费", "餐补")) and any(
        k in t for k in ("报", "标准", "多少", "能", "可以")
    ):
        return True
    if re.search(r"超过?\s*\d+|超了\s*\d+", t) and any(k in t for k in ("怎么办", "如何", "怎样")):
        return True
    if any(k in t for k in ("临时工", "外包", "正式员工以外")) and any(k in t for k in ("报", "差旅", "报销")):
        return True
    return False
