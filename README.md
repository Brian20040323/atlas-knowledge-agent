# AI Fullstack Starter

面向 **AI Agent / LLM 应用开发** 实习的可运行脚手架。

规范文档（唯一源）：[`规范文档/README.md`](规范文档/README.md)  
按规范写代码前必读：[`规范文档/07-现状差距与实现待办.md`](规范文档/07-现状差距与实现待办.md)  
（旧 `docs/` 仅重定向，勿再往那里写规范）

## 已包含

- FastAPI 后端 + SSE 流式对话
- Tool Calling（时间查询、计算器）
- Mock 模式：无 API Key 也能跑通全流程
- 静态前端聊天页
- **私有 SQLite 工作区**：会话、消息和知识库文档按账号隔离
- **自我学习查阅**：知识库学习 + 检索引用回答
- **多方面自主学习**：本地不足时从开放百科检索地理/历史/数学/行业等并自动入库
- **联网查询**：DuckDuckGo 开放网页搜索 + 摘要抓取，用于回答最新/库外问题
- **深度思考**：先展示推理过程，再输出准确结论
- **Agent 规划 + ReAct 循环**：意图路由 → 多步工具 → 综合作答（自研轻量实现）
- **分块检索**：长文档按句切分重叠块再打分（简易 RAG）
- **混合检索**：关键词 + TF-IDF；**Dense+Sparse Hybrid**（FastEmbed/BGE 本地神经向量 + lexical，可切换）
- **可选知识图谱**：SQLite 实体/关系表 + 子图检索（轻量 GraphRAG）
- **压测**：Locust 脚本 + `docs/LOAD_TEST.md`（QPS / P95；原始报告本地生成）
- **可观测性**：每轮 Agent Trace（耗时 / spans），`GET /api/runs`
- **评测集**：`scripts/run_eval.py` + `backend/tests/eval/cases.yaml`（含向量/图谱开关用例）
- **会话历史侧栏**：切换最近对话
- **本地语音**：Whisper STT + XTTS 音色克隆
- 文档表（RAG 知识库）

## 开源思路借鉴（已改写，非直接拷贝）

本项目**不依赖** LangChain / LangGraph，但吸收了常见开源 Agent 的设计并本地化：

| 思路 | 参考方向 | Atlas 中的实现 |
|------|----------|----------------|
| 条件路由图 | [agent-service-toolkit](https://github.com/JoshuaC215/agent-service-toolkit)（LangGraph edges） | `agents/planner.py` 意图路由 |
| Agentic RAG | [agentic_rag_project](https://github.com/serkanyasr/agentic_rag_project) | 先检索再决定 research/web |
| ReAct 循环 | Yao et al. / LangGraph ToolNode | `agents/loop.py` Thought→Action→Observation |
| 文本分块 | LangChain TextSplitter 类思路 | `rag/chunking.py` 自研切分 |
| Hybrid RAG | 向量库常见 hybrid 检索 | `rag/hybrid.py` TF-IDF + lexical；可选 `rag/retriever.py` 向量混合（默认关） |
| Tracing | Langfuse / OpenAI traces | `observability/traces.py` 轻量 spans |
| MCP | Cursor / Claude Desktop 工具协议 | `app/mcp/` 自研 stdio Server + Client |

完整脚手架可参考：[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-fastapi-nextjs-llm-template)（本仓库刻意保持无 npm、可 Mock 的轻量形态）。

## 快速启动

```powershell
cd <REPO_ROOT>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env
python run.py
```

浏览器打开：http://127.0.0.1:8000

## 接入真实模型

编辑 `.env`：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash
MOCK_MODE=auto
```

性价比建议用 DeepSeek（兼容 OpenAI 接口）。也可换成 OpenAI / 通义等。`MOCK_MODE=auto` 时：有 Key 走真实 LLM，无 Key 自动 Mock。

## 账号与访问边界

- `ATLAS_USER_AUTH=true`（默认）：注册并登录后使用；对话和知识库文档仅本人可见。
- `ATLAS_REGISTER_SECRET`：非空时，注册必须填写邀请码。
- `ATLAS_PUBLIC_PASSWORD`：为公网演示增加站点口令；它不能替代账号登录。
- 默认仅允许同源浏览器请求。如有独立前端，在 `CORS_ORIGINS` 填写允许的完整来源（逗号分隔）。

## 数据库（SQLite）

默认数据库文件：`data/app.db`（首次启动自动建表）

| 表 | 用途 |
|---|---|
| `conversations` | 会话列表 |
| `messages` | 对话消息 |
| `documents` | RAG 文档 |
| `graph_entities` / `graph_relations` | 可选知识图谱（P4，默认不写入） |

可选配置（`.env`）：

```env
DATABASE_URL=sqlite+aiosqlite:///C:/path/to/app.db
```

### 自我学习查阅

1. **学习知识**（仅当前登录账号可见，任选一种）：
   - 对话：`记住：FastAPI入门|FastAPI 是 Python 异步 Web 框架`
   - **自主学习**：`自主学习：工业革命`（多方面检索百科并写入知识库）
   - **联网查询**：`联网：今天科技新闻` / 问题中含「最新、搜索」时自动联网
   - 左侧面板：填写标题和内容后点击「保存到知识库」
   - **导入文件**：PDF / 图片 / TXT / MD（`POST /api/knowledge/upload`）
   - API：`POST /api/knowledge/learn`
   - 普通提问时若本地知识不足，也会自动触发多方面检索并学习

2. **严谨回答**：
   - 文末「**参考**」列出标题，并带可追溯的 `document_id=`
   - 有库内证据才断言；不足处明确说明并提示学习 / 联网
   - 资源上限见 `.env.example`（`UPLOAD_MAX_MB` / `DOC_MAX_CHARS` / `RAG_*` / `AGENT_MAX_STEPS`）
   - P2 可观测与限流：`HTTP_TIMEOUT_*` / `LLM_TIMEOUT_SECONDS` / `MAX_CONCURRENT_CHATS` / `WEB_CIRCUIT_FAIL_THRESHOLD`；`GET /api/runs` 可查检索与工具 spans，超额并发返回 429
  - P3 向量检索（默认关闭）：设置 `RAG_VECTOR_ENABLED=true` 后走 **Dense+Sparse Hybrid**（本地向量索引 + lexical/TF-IDF）。推荐 `RAG_EMBEDDING_PROVIDER=fastembed` + `BAAI/bge-small-zh-v1.5`；首次启动会下载模型。观测：`GET /api/knowledge/retrieval-meta`，重建索引：`POST /api/knowledge/reindex`
  - P4 图谱默认关闭；私有知识库模式下不启用，以避免跨账号图谱泄露。

### 压测（Locust）

```powershell
.\.venv\Scripts\python.exe -m locust -f scripts\locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8000 --csv docs\locust --html docs\locust_report.html
```

最近一次本地结果（20 并发 / 30s，失败率 0%）：检索接口约 **9.2 QPS**，P95≈**740ms**。详见 [`docs/LOAD_TEST.md`](docs/LOAD_TEST.md)；HTML/CSV 原始报告由命令在本地生成，不纳入版本库。

3. **语音**：
   - 麦克风：浏览器语音识别（Chrome/Edge，需授权）
   - 喇叭：默认系统朗读；配置 ElevenLabs 后可用**你的克隆音色**

### 用自己的声音当助手回复音

推荐本地免费克隆：侧边栏上传 10–30 秒清晰中文，或放入 `data/voice/clone_sample.wav`。也可用 ElevenLabs（见 `.env.example`）。

### MCP（把 Atlas 工具接到 Cursor）

本机 Python 3.9 无法安装官方 `mcp` 包，因此实现了**兼容 MCP stdio 协议**的轻量 Server/Client。

**作为 MCP Server（推荐）** — 让 Cursor 调用 Atlas 的知识库 / 联网等工具：

1. 打开 Cursor → Settings → MCP
2. 参考项目根目录 `mcp.cursor.example.json` 添加：

```json
{
  "mcpServers": {
    "atlas": {
      "command": "C:\\\\Users\\\\czy2004\\\\Desktop\\\\AI 全栈开发\\\\.venv\\\\Scripts\\\\python.exe",
      "args": ["C:\\\\Users\\\\czy2004\\\\Desktop\\\\AI 全栈开发\\\\scripts\\\\mcp_server.py"]
    }
  }
}
```

3. 重启 Cursor MCP 后，可在对话里使用 `search_knowledge` / `web_search` 等工具

本地自检：

```powershell
.\.venv\Scripts\python.exe scripts\test_mcp.py
```

**作为 MCP Client（可选）** — 让 Atlas Agent 调用外部 MCP 工具：在 `.env` 设置 `MCP_ENABLED=true` 与 `MCP_SERVERS=...`（见 `.env.example`）。

HTTP 调试：`GET /api/mcp/tools`、`POST /api/mcp/call`

### 评测与追踪

```powershell
.\.venv\Scripts\python.exe scripts\run_eval.py
.\.venv\Scripts\python.exe scripts\demo_scenarios.py
```

- `GET /api/runs` — 最近 Agent 运行 traces（耗时 / spans）
- `GET /api/knowledge/graph?query=Agent` — 可选图谱子图（默认 `graph_disabled`）
- 对话过程中状态栏会显示本轮 `trace …ms`
- CI：`.github/workflows/eval.yml` 可在 push/PR 时跑评测（可选）

4. **深度思考**：前端开关 / API `deep_think: true`

5. **检索 API**：`GET /api/knowledge/search?query=FastAPI`

### API

- `GET /api/conversations` — 会话列表
- `GET /api/conversations/{id}/messages` — 某会话消息
- `POST /api/chat` — 支持 `conversation_id`，流式结束后自动写入 DB
- `GET /api/runs` / `GET /api/runs/{id}` — Agent 可观测性
- `POST /api/documents` — 新增文档
- `GET /api/documents` — 文档列表

前端会把 `conversation_id` 存在 `localStorage`，刷新页面后自动恢复历史对话。

### 查看数据库

- 安装 [DB Browser for SQLite](https://sqlitebrowser.org/) 打开 `data/app.db`
- 或在 VS Code 安装 SQLite 插件直接查看

## 目录结构

```
AI 全栈开发/
├── backend/app/
│   ├── main.py          # FastAPI 入口
│   ├── config.py        # 环境配置
│   ├── api/             # HTTP / SSE 路由
│   ├── agents/          # Chat Agent + Tool Calling
│   ├── db/              # SQLite 模型与 CRUD
│   ├── tools/           # 内置工具（含 search_graph）
│   └── rag/             # 分块 / hybrid / 向量 / 图谱
├── data/
│   └── app.db           # SQLite（含可选 graph_* 表）
├── 规范文档/            # 唯一规范源（架构、评测、变更记录）
├── docs/                # 旧规范重定向 + 运维说明（如压测）
├── scripts/             # run_eval / demo_scenarios / mcp
├── frontend/            # 聊天 UI
├── run.py               # 一键启动
├── skills/               # 可版本化的评测、诊断与配置检查 Skills
└── .env.example
```

## 项目 Skills

- `skills/atlas-eval-gate`：Agent、RAG、Prompt 改动后的评测门禁。
- `skills/atlas-rag-diagnose`：在当前账号范围内定位导入、检索和 Trace 问题。
- `skills/atlas-config-drift`：发布前核对代码默认值、示例环境、CI 与文档。
- `.cursor/skills/atlas-policy-selftest`：制度导入 L0–L5 分层验收。

## 下一步可扩展（规范主线 P0–P4 已落地）

1. Multi-Agent（LangGraph / CrewAI）
2. 更强 embedding（sentence-transformers 等）与专用向量库 — 接口已预留
3. 图谱迁 Neo4j / LLM 抽取（当前为 SQLite + 规则抽取 MVP）
4. Trace 持久化、Langfuse 等外部可观测性
