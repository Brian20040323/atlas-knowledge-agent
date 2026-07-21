"""Lightweight query rewrite for policy / KB retrieval (T4).

依据：规范文档 04 §2.1 — 检索不准时做同义扩展，用评测证明。
"""

from __future__ import annotations

import re

from app.rag.policy_intent import is_policy_question


def rewrite_search_query(query: str) -> str:
    """Return a retrieval-oriented rewrite; identity if no rule applies."""
    q = (query or "").strip()
    if not q:
        return q

    out = q

    # --- HR / 招聘口语同义（OpenClaw 审查：员工制度·薪资覆盖弱）---
    if "工资" in out and "薪资" not in out:
        out = out.replace("工资", "薪资", 1)
    if "社招" in out and "社会招聘" not in out:
        out = out.replace("社招", "社会招聘", 1)
    if "校招" in out and "校园招聘" not in out:
        out = out.replace("校招", "校园招聘", 1)
    if "员工手册" in out and "员工制度" not in out:
        out = out.replace("员工手册", "员工制度", 1)

    # --- Colloquial synonyms (before policy gate; expand real-user phrasing) ---
    if "房费" in out:
        out = out.replace("房费", "住宿费", 1)
    if "住宾馆" in out or "住酒店" in out:
        out = out.replace("住宾馆", "住宿费", 1).replace("住酒店", "住宿费", 1)
    elif any(k in out for k in ("宾馆", "酒店")) and any(
        k in out for k in ("报", "额度", "上限", "标准", "差旅", "出差", "一晚", "限额")
    ):
        out = out.replace("宾馆", "住宿费", 1).replace("酒店", "住宿费", 1)
    if "住宿标准" in out:
        out = out.replace("住宿标准", "住宿费上限", 1)
    if "出差" in out:
        out = out.replace("出差", "差旅", 1)
    if "差旅政策" in out:
        out = out.replace("差旅政策", "差旅报销制度", 1)
    if "飞机票" in out:
        out = out.replace("飞机票", "机票", 1)
    elif "坐飞机" in out:
        out = out.replace("坐飞机", "机票", 1)
    elif "飞机" in out and any(k in out for k in ("报", "舱", "票", "差旅")):
        out = out.replace("飞机", "机票", 1)

    # Cabin class → anchor flight + economy rule in seed
    if any(k in out for k in ("头等舱", "商务舱")) and "机票" not in out:
        out = f"差旅报销 机票 经济舱 {out}"

    # Attachments / materials without explicit 差旅
    if any(k in out for k in ("行程单", "审批单", "单据", "材料")) and "差旅" not in out:
        if any(k in out for k in ("交", "带", "要", "哪些", "什么", "附件", "报销")):
            out = f"差旅报销 附件 {out}"
    elif ("行程单" in out or "审批单" in out) and "差旅" not in out:
        out = f"差旅报销 附件 {out}"

    if "单据" in out:
        out = out.replace("单据", "附件", 1)

    # 「超过500」「超了500」→ 住宿超标准
    if re.search(r"超过?\s*500|超了\s*500", out) and "差旅" not in out:
        out = f"差旅报销 住宿费 超标准 {out}"

    # Expense lodging / materials cues (may lack explicit「制度」关键词)
    if re.search(r"住宿(上限|费)?", out) and "差旅" not in out:
        out = f"差旅报销 {out}"
    if "报销" in out and any(
        k in out for k in ("材料", "附件", "交什么", "要交", "哪些票", "发票", "要不要")
    ) and "差旅" not in out:
        out = out.replace("报销", "差旅报销", 1)

    # Scope questions about who can claim
    if any(k in out for k in ("临时工", "外包", "正式员工以外", "非正式")):
        if "差旅" not in out and "报销" in out:
            out = f"差旅报销 {out}"
        if "正式员工" not in out or "以外" in out:
            out = f"差旅报销 正式员工 {out}" if "差旅报销" not in out else f"{out} 正式员工"
        elif "差旅" in out and "差旅报销" not in out:
            out = out.replace("差旅", "差旅报销", 1)

    if not is_policy_question(out) and "差旅报销" not in out:
        return q

    if "机票" in out and "差旅报销" not in out:
        if "差旅机票" in out:
            out = out.replace("差旅机票", "差旅报销 机票", 1)
        else:
            out = out.replace("机票", "差旅报销 机票", 1)

    if "住宿" in out and "住宿费" not in out:
        if "差旅" not in out:
            out = out.replace("住宿", "差旅 住宿费", 1)
        else:
            out = out.replace("住宿", "住宿费", 1)

    if "发票" in out and "差旅" in out and "差旅报销" not in out:
        out = out.replace("差旅", "差旅报销", 1)

    # 「境内」适用范围口语
    if "境内" in out and "差旅" in out and "差旅报销" not in out:
        out = out.replace("差旅", "差旅报销", 1)

    if "报销上限" in out and "差旅" not in out:
        out = out.replace("报销上限", "差旅报销 上限", 1)
    elif re.search(r"(?<!差旅)报销标准", out) and "差旅" not in out:
        out = re.sub(r"报销标准", "差旅报销 标准", out, count=1)

    # 「差旅费用怎么报」类口语 → 锚定制度标题词
    if re.search(r"差旅(费用)?", out) and any(
        k in out for k in ("怎么报", "如何报", "报销规定", "费用报销", "额度", "有没有", "交什么", "材料")
    ):
        if "差旅报销" not in out:
            out = out.replace("差旅", "差旅报销", 1)

    # 已含差旅+住宿费但仍缺「报销」标题词时补全
    if "差旅" in out and "住宿费" in out and "差旅报销" not in out:
        out = out.replace("差旅", "差旅报销", 1)

    # 差旅+附件/材料
    if "差旅" in out and any(k in out for k in ("材料", "附件", "单据")) and "差旅报销" not in out:
        out = out.replace("差旅", "差旅报销", 1)

    out = re.sub(r"\s+", " ", out).strip()

    # --- T7-8: 制度推理辅助扩展（上位概念，扩大命中窗口）---
    _POLICY_PRINCIPLE_MAP: dict[str, str] = {
        # 住宿类
        "民宿": "住宿 住宿类型",
        "青旅": "住宿 住宿类型",
        "公寓": "住宿 住宿类型 住宿费",
        "长住": "住宿 长期住宿",
        "长租": "住宿 长期住宿",
        # 交通类（制度外）
        "打车": "交通 出行 市内交通",
        "地铁": "交通 出行 市内交通",
        "公交": "交通 出行 市内交通",
        "租车": "交通 出行",
        "高铁": "交通 交通费 差旅",
        # 人员类
        "实习生": "适用 适用范围 人员 正式员工",
        "外包": "适用 适用范围 人员 正式员工",
        "兼职": "适用 适用范围 人员 正式员工",
        "临时工": "适用 适用范围 人员 正式员工",
        # 流程类
        "超预算": "超标 审批 超标准",
        "紧急": "特批 加急 审批 例外",
        "补报": "补交 补办 补充 报销",
        "忘交": "补交 补办 补充 逾期",
        # 餐饮
        "餐费": "餐饮 差旅 补贴 报销",
        "餐补": "餐饮 补贴 差旅",
        # 住宿类型
        "协议酒店": "住宿 住宿费 住宿标准",
        "协议价": "住宿 住宿费 价格 标准",
    }
    for keyword, expansion in _POLICY_PRINCIPLE_MAP.items():
        if keyword in out:
            out = f"{out} {expansion}"
            break  # 只应用第一个匹配的扩展，避免过度膨胀
    # --- end T7-8 ---

    return out or q
