# -*- coding: utf-8 -*-
"""Build Q-Trend 开题报告（去掉版本对照，重排小标题）."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


OUT_DIR = Path(r"c:\Users\czy2004\Documents\xwechat_files\wxid_mk5i6rp0lkj412_9245\msg\file\2026-07")
OUT_NAME = "Q-Trend_开题报告.docx"
ALT_DIR = Path(r"c:\Users\czy2004\Desktop\AI 全栈开发")


def set_run_font(run, name="宋体", size=12, bold=False, color=None):
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = name
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), "Times New Roman" if name != "黑体" else name)
    rFonts.set(qn("w:hAnsi"), "Times New Roman" if name != "黑体" else name)
    rFonts.set(qn("w:eastAsia"), name)
    if color is not None:
        run.font.color.rgb = color


def add_para(doc, text, *, size=12, bold=False, name="宋体", align=None, space_after=6, first_line=False):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    if first_line:
        pf.first_line_indent = Pt(24)
    run = p.add_run(text)
    set_run_font(run, name=name, size=size, bold=bold)
    return p


def add_heading_cn(doc, text, level=1):
    """Custom headings without Word Heading styles (more controllable)."""
    if level == 1:
        return add_para(doc, text, size=16, bold=True, name="黑体", space_after=10)
    if level == 2:
        return add_para(doc, text, size=14, bold=True, name="黑体", space_after=8)
    return add_para(doc, text, size=12, bold=True, name="黑体", space_after=6)


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.clear()
        pf = p.paragraph_format
        pf.space_after = Pt(4)
        pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        run = p.add_run(item)
        set_run_font(run, size=12)


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        set_run_font(run, name="黑体", size=10, bold=True)
    for r_i, row in enumerate(rows):
        for c_i, val in enumerate(row):
            cell = table.rows[r_i + 1].cells[c_i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(val))
            set_run_font(run, size=10)
    doc.add_paragraph()


def build():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Pt(72)
    section.bottom_margin = Pt(72)
    section.left_margin = Pt(72)
    section.right_margin = Pt(72)

    # ---- 封面信息 ----
    add_para(doc, "飞书AI先锋未来人才大赛", size=14, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
    add_para(doc, "去哪网选题 · 开题报告", size=14, bold=True, name="黑体", align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)
    add_para(
        doc,
        "命题：继淄博、天水、哈尔滨之后——如何用AI抢在热搜之前，预测出下一座爆火的小城？",
        size=11,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=8,
    )
    add_para(
        doc,
        "方案名称：Q-Trend — 去哪网旅游趋势智能预测引擎",
        size=12,
        bold=True,
        name="黑体",
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=16,
    )

    # ==================== 一 ====================
    add_heading_cn(doc, "一、命题前置分析与洞察", level=1)

    add_heading_cn(doc, "1.1 短视频如何重构旅游目的地的「被发现」路径", level=2)
    add_para(
        doc,
        "2023 年淄博烧烤、2024 年天水麻辣烫和哈尔滨冰雪季、2025 年泉州簪花和阿勒泰影视取景地——"
        "每一个季度，几乎都有一个「查无此人」的小城突然占据全网注意力。表层看是随机事件，底层却是一个被多数从业者忽略的结构性变化："
        "短视频平台的推荐算法彻底改变了旅游目的地的被发现机制。过去一个城市要火，需要旅行社铺渠道、旅游局砸广告、OTA 给流量位，周期以年计。"
        "现在，一条 15 秒的素人视频被算法选中，48 小时内就能让上千万人建立起对一个陌生城市的认知。"
        "用户的决策起点从「我想去三亚，哪家便宜」变成了「我刚刷到一个没听说过的城市好有意思，这地方在哪、能订吗」。",
        first_line=True,
    )
    add_para(
        doc,
        "这一变化对 OTA 行业的竞争规则产生了根本性影响：谁先在用户「第一次听说」的瞬间出现并提供预订路径，谁就抢到了整个转化链条的头筹。"
        "而去哪儿目前的热门目的地专题页，几乎都是在热搜出来之后才上的——永远晚一步。",
        first_line=True,
    )

    add_heading_cn(doc, "1.2 三大结构性矛盾", level=2)

    add_heading_cn(doc, "1.2.1 需求信号与供给能力严重脱节", level=3)
    add_para(
        doc,
        "我们对淄博、天水、哈尔滨、泉州、阿勒泰五个爆火城市做了全周期回溯分析（详见附录 A），发现一个清晰规律："
        "小红书笔记增速和抖音播放量增速领先 OTA 搜索量 5–10 天，领先微博热搜 7–14 天。"
        "以淄博为例，抖音「淄博烧烤」相关视频播放量在 2023 年 3 月初已出现异常增长，但 OTA 平台的专题页和供应链响应直到 4 月中旬热搜登顶后才启动，"
        "错失了近一个月的黄金窗口。中小城市的酒店、交通供给弹性极低——大城市多来 10 万人顶多涨价，小城市多来 2 万人可能直接没房。窗口期即瓶颈期。",
        first_line=True,
    )

    add_heading_cn(doc, "1.2.2 热度 ≠ 需求，现有工具难以区分", level=3)
    add_para(
        doc,
        "市面上舆情监控工具的核心逻辑是爬关键词、算热度趋势、发预警。这个思路存在一个致命缺陷：「热度在涨」和「旅游要爆」是两回事。"
        "用户可能只是觉得好玩转发一下（纯围观），并非真的要去（出行意图）。如果不加区分，模型的误报率会高到运营团队直接关掉系统。"
        "飞猪的热力地图反映的是当下热度而非未来趋势；携程问道和同程程心 AI 聚焦的是「已知目的地后怎么安排」，不是预测。"
        "现有方案无一个同时解决「预测 + 供给仿真 + 自动触发」。",
        first_line=True,
    )

    add_heading_cn(doc, "1.2.3 去哪网数据富矿被低估", level=3)
    add_para(
        doc,
        "去哪网后台拥有用户从搜索目的地关键词 → 点击酒店详情 → 收藏 → 下单的完整时间戳行为链路，覆盖机票、火车票、酒店、门票等多维度。"
        "这些数据是距离交易最近的意图信号——比社媒公开数据的信号纯度高一个数量级。但截至目前，这些数据主要用于事后报表复盘，从未被系统性地用于事前预测。"
        "这是去哪网握在手里但从未打出去的一张牌。",
        first_line=True,
    )

    add_heading_cn(doc, "1.3 命题题眼与核心公式", level=2)
    add_para(
        doc,
        "这个命题的题眼不是「预测下一个网红城市是谁」，而是构建一个以多源数据融合驱动的旅游热度早期预警系统，"
        "让去哪网从「热搜的搬运工」变成「趋势的定义者」。其核心竞争力来自一个简单的因果链：",
        first_line=True,
    )
    add_para(
        doc,
        "社媒内容增量信号 × 去哪网自有行为数据交叉验证 × 供给弹性仿真 = 可执行的业务预见。",
        bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=8,
    )
    add_para(
        doc,
        "三个要素中去哪网独占第二个，这是任何外部竞品都无法复制的护城河。",
        first_line=True,
    )

    # ==================== 二 ====================
    add_heading_cn(doc, "二、整体解决方案设计", level=1)

    add_heading_cn(doc, "2.1 方案概述", level=2)
    add_para(
        doc,
        "我们提出 Q-Trend——去哪网旅游趋势智能预测引擎，一个融合社媒多模态信号、去哪网内部行为数据、"
        "交通基础设施变化及宏观消费指标的多源 AI 预测系统。核心目标：在热搜出现前 7–14 天锁定潜力小城，"
        "输出热度置信度评分、爆发时间窗口预测及供给侧压力评估，赋能去哪网提前布局资源、抢占市场先机。"
        "与市面上所有方案的根本区别在于：Q-Trend 不只回答「哪里会火」，更回答「知道了之后该做什么」——把预测翻译成业务动作。",
        first_line=True,
    )

    add_heading_cn(doc, "2.2 四层系统架构", level=2)
    add_para(
        doc,
        "系统采用四层架构，每一层在设计上有明确的「防假阳性」职责——不是堆砌功能，而是每一层解决一个特定的误报来源。",
        first_line=True,
    )

    add_heading_cn(doc, "2.2.1 数据融合层（解决「数据不全」导致的假阳性）", level=3)
    add_para(doc, "汇聚三类异构数据：", first_line=True)
    add_bullets(
        doc,
        [
            "社媒内容增量：抖音、小红书城市维度的发帖量及互动量增速。收藏和分享的权重远高于点赞——前者表明用户「想留着以后用」，是更强的意图信号。",
            "去哪网后台搜索与预订行为链路：用户从「搜目的地关键词 → 点击酒店详情 → 收藏 → 下单」的完整时间戳数据。"
            "这是离交易最近的意图信号，外部竞品永远拿不到，是 Q-Trend 最核心的数据护城河。",
            "外部基建数据：12306 高铁线路新开通、民航支线航线批复、地方政府文旅消费券发放——这些是供给侧的先行指标，决定了一个城市「能不能接住」流量。",
        ],
    )
    add_para(
        doc,
        "仅依赖单一平台或单一维度的数据，信号噪声比不足以支撑可靠的预测。三源交叉验证是 Q-Trend 方案的第一道防线。",
        first_line=True,
    )

    add_heading_cn(doc, "2.2.2 信号提取层（解决「围观者 ≠ 出行者」导致的假阳性）", level=3)
    add_para(doc, "本层做三件事：", first_line=True)
    add_bullets(
        doc,
        [
            "A/B/C/D 意图分级：用大语言模型将社媒内容按出行意图分为四级——A 类纯围观（觉得好玩转发）、B 类种草（「好想去」）、"
            "C 类计划出行（「怎么去」「住哪里」）、D 类已出发。核心预警规则：B 类 + C 类占比在 3–5 天内从约 5% 跳升至 15% 以上时触发一级预警。"
            "这是整个方案最关键的一道过滤器——没有它，任何一个网红城市都会被误报。",
            "多模态视觉特征量化：用多模态模型（CLIP 思路）对城市内容池做视觉主题聚类，捕捉「烟火气美食画面」「高饱和蓝白冰雪配色」"
            "「治愈系自然风光」等易传播视觉基因的变化。爆火城市的内容往往共享特定的视觉模板——识别这些模板的出现频率变化就是识别热度潜力。",
            "有机增长与营销驱动分离：用时序异常检测算法，过滤掉去哪儿自身广告投放或促销带来的「已知原因增长」，"
            "只预警「没有已知原因、纯粹因为用户在别处看到内容自己跑来搜」的增长。",
        ],
    )

    add_heading_cn(doc, "2.2.3 预测引擎层（解决「单源不可靠」导致的假阳性）", level=3)
    add_para(doc, "多任务模型同时输出三个维度：", first_line=True)
    add_bullets(
        doc,
        [
            "会不会火：0–1 概率评分，融合社媒信号、行为信号、基建信号。",
            "什么时候火：基于三平台传播物理分模型预测爆发窗口——抖音主导型（S 型脉冲，1–2 周）、小红书主导型（渐进扩散，3–4 周）、"
            "双平台共振型（爆发力最强且持续时间最长，如哈尔滨）。不同窗口类型对应不同的供应链策略。",
            "火了之后接不接得住：供给压力仿真——将预测热度换算为预计搜索量和订单量，与酒店库存和价格弹性做对比，输出「满房风险指数」。"
            "这回答了任何一个供应链负责人都会问的问题：「你说这个地方要火——然后呢？我们该锁多少房？」",
        ],
    )
    add_para(
        doc,
        "附加模块「爆火基因库」：用五个已验证爆火城市爆发前 30 天的全维度数据构建城市特征向量库。"
        "候选城市自动匹配最相似的历史案例以校准预测。运营团队可以直观理解「这个城市现在跟 2024 年 2 月底的天水很像」——"
        "降低模型输出在组织内的认知翻译成本。",
        first_line=True,
    )

    add_heading_cn(doc, "2.2.4 业务行动层（解决「预测了但没人用」的落地假阳性）", level=3)
    add_para(doc, "预测做得再好，不落地就是废的。本层设计三管齐下：", first_line=True)
    add_bullets(
        doc,
        [
            "运营驾驶舱：实时热力地图 + 按紧迫度排列的预警列表 + 城市详情卡片。"
            "设计原则：运营同学打开面板后第一眼看到的是「现在需要做什么」，不是图表。",
            "三级自动触发体系：关注级（40–60% 概率，推送注意列表）→ 预警级（60–80%，附带 AI 信号报告和行动清单）→ "
            "行动级（>80%，自动生成目的地专题页草稿 + 推送锁房建议）。高风险决策（如锁房）始终保留人工确认节点。",
            "C 端潜力目的地板块：将模型预测信号转化为品牌心智——在去哪网 App 内以「趋势发现」形式提前曝光潜力城市，"
            "让用户觉得「去哪网有眼光，竟然提前知道这里要火」，从而实现从订票工具到趋势发现地的品牌升级。",
        ],
    )

    add_heading_cn(doc, "2.3 核心创新点", level=2)
    add_para(doc, "Q-Trend 与市面上现有方案存在三个根本性差异：", first_line=True)

    add_heading_cn(doc, "2.3.1 激活去哪网自有数据护城河", level=3)
    add_para(
        doc,
        "现有舆情方案全是基于社媒公开数据——它们只能回答「什么词在涨」，分不清涨的是围观还是出行意图。"
        "Q-Trend 将去哪网后台的搜索与预订行为链路作为交叉验证层——用户不只是「在看」，是真的「在搜、在比价、在收藏」。"
        "这套数据外部竞品永远拿不到，且以前去哪网内部也没人用它做预测。Q-Trend 本质上是在填补「数据在手但闲置」的空白。",
        first_line=True,
    )

    add_heading_cn(doc, "2.3.2 从「预测热度」推进到「仿真供给冲击」", level=3)
    add_para(
        doc,
        "市面上的 AI 方案终点都是「告诉你哪里会火」。Q-Trend 额外做了一整层供给压力仿真——因为去哪网有这个数据基础："
        "每个城市的酒店房间总数、平时入住率、价格弹性。「预测 + 仿真」的组合，让输出不再是一张图表或一份报告，"
        "而是一句业务团队可以直接行动的指令：「按目前信号，这个城市三天后酒店可能全满，现在不锁房就晚了。」"
        "从「知道」到「行动」的翻译成本被这一模块全部吸收。",
        first_line=True,
    )

    add_heading_cn(doc, "2.3.3 对预测失败做事前设计", level=3)
    add_para(
        doc,
        "大部分 AI 方案不会在开题阶段谈失败。但 Q-Trend 的设计哲学是：系统一定会出错。我们做了三层防御："
        "（1）分级响应机制保证高风险动作永远需要人工确认；"
        "（2）每个预测附带「如果判断错了，最大损失是多少」的估算——错过一个爆火城市的代价是损失酒店差价利润，误报导致锁房的代价是资金占用成本；"
        "（3）系统持续追踪自身准确率，每月自动调整阈值。"
        "更重要的是——如果某个城市的酒店库存极低（几十间房），即使模型概率只有 50%，也应提醒供应链团队看一眼，因为「错过了」的代价远大于「多看一眼」。"
        "这种对失败的设计不是悲观，而是组织信任——供应链团队不会因为一次误报就关掉系统，因为他们从一开始就知道误报会发生，并知道发生时损失可控。",
        first_line=True,
    )

    add_heading_cn(doc, "2.4 落地预期价值", level=2)
    add_table(
        doc,
        ["指标", "目标值", "测算依据"],
        [
            ["预警提前量", "领先微博热搜 7–14 天", "基于淄博/天水/哈尔滨等五城历史数据回溯验证"],
            ["TOP 10 命中率", "≥ 70%", "月度滚动评估，A/B 对照"],
            ["单城 GMV 增量", "+15% ~ +25%", "对比同期同体量未预警城市"],
            ["误报率", "≤ 30%（业务决策阈值）", "非技术上限——低于此值供应链 ROI 为正"],
            ["NPS「趋势发现」维度", "+5 分", "用户调研中新增趋势发现功能认知问卷"],
            ["沉默测试准确率提升", "每季度 +2–3%", "不对已预警城市做主动干预，验证模型真实效力"],
        ],
    )
    add_para(doc, "表 1：Q-Trend 可量化预期指标", size=10, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=6)
    add_para(
        doc,
        "注：所有数值基于历史案例回溯估算，实际落地后需以灰度测试数据校准。误报率 30% 不是技术上限，而是业务决策阈值——"
        "在这个水平下，供应链的抢先收益超过误报损失。我们将这一阈值交给业务团队自行调整，而非由算法团队替他们决定。",
        size=10,
        first_line=True,
    )

    add_heading_cn(doc, "2.5 落地可行性与可推广性", level=2)

    add_heading_cn(doc, "2.5.1 技术可行性", level=3)
    add_para(
        doc,
        "本方案不依赖任何尚未成熟的前沿技术。大语言模型和多模态模型的 API 已高度商品化，无论调用云端 API 还是私有化部署，研发门槛均已大幅降低。"
        "去哪网拥有覆盖机票、火车票、酒店、门票的全链路内部数据，数据基建无需从零搭建。"
        "数据的清洗和对齐（尤其是社媒时间粒度与 OTA 交易时间粒度的统一）是工程上的主要挑战，但属于「已知问题」而非「需要突破」。"
        "建议先在 5–10 个候选城市做灰度测试，3–4 个月即可完成从 0 到 MVP 的闭环。",
        first_line=True,
    )

    add_heading_cn(doc, "2.5.2 组织可行性", level=3)
    add_para(
        doc,
        "系统设计了三级响应机制和人工确认节点，高风险决策不追求全自动化——这不仅是技术选择，更是组织信任设计。"
        "误报容忍度和决策阈值交给业务团队自行设定，降低了跨部门推广的阻力。"
        "「沉默测试」机制（不对预测城市做主动干预，仅追踪预测准确率）为模型提供了低风险的迭代优化路径。",
        first_line=True,
    )

    add_heading_cn(doc, "2.5.3 跨行业可推广性", level=3)
    add_para(
        doc,
        "社媒信号 + 平台交易数据 + 外部基础设施的三源融合范式不限于旅游场景——"
        "本地生活（美团/大众点评的热门商圈预测）、演出票务（大麦的演唱会热度预警）、区域性消费品分销（快消品的区域需求预测）均可复用类似逻辑。"
        "去哪网如果跑通这一模式，将预测结果包装为「去哪网旅游趋势指数」对外发布，可进一步建立行业话语权和品牌影响力。",
        first_line=True,
    )

    # ==================== 三 附录 ====================
    add_heading_cn(doc, "三、附录", level=1)

    add_heading_cn(doc, "附录 A　五城爆火回溯分析", level=2)
    add_para(
        doc,
        "我们对五个典型爆火城市进行了全周期回溯分析，提炼传播规律以验证预测模型的特征有效性。"
        "选城标准：2023–2025 年间通过社媒自然引爆（非传统广告）、旅游相关搜索量三个月内出现 300% 以上增长的国内中小型城市。",
        first_line=True,
    )
    add_table(
        doc,
        ["城市", "爆发时间", "核心引爆物", "首发平台", "酝酿窗口", "关键早期信号"],
        [
            ["淄博", "2023.04", "烧烤", "抖音", "~3 周", "大学生组团视频、BGM 二创激增"],
            ["哈尔滨", "2023.12–2024.01", "冰雪大世界 + 南方小土豆", "抖音 + 小红书", "~2 周", "「南方小土豆」话题自然发酵"],
            ["天水", "2024.03", "麻辣烫", "抖音", "~10 天", "美食博主密集探店"],
            ["泉州", "2024 全年", "簪花", "小红书", "~4 周", "赵丽颖同款效应 + 文化符号化"],
            ["阿勒泰", "2024.05", "《我的阿勒泰》", "多平台联动", "~2 周", "影视 IP 带动 + 自然风光扩散"],
        ],
    )
    add_para(doc, "表 A-1：五城爆火回溯分析", size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "三个关键规律：", first_line=True)
    add_bullets(
        doc,
        [
            "抖音主导 = 脉冲式短窗口：淄博和天水皆由抖音率先引爆，热度上升曲线呈 S 型，从萌芽到爆发约需 1–3 周。适合快速响应型运营策略。",
            "小红书主导 = 渐进式长窗口：泉州簪花话题在小红书的扩散周期长达 4 周，增速平稳但持续性强。适合长线内容运营和品牌建设。",
            "双平台共振 = 最强组合：哈尔滨是唯一一个抖音和小红书同时出现非自然增长的案例，爆发的持续时间和 GMV 增长幅度均远超单平台案例。"
            "预测模型中双平台共振信号的权重应当最高。",
        ],
    )

    add_heading_cn(doc, "附录 B　核心参考资料", level=2)
    add_bullets(
        doc,
        [
            "中国旅游研究院《2024 年国内旅游景气报告》",
            "巨量引擎《2024 抖音文旅行业白皮书》",
            "小红书《2024 年度生活趋势报告》",
            "麦肯锡《中国消费趋势报告 2024》",
            "中国高铁网络通达性数据（12306 公开数据）",
            "2023–2025 各爆火城市百度指数、微信指数时间序列数据",
            "OTA 行业公开财报及年度运营数据",
        ],
    )

    add_heading_cn(doc, "附录 C　数据可获得性评估", level=2)
    add_para(doc, "以下为方案中所需数据源的可获得性评估，所有数据源均已有明确的获取路径：", first_line=True)
    add_table(
        doc,
        ["数据源", "可获得性", "说明"],
        [
            ["去哪网内部搜索/预订数据", "完全可控", "命题企业可直接提供或提供脱敏模拟数据"],
            ["抖音 / 小红书公开内容", "趋势级可得", "通过官方 API 或合规第三方数据服务获取"],
            ["高铁 / 航班时刻表及增量", "公开可得", "全国铁路运行图和民航时刻表均为公开信息"],
            ["百度指数 / 微信指数", "公开可得", "免费公开"],
            ["地方政府文旅活动及消费券", "公开可得", "各地方文旅局官方账号公开发布"],
        ],
    )
    add_para(doc, "表 C-1：数据可获得性评估", size=10, align=WD_ALIGN_PARAGRAPH.CENTER)

    add_heading_cn(doc, "附录 D　设计原则", level=2)
    add_para(doc, "Q-Trend 的设计遵循三个原则：", first_line=True)
    add_bullets(
        doc,
        [
            "诚实原则：系统一定会出错。不对预测失败做回避，而是将失败视为设计输入，将其代价显性化、可控化。",
            "护城河原则：差异化不来自「别人没想到的技术」，而来自「别人拿不到的数据 + 别人没做的取舍」。"
            "去哪网的搜索预订行为数据是唯一的；而我们决定不追求全自动锁房（保留人工确认）这个取舍，本身就是护城河。",
            "翻译原则：技术团队的输出必须能直接翻译成业务团队的行动。概率分数要被翻译成「该锁多少房」，"
            "时间窗口要被翻译成「专题页什么时候上」。如果一个预测不能被翻译成行动，它就不是预测——只是一个数字。",
        ],
    )

    add_para(
        doc,
        "飞书AI先锋未来人才大赛 · 去哪网选题 · Q-Trend 开题报告",
        size=9,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=0,
        name="宋体",
    )

    out1 = OUT_DIR / OUT_NAME
    out2 = ALT_DIR / OUT_NAME
    doc.save(str(out1))
    doc.save(str(out2))
    print("saved:", out1)
    print("saved:", out2)


if __name__ == "__main__":
    build()
