# -*- coding: utf-8 -*-
"""Export 数据分析样本 → PDF with charts on Desktop."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import openpyxl
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt

XLSX = Path(
    r"c:\Users\czy2004\Documents\xwechat_files\wxid_mk5i6rp0lkj412_9245\msg\file\2026-07"
    r"\开题报告_数据分析样本(1).xlsx"
)
DOCX = Path(r"c:\Users\czy2004\Desktop\开题报告_数据分析样本.docx")
PDF = Path(r"c:\Users\czy2004\Desktop\开题报告_数据分析样本.pdf")
CHART_DIR = Path(r"c:\Users\czy2004\Desktop\AI 全栈开发\_data_sample_charts")

# Visual style — clear, not purple-AI default
COLORS = {
    "primary": "#1F4E79",
    "accent": "#2E7D4F",
    "warm": "#C45C26",
    "muted": "#6B7280",
    "light": "#E8EEF4",
    "bars": ["#1F4E79", "#2E7D4F", "#C45C26", "#4A6FA5", "#5B8C5A", "#8B6914"],
}


def setup_matplotlib_font():
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.dpi"] = 140
    plt.rcParams["savefig.dpi"] = 160
    plt.rcParams["axes.edgecolor"] = "#CBD5E1"
    plt.rcParams["axes.labelcolor"] = "#1F2937"
    plt.rcParams["xtick.color"] = "#374151"
    plt.rcParams["ytick.color"] = "#374151"


def set_run_font(run, name="宋体", size=10.5, bold=False):
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), name)


def add_para(doc, text, *, size=10.5, bold=False, name="宋体", align=None, space_after=6, first_line=False):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if first_line:
        pf.first_line_indent = Pt(21)
    run = p.add_run(text)
    set_run_font(run, name=name, size=size, bold=bold)
    return p


def add_h(doc, text, level=1):
    if level == 1:
        return add_para(doc, text, size=16, bold=True, name="黑体", space_after=10)
    if level == 2:
        return add_para(doc, text, size=13, bold=True, name="黑体", space_after=8)
    return add_para(doc, text, size=11, bold=True, name="黑体", space_after=6)


def fmt_val(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-9:
            return f"{int(round(v)):,}"
        return f"{v:g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v).strip()


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(h))
        set_run_font(run, name="黑体", size=9, bold=True)
    for r_i, row in enumerate(rows):
        for c_i, val in enumerate(row):
            cell = table.rows[r_i + 1].cells[c_i]
            cell.text = ""
            s = val if isinstance(val, str) else fmt_val(val)
            run = cell.paragraphs[0].add_run(s if s is not None else "—")
            set_run_font(run, size=9)
    doc.add_paragraph()


def add_image(doc, path: Path, width_inches=5.8, caption: str = ""):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run()
    run.add_picture(str(path), width=Inches(width_inches))
    if caption:
        add_para(doc, caption, size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)


def sheet_rows(ws, start_row=3):
    headers = [c.value for c in ws[start_row]]
    while headers and headers[-1] is None:
        headers.pop()
    n = len(headers)
    rows = []
    for r in range(start_row + 1, (ws.max_row or start_row) + 1):
        vals = [ws.cell(r, c).value for c in range(1, n + 1)]
        if all(v is None or str(v).strip() == "" for v in vals):
            continue
        vals = [("—" if v is None else v) for v in vals]
        rows.append(vals)
    return [str(h) if h is not None else "" for h in headers], rows


def make_charts(wb) -> dict[str, Path]:
    setup_matplotlib_font()
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # --- Chart 1: 候选城市增长倍数 ---
    ws = wb["候选城市"]
    _, rows = sheet_rows(ws, 3)
    cities, growth = [], []
    for row in rows:
        name = str(row[0])
        g = row[2]
        if isinstance(g, (int, float)):
            cities.append(name)
            # 义乌 0.62 → 显示为 0.62（增速），其余为倍数；统一用数值轴并标注
            growth.append(float(g))

    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    # split: 义乌 is rate, others are multipliers — plot multipliers for 潜力股, annotate 义乌 separately
    colors = []
    for c, g in zip(cities, growth):
        if c == "义乌":
            colors.append(COLORS["warm"])
        elif g >= 4:
            colors.append(COLORS["accent"])
        elif g >= 2:
            colors.append("#4A6FA5")
        else:
            colors.append(COLORS["primary"])
    bars = ax.barh(cities[::-1], growth[::-1], color=colors[::-1], height=0.65)
    ax.set_xlabel("增长下限 / 增速数值（义乌为同比增速，其余为增长倍数下限）")
    ax.set_title("候选城市增长对比（资料节选）", fontsize=13, fontweight="bold", color=COLORS["primary"], pad=10)
    ax.axvline(1.0, color=COLORS["muted"], linestyle="--", linewidth=0.9, alpha=0.7)
    for bar, val, city in zip(bars, growth[::-1], cities[::-1]):
        label = f"{val:.0%}" if city == "义乌" else (f"{val:g}×" if val >= 1 else f"{val:g}")
        ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2, label, va="center", fontsize=9)
    ax.set_xlim(0, max(growth) * 1.18)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p1 = CHART_DIR / "chart_cities.png"
    fig.savefig(p1, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths["cities"] = p1

    # --- Chart 2: 关键词排名集中度（3个月）---
    # from raw: 总词数 18928, 前10 3709, 前20 9249, 前30 12751
    total = 18928
    top10, top20, top30 = 3709, 9249, 12751
    segments = [
        ("前10名", top10),
        ("第11–20名", top20 - top10),
        ("第21–30名", top30 - top20),
        ("30名以外", total - top30),
    ]
    labels = [f"{n}\n{v:,}（{v/total:.1%}）" for n, v in segments]
    sizes = [v for _, v in segments]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    wedges, _ = ax.pie(
        sizes,
        labels=None,
        colors=["#1F4E79", "#4A6FA5", "#7BA3C9", "#D1D9E6"],
        startangle=90,
        wedgeprops=dict(width=0.55, edgecolor="white", linewidth=2),
    )
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=9)
    ax.set_title("去哪儿网 3 个月关键词分布（前30名集中度）", fontsize=13, fontweight="bold", color=COLORS["primary"], pad=12)
    # center text
    ax.text(0, 0, f"总词数\n{total:,}", ha="center", va="center", fontsize=11, fontweight="bold", color=COLORS["primary"])
    fig.tight_layout()
    p2 = CHART_DIR / "chart_keywords.png"
    fig.savefig(p2, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths["keywords"] = p2

    # --- Chart 3: 重点城市入境/机票信号 ---
    focus = [
        ("阿勒泰\n入境机票", 4.0, "倍"),
        ("黑河\n入境机票", 2.3, "倍"),
        ("义乌\n机票同比", 0.62, "增速"),
        ("重庆\n入境机票同比", 0.30, "增速"),
        ("入境航段\n2026-02", 0.32, "增速"),
        ("入境航段\n2026-03", 0.24, "增速"),
    ]
    # normalize to comparable display: show as percentage-equivalent for 增速, keep 倍 as *100 for visual? Better two groups.
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), gridspec_kw={"width_ratios": [1.1, 1]})

    ax = axes[0]
    names = ["阿勒泰", "黑河"]
    vals = [4.0, 2.3]
    ax.bar(names, vals, color=[COLORS["accent"], "#4A6FA5"], width=0.55)
    ax.set_ylabel("增长倍数")
    ax.set_title("入境机票增长倍数", fontsize=11, fontweight="bold", color=COLORS["primary"])
    for i, v in enumerate(vals):
        ax.text(i, v + 0.08, f"{v:g}×", ha="center", fontsize=10)
    ax.set_ylim(0, 5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax = axes[1]
    names2 = ["义乌机票", "重庆入境", "航段02月", "航段03月"]
    vals2 = [62, 30, 32, 24]  # percent
    ax.bar(names2, vals2, color=[COLORS["warm"], "#C47B4A", COLORS["primary"], "#4A6FA5"], width=0.6)
    ax.set_ylabel("同比增长（%）")
    ax.set_title("同比增速信号（%）", fontsize=11, fontweight="bold", color=COLORS["primary"])
    for i, v in enumerate(vals2):
        ax.text(i, v + 1.2, f"{v}%", ha="center", fontsize=9)
    ax.set_ylim(0, 75)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.suptitle("重点增长信号一览（原始提取节选）", fontsize=13, fontweight="bold", color=COLORS["primary"], y=1.02)
    fig.tight_layout()
    p3 = CHART_DIR / "chart_signals.png"
    fig.savefig(p3, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths["signals"] = p3

    # --- Chart 4: 资料缺口优先级 ---
    ws = wb["资料缺口"]
    _, gap_rows = sheet_rows(ws, 3)
    high = sum(1 for r in gap_rows if str(r[0]) == "高")
    mid = sum(1 for r in gap_rows if str(r[0]) == "中")
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    cats = ["高优先级", "中优先级"]
    counts = [high, mid]
    bars = ax.barh(cats[::-1], counts[::-1], color=[COLORS["warm"], COLORS["primary"]][::-1], height=0.45)
    ax.set_xlabel("缺口条目数")
    ax.set_title("资料缺口优先级分布", fontsize=13, fontweight="bold", color=COLORS["primary"], pad=10)
    for bar, v in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2, f"{v} 项", va="center", fontsize=11)
    ax.set_xlim(0, max(counts) + 1.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p4 = CHART_DIR / "chart_gaps.png"
    fig.savefig(p4, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths["gaps"] = p4

    # --- Chart 5: 搜狗前10/20/30 对比 ---
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    labels_sg = ["搜狗前10名", "搜狗前20名", "搜狗前30名"]
    vals_sg = [3954, 8777, 14915]
    ax.bar(labels_sg, vals_sg, color=["#1F4E79", "#4A6FA5", "#7BA3C9"], width=0.55)
    ax.set_ylabel("词数（个）")
    ax.set_title("搜狗关键词排名覆盖（2026-07-06）", fontsize=13, fontweight="bold", color=COLORS["primary"], pad=10)
    for i, v in enumerate(vals_sg):
        ax.text(i, v + 200, f"{v:,}", ha="center", fontsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    p5 = CHART_DIR / "chart_sogou.png"
    fig.savefig(p5, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths["sogou"] = p5

    return paths


def build_docx(charts: dict[str, Path]):
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = Cm(1.8)
        sec.bottom_margin = Cm(1.8)
        sec.left_margin = Cm(1.8)
        sec.right_margin = Cm(1.8)

    add_para(doc, "飞书AI先锋未来人才大赛 · 去哪网选题", size=11, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    add_para(doc, "开题报告 · 数据分析样本", size=18, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    add_para(
        doc,
        "主题：继淄博、天水、哈尔滨之后——如何用AI抢在热搜之前，预测下一座爆火的小城",
        size=10,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=14,
    )

    # 一
    ws = wb["说明"]
    add_h(doc, "一、样本说明", 1)
    add_para(
        doc,
        "本文件整理自开题阶段已核实的结构化数据，并配图表便于提交审阅。"
        "表格与图均来自同一批样本，潜力股城市不等于下一座必然爆火城市。",
        first_line=True,
    )
    meta_rows = []
    for r in range(3, 10):
        a, b = ws.cell(r, 1).value, ws.cell(r, 2).value
        if a:
            meta_rows.append([a, b or "—"])
    add_table(doc, ["项目", "说明"], meta_rows)
    add_para(doc, "表 1　样本元信息", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)

    # 二
    ws = wb["原始提取"]
    add_h(doc, "二、原始提取数据", 1)
    add_para(doc, str(ws["A1"].value or ""), first_line=True, space_after=8)
    headers, rows = sheet_rows(ws, 3)
    nice_rows = []
    for row in rows:
        row = list(row)
        while len(row) < len(headers):
            row.append("—")
        if len(row) >= 6 and isinstance(row[4], (int, float)):
            unit = str(row[5])
            val = row[4]
            if unit == "同比" and isinstance(val, float) and val <= 2:
                row[4] = f"{val:.0%}" if abs(val * 100 - round(val * 100)) < 1e-6 else f"{val:.1%}"
            elif unit == "倍":
                row[4] = f"{val:g}"
            elif isinstance(val, (int, float)) and abs(float(val) - round(float(val))) < 1e-9:
                row[4] = f"{int(round(val)):,}"
            else:
                row[4] = fmt_val(val)
        nice_rows.append([x if isinstance(x, str) else fmt_val(x) for x in row[: len(headers)]])
    add_table(doc, headers, nice_rows)
    add_para(doc, "表 2　截图/资料中可核实的结构化数据", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)

    add_h(doc, "2.1 关键词与搜索覆盖（图示）", 2)
    add_image(doc, charts["keywords"], 5.6, "图 1　去哪儿网 3 个月关键词分布（前30名集中度）")
    add_image(doc, charts["sogou"], 5.2, "图 2　搜狗关键词排名覆盖（2026-07-06）")
    add_image(doc, charts["signals"], 5.8, "图 3　重点增长信号一览（入境机票倍数 / 同比增速）")

    # 三
    ws = wb["候选城市"]
    add_h(doc, "三、候选城市池", 1)
    add_para(doc, str(ws["A1"].value or ""), first_line=True, space_after=6)
    add_para(
        doc,
        "说明：下表城市仅用于建立候选池；「可直接判定爆火」均为否。",
        size=10,
        first_line=True,
        space_after=8,
    )
    headers, rows = sheet_rows(ws, 3)
    nice_rows = []
    for row in rows:
        row = list(row)
        while len(row) < len(headers):
            row.append("—")
        if isinstance(row[2], (int, float)):
            if row[2] >= 2:
                row[2] = f"{row[2]:g}×"
            elif row[2] < 1:
                row[2] = f"{row[2]:.0%}"
            else:
                row[2] = f">{row[2]:g}"
        nice_rows.append([x if isinstance(x, str) else fmt_val(x) for x in row[: len(headers)]])
    add_table(doc, headers, nice_rows)
    add_para(doc, "表 3　资料中出现的候选城市", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    add_image(doc, charts["cities"], 5.8, "图 4　候选城市增长对比（义乌为同比增速，其余为增长倍数下限）")

    # 四
    ws = wb["资料缺口"]
    add_h(doc, "四、资料缺口与补数建议", 1)
    add_para(doc, str(ws["A1"].value or ""), first_line=True, space_after=8)
    headers, rows = sheet_rows(ws, 3)
    nice_rows = [[x if isinstance(x, str) else fmt_val(x) for x in row] for row in rows]
    add_table(doc, headers, nice_rows)
    add_para(doc, "表 4　无法确认与需要补充的信息", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    add_image(doc, charts["gaps"], 4.8, "图 5　资料缺口优先级分布")

    # 五
    add_h(doc, "五、使用与引用注意", 1)
    for b in [
        "模型字段与评分框架属于待验证研究设计，本样本不构成最终预测结论。",
        "图表仅为样本可视化，不等同于模型输出或爆火判定。",
        "现有城市数据主要来自去哪儿平台入境游相关报道，缺少城市级日度多源数据与爆火标签。",
        "潜力股城市 ≠ 下一座必然爆火的城市；引用时请同时标注资料编号与质量等级。",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        p.clear()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        run = p.add_run(b)
        set_run_font(run, size=10.5)

    add_para(
        doc,
        "飞书AI先锋未来人才大赛 · 开题报告数据分析样本（含图表整理版）",
        size=9,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=0,
    )
    doc.save(str(DOCX))


def export_pdf():
    import subprocess

    ps = f"""
$docx = '{DOCX}'
$pdf = '{PDF}'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$doc = $app.Documents.Open($docx)
$doc.SaveAs([ref]$pdf, [ref]17)
$doc.Close()
$app.Quit()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    charts = make_charts(wb)
    build_docx(charts)
    export_pdf()
    print("charts", list(charts))
    print("PDF", PDF, PDF.stat().st_size if PDF.exists() else 0)


if __name__ == "__main__":
    main()
