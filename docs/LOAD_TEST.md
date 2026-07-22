# Atlas Locust 压测报告（本地）

> 生成时间：2026-07-22  
> 环境：Windows · Atlas · `RAG_VECTOR_ENABLED=true` · Dense+Sparse Hybrid（`fastembed` · `BAAI/bge-small-zh-v1.5`）  
> 命令：`locust -f scripts/locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8000`
>
> 注意：下列基线生成于新增冷查询任务之前；冷热查询的新结果必须重新实测，不能沿用本页旧数字。

## 结果摘要

在 **20 并发用户**、持续 **30s** 的 Locust 压测中：

| 接口 | 请求数 | 失败 | 约 QPS | P50 | P95 | P99 |
|------|--------|------|--------|-----|-----|-----|
| `GET /api/knowledge/search` | 267 | **0** | **≈9.2** | 280ms | 740ms | ≈1000ms |
| `GET /api/health` | 158 | 0 | ≈5.4 | 69ms | 270ms | 370ms |
| `POST /api/chat`（短问） | 18 | **0** | ≈0.6 | 4.4s | 11s | 11s |
| Aggregated | 642 | **0** | **≈22** | 140ms | 740ms | — |

- 检索热路径在 20 并发下失败率 0%，检索 QPS 约 9+，P95 延迟约 740ms。
- Chat 路径含真实 LLM 调用，延迟更高属预期；`MAX_CONCURRENT_CHATS` 用于限制洪峰。
- HTML 报告与 CSV 均为本地生成物，不提交版本库；本文件保留可比较的摘要。

## 复现

### 30 秒冒烟

```powershell
cd <REPO_ROOT>
.\.venv\Scripts\python.exe -m locust -f scripts\locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8000 --csv docs\locust --html docs\locust_report.html
```

当前脚本将知识检索拆为两个独立统计项：

- `/api/knowledge/search`：已有知识主题的常规查询。
- `/api/knowledge/search [cold]`：大概率不在本地知识库中的查询，用于观察低命中/未命中路径。

### 3 分钟稳态

```powershell
.\.venv\Scripts\python.exe -m locust -f scripts\locustfile.py `
  --headless -u 50 -r 10 -t 180s `
  --host http://127.0.0.1:8000 `
  --csv docs\locust_steady --html docs\locust_steady_report.html
```

先跑 30 秒冒烟并确认失败数为 0，再运行稳态压测。评估时分别记录冷热查询的请求数、失败数、QPS、P50、P95 和 P99。

## 配置说明

1. **Dense+Sparse**：`RAG_VECTOR_ENABLED=true` 时使用本地向量索引 + lexical/TF-IDF 加权融合。Dense 默认 FastEmbed + BGE-small-zh-v1.5（512 维）。
2. **Graph**：`RAG_GRAPH_ENABLED=true` 时启用规则实体/关系抽取与子图检索。
3. **存储**：当前向量索引落盘为本地 JSON；可切换远程 Embedding 或后续接入 Qdrant 等向量库。
4. **账号隔离**：压测账户需要先注册/登录；若压测接口不含认证，设置 `ATLAS_USER_AUTH=false` 仅用于本机压测。

## 验收门槛

- `/api/knowledge/search` 与 `/api/knowledge/search [cold]` 的失败数均为 0。
- 两条检索路径 P95 均低于 2000ms。
- 429 只允许出现在 chat 背压路径，不应算服务端故障；其他 4xx/5xx 必须调查。
- 简历或 README 中的 QPS/P95 只引用本机本次报告，不复制历史或外部方案数字。
