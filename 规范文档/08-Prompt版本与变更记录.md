# 08 · Prompt 版本与变更记录

> 依据：[05-工程化规范.md](05-工程化规范.md) §4  
> 规则：改 Prompt 必须升版本号 + 本表记一行 + 跑评测  
> 版本账本起始：v1.0 · 2026-07-16

---

## 1. 版本号约定

| 项 | 约定 |
|----|------|
| 常量名 | `SYSTEM_PROMPT_VERSION` / `PROMPT_SYNTH_VERSION` / `THINKING_PROMPT_VERSION` |
| 格式 | `{模块}_v{n}` |
| 存放 | `backend/app/agents/__init__.py`、`reasoning.py` |
| Trace | `trace.meta.prompt_versions` |
| 禁止 | 只改字符串不改版本；版本不进 Trace |

---

## 2. 当前登记

| 版本 | 日期 | 模块 | 变更说明 | 关联评测 |
|------|------|------|----------|----------|
| atlas_system_v3 | 2026-07-21 | SYSTEM_PROMPT | 制度推理层：三步推理法（定位原则→类比推演→结构化回答）；铁律从4条扩至5条（+反注入条款）；新增民宿/打车等推理示例；替换v2的角色描述和风格约束 | 待跑分 |
| atlas_system_v2 | 2026-07-21 | SYSTEM_PROMPT | 重构分层：角色/铁律/结构/示例四段式（已被v3覆盖） | — |
| policy_synth_v1 | 2026-07-16 | Mock/拒答综合语义 | 与制度拒答话术对齐 | `policy_missing_*` |
| thinking_append_v1 | 2026-07-16 | THINKING_SYSTEM_APPEND | 制度禁编造条款 | `prompt_versions_defined` |
| atlas_system_v1 | 2026-07-16 | SYSTEM_PROMPT | 初版编号；制度无据须拒绝 | `prompt_versions_defined` |

---

## 3. 变更记录

| 版本 | 日期 | 变更 | 改前 | 改后 | 结论 |
|------|------|------|------|------|------|
| atlas_system_v3 | 2026-07-21 | 制度推理三层结构+新示例；铁律+反注入；回答格式改为四段式 | 126/126 (v2未跑) | (待跑) | 待评测 |
| atlas_system_v2 | 2026-07-21 | 角色/铁律/结构/示例重构 | v1 126/126 | (未跑) | 被v3覆盖 |
| atlas_system_v1 等 | 2026-07-16 | T5 挂版本号 + Trace meta | 52/52 | 126/126 | 有效 |

---

## 4. v3 变更详情

### 4.1 结构变更

| 节 | v2 | v3 |
|----|-----|-----|
| 角色 | 通用研究型助手 | 企业制度推理引擎 |
| 铁律 | 4条 | 5条（+反注入条款） |
| **制度推理方法** | ❌ 无 | 🆕 三步推理法（定位→类比→回答） |
| 示例 | 问答式 | 四段式（制度依据/推理分析/结论/补充说明） |
| 回答结构 | 结论→展开→参考 | v2 保留 |
| 短问澄清 | 有 | 保留 |
| 复合问题 | 有 | 保留 |

### 4.2 风险与回滚

- 若 v3 导致 `run_eval` 退化 → 回滚至 `atlas_system_v1`
- v3 prompt 约 650 tokens，token 消耗增加但仍在预算内

---

## 5. 检查清单

- [x] 代码侧已挂 `atlas_system_v3`  
- [x] Trace 含 `prompt_versions`  
- [x] 本表已登记  
- [ ] `run_eval` 验证  
