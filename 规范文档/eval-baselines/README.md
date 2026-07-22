# Eval baselines

## Phase 0 — 2026-07-21（Harness 锁标准）

Command: `python scripts/run_eval.py --category harness`

Result: **7/7 passed**（当时尚未含 `web_empty_honest`）

| Case | Result |
|------|--------|
| harness_entity_chaling | PASS |
| harness_entity_nanya | PASS |
| harness_clarify_reimburse | PASS |
| harness_clarify_salary | PASS |
| harness_web_news_locked | PASS |
| harness_sanitize_tool_calls | PASS |
| harness_policy_meal_star | PASS |

## Phase 4 — 2026-07-21（全量冻结）

Command: `python scripts/run_eval.py`

Result: **149/149 passed**

Harness（8/8，含 `harness_web_empty_honest`）全绿；泄漏用例 100% 过；intent 路由相对 Phase 0 不降。

静态资源 cache-bust：`?v=20260721harness1`
