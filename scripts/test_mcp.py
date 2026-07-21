"""Self-test Atlas MCP stdio server (initialize → tools/list → tools/call)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.mcp.protocol import read_message, write_message  # noqa: E402


def main() -> int:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    script = ROOT / "scripts" / "mcp_server.py"
    proc = subprocess.Popen(
        [str(py), str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT),
        bufsize=0,
    )
    assert proc.stdin and proc.stdout

    def req(method: str, params: dict | None = None, req_id: int = 1) -> dict:
        write_message(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
            proc.stdin,
        )
        while True:
            msg = read_message(proc.stdout)
            if msg is None:
                err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
                raise RuntimeError(f"no response; stderr={err[:500]}")
            if msg.get("id") == req_id:
                return msg

    try:
        init = req(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
            1,
        )
        print("initialize:", json.dumps(init.get("result", {}).get("serverInfo"), ensure_ascii=False))

        write_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            proc.stdin,
        )

        listed = req("tools/list", {}, 2)
        tools = (listed.get("result") or {}).get("tools") or []
        names = [t.get("name") for t in tools]
        print("tools:", names)
        assert "search_knowledge" in names
        assert "web_search" in names

        called = req(
            "tools/call",
            {"name": "calculator", "arguments": {"expression": "12+30"}},
            3,
        )
        text = ((called.get("result") or {}).get("content") or [{}])[0].get("text")
        print("calculator:", text)
        assert "42" in (text or "")

        print("MCP self-test PASS")
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
