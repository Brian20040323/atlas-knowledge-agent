"""Tests for Atlas ExecutionGraph v1 (staged trajectory)."""

from __future__ import annotations

import unittest

from app.observability.traces import AgentTrace, normalize_graph, run_payload_to_graph, stages_from_graph


class TraceGraphV1Tests(unittest.TestCase):
    def test_to_graph_stages_and_types(self) -> None:
        t = AgentTrace(run_id="r1", query="差旅报销标准？")
        with t.span("retrieve_local", query="差旅"):
            pass
        with t.span("plan"):
            pass
        with t.span("llm_synthesize"):
            pass
        t.intent = "policy_qa"
        payload = t.finish(mode="answer", answer="按制度…")
        g = payload["graph"]
        self.assertEqual(g["schema_version"], "1.0")
        types = [n["type"] for n in g["nodes"]]
        self.assertEqual(types[0], "input")
        self.assertIn("plan", types)
        self.assertIn("retrieve", types)
        self.assertEqual(types[-1], "answer")
        stages = {n["id"]: n["stage"] for n in g["nodes"]}
        self.assertEqual(stages["input"], "input")
        self.assertEqual(stages["intent"], "reason")
        retrieve_id = next(n["id"] for n in g["nodes"] if n["type"] == "retrieve")
        self.assertEqual(stages[retrieve_id], "execute")
        self.assertEqual(stages["answer"], "answer")
        # Detail whitelist — no raw arbitrary meta dump
        retrieve = next(n for n in g["nodes"] if n["type"] == "retrieve")
        self.assertTrue(set(retrieve["detail"]).issubset({"query_summary", "result_count", "model", "fallback", "error_type"}))

    def test_run_payload_rebuild_and_stages(self) -> None:
        g = run_payload_to_graph(
            {
                "run_id": "x",
                "query": "q",
                "intent": "chitchat",
                "mode": "chitchat",
                "spans": [{"name": "plan", "duration_ms": 1.0, "meta": {}, "error": None}],
            }
        )
        self.assertEqual(g["schema_version"], "1.0")
        stage_ids = [s["id"] for s in stages_from_graph(g)]
        self.assertEqual(stage_ids, ["input", "reason", "answer"])

    def test_normalize_drops_dangling_and_whitelists(self) -> None:
        g = normalize_graph(
            {
                "schema_version": "1.0",
                "run": {"id": "x", "status": "success", "duration_ms": 1, "stop_reason": "final"},
                "summary": {"tool_count": 0, "failed_count": 0},
                "nodes": [
                    {
                        "id": "input",
                        "type": "input",
                        "stage": "input",
                        "label": "q",
                        "status": "success",
                        "detail": {"secret": "nope", "query_summary": "q"},
                    },
                    {"id": "answer", "type": "answer", "stage": "answer", "label": "ok", "status": "success"},
                ],
                "edges": [
                    {"source": "input", "target": "answer", "relation": "sequence"},
                    {"source": "input", "target": "missing", "relation": "sequence"},
                ],
            }
        )
        self.assertTrue(all(e["target"] != "missing" for e in g["edges"]))
        detail = g["nodes"][0]["detail"]
        self.assertNotIn("secret", detail)
        self.assertIn("query_summary", detail)


if __name__ == "__main__":
    unittest.main()
