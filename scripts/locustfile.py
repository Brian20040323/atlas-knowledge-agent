"""Locust load test for Atlas HTTP API (read path + short chat).

Usage (server on :8000):
  .\.venv\Scripts\python.exe -m locust -f scripts/locustfile.py --headless -u 20 -r 5 -t 30s --host http://127.0.0.1:8000 --csv docs/locust --html docs/locust_report.html
"""

from __future__ import annotations

from locust import HttpUser, between, task


class AtlasUser(HttpUser):
    wait_time = between(0.2, 0.8)

    @task(5)
    def health(self) -> None:
        self.client.get("/api/health", name="/api/health")

    @task(3)
    def meta(self) -> None:
        self.client.get("/api/meta", name="/api/meta")

    @task(3)
    def retrieval_meta(self) -> None:
        self.client.get("/api/knowledge/retrieval-meta", name="/api/knowledge/retrieval-meta")

    @task(8)
    def search(self) -> None:
        self.client.get(
            "/api/knowledge/search",
            params={"query": "什么是 Agent Runtime", "top_k": 3},
            name="/api/knowledge/search",
        )

    @task(2)
    def search_cold(self) -> None:
        # 冷查询：query 大概率不在本地 KB，触发空/低命中的 fallback 路径，
        # 用于观察未命中时的检索延迟与稳定性（与热查询分开统计）。
        self.client.get(
            "/api/knowledge/search",
            params={"query": "量子计算基本原理", "top_k": 5},
            name="/api/knowledge/search [cold]",
        )

    @task(1)
    def chat_once(self) -> None:
        with self.client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "现在几点了？"}],
                "use_tools": True,
                "deep_think": False,
            },
            name="/api/chat",
            catch_response=True,
            timeout=60,
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")
            elif resp.status_code == 429:
                resp.success()  # backpressure expected under load
            elif resp.status_code >= 400:
                resp.failure(f"client error {resp.status_code}: {resp.text[:120]}")
            else:
                resp.success()


# 稳态压测（推荐用于性能评估，ramp-up 后维持 3 分钟稳态）：
#   .\.venv\Scripts\python.exe -m locust -f scripts/locustfile.py `
#     --headless -u 50 -r 10 -t 180s `
#     --host http://127.0.0.1:8000 `
#     --csv docs/locust_steady --html docs/locust_steady_report.html
#
# 参数说明：
#   -u 50   最大并发 50 用户
#   -r 10   每秒启动 10 个用户（ramp-up）
#   -t 180s 持续 3 分钟（覆盖稳态，避免只测到冷启动）
#
# 注意：若 ATLAS_USER_AUTH=true，知识库 / chat 接口需登录态，
# 压测前可临时置为 false，或改用带 Cookie 的自定义 client。
