# -*- coding: utf-8 -*-
from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt, Cm
import subprocess
import shutil

DOCX = Path(r"c:\Users\czy2004\Desktop\OpenClaw协作_遗漏审查与落地.md")
# Actually write markdown + pdf via simple docx
OUT_DOCX = Path(r"c:\Users\czy2004\Desktop\OpenClaw协作_遗漏与优化落地.docx")
OUT_PDF = Path(r"c:\Users\czy2004\Desktop\OpenClaw协作_遗漏与优化落地.pdf")
EN_DOCX = Path(r"c:\Users\czy2004\Desktop\openclaw_collab_gaps.docx")
EN_PDF = Path(r"c:\Users\czy2004\Desktop\openclaw_collab_gaps.pdf")
PS1 = Path(r"c:\Users\czy2004\Desktop\AI 全栈开发\_export_collab_pdf.ps1")


def font(run, name="宋体", size=11, bold=False):
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), "Times New Roman")
    rFonts.set(qn("w:hAnsi"), "Times New Roman")
    rFonts.set(qn("w:eastAsia"), name)


def p(doc, text, *, size=11, bold=False, name="宋体", align=None, after=6, first=False):
    para = doc.add_paragraph()
    if align is not None:
        para.alignment = align
    pf = para.paragraph_format
    pf.space_after = Pt(after)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if first:
        pf.first_line_indent = Pt(22)
    run = para.add_run(text)
    font(run, name=name, size=size, bold=bold)


def h(doc, text, level=1):
    p(doc, text, size={1: 16, 2: 13}.get(level, 11), bold=True, name="黑体", after=8)


def bullets(doc, items):
    for t in items:
        para = doc.add_paragraph(style="List Bullet")
        para.clear()
        para.paragraph_format.space_after = Pt(3)
        run = para.add_run(t)
        font(run, size=11)


doc = Document()
for s in doc.sections:
    s.top_margin = Cm(2)
    s.bottom_margin = Cm(2)
    s.left_margin = Cm(2.2)
    s.right_margin = Cm(2.2)

p(doc, "Atlas × OpenClaw 协作审查", size=12, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
p(doc, "遗漏问题对照与本轮落地", size=18, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
p(doc, "审查视角：OpenClaw（小龙虾）工程审查 · DeepSeek V4 Pro · 对照 Atlas 现码", size=10, align=WD_ALIGN_PARAGRAPH.CENTER, after=14)

h(doc, "1. 协作结论摘要", 1)
p(
    doc,
    "OpenClaw 审查认为：方案文档里的 P1–P8 覆盖了面试 Q1–Q9 主线，但相对生产 RAG 仍缺闲聊分流、安全护栏、精排、DST、反馈闭环等。"
    "对照 Atlas 现码后发现：短问澄清、复合拆问、注入防护其实已有（T7）；真正缺口是闲聊分流与员工制度/薪资同义覆盖。本轮已优先落地闲聊分流。",
    first=True,
)

h(doc, "2. OpenClaw 指出的遗漏 vs Atlas 现状", 1)
table = doc.add_table(rows=1, cols=4)
table.style = "Table Grid"
for i, t in enumerate(["优先级", "OpenClaw 遗漏点", "Atlas 对照", "本轮动作"]):
    cell = table.rows[0].cells[i]
    cell.text = ""
    run = cell.paragraphs[0].add_run(t)
    font(run, name="黑体", size=9, bold=True)

rows = [
    ("P0", "闲聊仍走检索/research", "此前确实缺失", "已落地 T8-1 CHITCHAT"),
    ("P0", "安全/注入防护缺失", "已有 T7-6 input_guard", "保持，不重复造轮子"),
    ("P0", "缺少精排 Rerank", "混合分+过滤，无 Cross-Encoder", "列入下一轮"),
    ("P1", "槽位无 LLM DST", "规则槽位已有，够差旅场景", "本轮扩展员工制度/薪资别名"),
    ("P1", "复合问合并冲突消解", "已有 COMPOSITE 并行+合并", "后续加强 merge Prompt"),
    ("P1", "短问澄清未落地", "已有 T7-1 CLARIFY", "补评测用例"),
    ("P2", "同义覆盖弱", "偏差旅", "补社招/校招/工资等同义"),
    ("P2", "无用户反馈闭环", "确无", "暂缓（避免范围膨胀）"),
]
for r in rows:
    cells = table.add_row().cells
    for i, v in enumerate(r):
        cells[i].text = ""
        run = cells[i].paragraphs[0].add_run(v)
        font(run, size=9)
doc.add_paragraph()

h(doc, "3. 本轮已落地（开始做）", 1)
bullets(
    doc,
    [
        "新增 backend/app/rag/chitchat.py：识别你好/谢谢等，模板回复，跳过 RAG。",
        "planner 增加 Intent.CHITCHAT；须在 CLARIFY 之前，避免「你好」被当成短问澄清。",
        "stream_chat：闲聊跳过 prelim 检索；done.mode=chitchat。",
        "dialogue_slots / query_rewrite：补员工制度、薪资、社招、校招等同义与槽位。",
        "评测新增 4 例；run_eval 对齐 chitchat/clarify 短路径。",
        "评测结果：130/130 passed。",
    ],
)

h(doc, "4. 建议下一轮顺序（与 OpenClaw 一致，略校正）", 1)
bullets(
    doc,
    [
        "下一件：轻量 LLM rerank（Top20→TopK）或继续强化规则过滤证据。",
        "再下一件：COMPOSITE 汇总用 merge_answers Prompt（冲突消解）。",
        "再下一件：可选开启向量 + 同义词挖掘（员工制度域）。",
        "明确不做：自研向量库选型竞赛；先把链路跑稳。",
    ],
)

h(doc, "5. 验收话术（演示）", 1)
bullets(
    doc,
    [
        "输入「你好你好」→ 寒暄引导，不再出现「材料不足以回答你好」。",
        "输入「薪资」→ 澄清选项，不编数字。",
        "输入「差旅住宿费上限」→ 仍有据答 500 + 参考。",
    ],
)

p(doc, "— Atlas × OpenClaw 协作记录 —", size=9, align=WD_ALIGN_PARAGRAPH.CENTER, after=0)

doc.save(str(OUT_DOCX))
shutil.copy2(OUT_DOCX, EN_DOCX)
PS1.write_text(
    f"""$docx='{EN_DOCX}'
$pdf='{EN_PDF}'
$w=New-Object -ComObject Word.Application
$w.Visible=$false
$w.DisplayAlerts=0
$d=$w.Documents.Open($docx,$false,$true)
$d.ExportAsFixedFormat($pdf,17)
$d.Close($false)
$w.Quit()
""",
    encoding="utf-8",
)
subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1)], check=True)
shutil.copy2(EN_PDF, OUT_PDF)
print("wrote", OUT_DOCX, OUT_PDF)
