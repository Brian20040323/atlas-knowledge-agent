# Atlas · 知识助手 Agent

本地可运行的知识助手：对话前端 + FastAPI + SSE，意图路由 → 多工具 ReAct → 混合检索，支持账号隔离、引用答疑与 Trace 可观测。

**关联仓库：** [lite-react-agent](https://github.com/Brian20040323/lite-react-agent) · [hybrid-rag-kit](https://github.com/Brian20040323/hybrid-rag-kit) · [mcp-knowledge-bridge](https://github.com/Brian20040323/mcp-knowledge-bridge)

## 功能概览

- FastAPI 后端 + SSE 流式对话；Mock 模式无 API Key 可跑通
- 私有 SQLite 工作区：会话 / 消息 / 知识库按账号隔离
- Agent：意图路由 → 多步工具 → 综合作答（自研轻量 ReAct，不依赖 LangChain / LangGraph）
- 检索：分块 + 关键词 / TF-IDF；可选 Dense+Sparse（默认关）
- 空库 / 证据不足时可拒答或降级说明；回答可带引用
- 可观测：`GET /api/runs` Trace（耗时 / spans）
- 评测：`scripts/run_eval.py` + YAML 用例
- 可选：联网检索、知识图谱、语音（按配置开启，非默认主路径）

## 快速开始

```powershell
cd <REPO_ROOT>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env
python run.py
```

浏览器打开：http://127.0.0.1:8000

真实模型（示例 DeepSeek，OpenAI 兼容）：

```env
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
MOCK_MODE=auto
```

## 目录结构

```
atlas-knowledge-agent/
├── backend/app/     # API · Agent · RAG · DB · tools
├── frontend/        # 静态聊天 UI
├── scripts/         # 评测 / MCP / 演示脚本
├── skills/          # Cursor Skills（评测门禁等）
├── 规范文档/         # 架构与验收规范（中文）
├── docs/            # 运维说明（如压测）
└── run.py
```

## 诚实边界

- 外部真实用户规模有限；价值以可演示产品 + 评测 / Trace 验证为主
- 向量检索、图谱、语音等为可选能力，默认演示走稀疏检索主路径
- 压测数字来自本地 Locust，不是公网 SLA

## License

见仓库内许可说明；个人作品集用途。
