---
name: atlas-rag-diagnose
description: Diagnose Atlas private knowledge retrieval, index state, and evidence quality without exposing another user's documents.
---

# Atlas RAG 检索诊断

用于“检索不准”“文档导入后找不到”“向量索引问题”“为什么这样回答”。

## 前置

1. 服务已启动。
2. 账号隔离开启时，必须以目标用户登录并使用该会话 cookie；不得用另一账号读取或对比文档。

## 检查顺序

1. `GET /api/health` 确认服务与模型模式。
2. `GET /api/knowledge/retrieval-meta` 确认 TF-IDF 或 `dense+sparse-hybrid` 路径。
3. `GET /api/documents` 核对目标文件属于当前账号。
4. `GET /api/knowledge/search?query=...` 核对 title、excerpt、score 和 `retrieval`。
5. 需要时调用受保护的 `POST /api/knowledge/reindex`，然后重复第 4 步。
6. 对错误回答查看 `GET /api/runs/{run_id}` 的 retrieve、plan、tool spans。

## 输出

报告必须区分：未入库、无权限、无召回、排序错误、模型综合错误、外部服务失败。不得在报告中输出其他用户的文档正文。
