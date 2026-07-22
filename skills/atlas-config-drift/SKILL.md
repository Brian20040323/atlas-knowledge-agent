---
name: atlas-config-drift
description: Compare Atlas runtime defaults, sample environment, CI, and documentation before release.
---

# Atlas 配置漂移检查

用于“配置不一致”“发版前检查”“默认值为什么不同”。

## 对照源

- `backend/app/config.py`：运行时默认值。
- `.env.example`：新环境的安全推荐值。
- `.github/workflows/eval.yml`：CI 覆盖的明确环境。
- `README.md` 与 `规范文档/06-架构分层与迭代计划.md`：用户与架构口径。

## 必检项

`ATLAS_USER_AUTH`、`CORS_ORIGINS`、上传上限、并发与超时、vector/graph/rerank/FAQ 开关、embedding provider/model/dimension、Python 版本。

## 判定

- 代码与 `.env.example` 的默认值必须一致，或在样例中明确注明覆盖目的。
- CI 必须显式写出会影响评测的开关。
- 文档不得把可选功能描述为默认功能。
- 发现漂移时先确定目标默认值，再同一变更中同步四个来源。
