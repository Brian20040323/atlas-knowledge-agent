---
name: atlas-eval-gate
description: Run Atlas evaluation gates after changing Agent, RAG, routes, prompts, or configuration.
---

# Atlas 评测门禁

用于“跑评测”“RAG 回归”“改 Prompt 后验证”“CI 为什么失败”。

## 执行

在仓库根目录使用项目 venv：

```powershell
.\.venv\Scripts\python.exe scripts\run_eval.py
```

快速检查可按类别运行：

```powershell
.\.venv\Scripts\python.exe scripts\run_eval.py --category degrade,harness
```

## 判定

- 退出码为 `0` 才能宣称通过。
- 改 Prompt、路由、检索或降级行为后必须运行全量题库。
- 若更改向量路径，另以 `RAG_VECTOR_ENABLED=true` 运行对应降级用例，并确认检索标识为 `dense+sparse-hybrid`。
- 将通过数、失败 case 与运行环境追加到 `规范文档/eval-baselines/`；不要把临时终端日志当基线。
