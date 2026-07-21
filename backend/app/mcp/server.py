"""
Atlas MCP Server — exposes knowledge / web / research tools over stdio.

Run (for Cursor / Claude Desktop):
  .\\.venv\\Scripts\\python.exe scripts\\mcp_server.py

Protocol: MCP JSON-RPC with Content-Length framing (no official mcp SDK; Py3.9).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python scripts/mcp_server.py` and package imports
ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.mcp.protocol import (  # noqa: E402
    read_message,
    rpc_error,
    rpc_result,
    tool_spec_to_mcp,
    write_message,
)
from app.tools import TOOL_HANDLERS, TOOL_SPECS, run_tool  # noqa: E402

SERVER_INFO = {
    "name": "atlas-mcp",
    "version": "0.1.0",
}

PROTOCOL_VERSION = "2024-11-05"


def list_tools() -> list[dict[str, Any]]:
    return [tool_spec_to_mcp(s) for s in TOOL_SPECS if s.get("function", {}).get("name")]


async def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if name not in TOOL_HANDLERS:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)}],
            "isError": True,
        }
    try:
        raw = await run_tool(name, arguments or {})
    except Exception as exc:  # noqa: BLE001
        return {
            "content": [{"type": "text", "text": f"tool error: {exc}"}],
            "isError": True,
        }
    return {
        "content": [{"type": "text", "text": raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)}],
        "isError": False,
    }


async def handle_request(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications have no id
    if req_id is None and method:
        if method == "notifications/initialized":
            return None
        if method == "notifications/cancelled":
            return None
        return None

    if method == "initialize":
        return rpc_result(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": SERVER_INFO,
            },
        )

    if method == "ping":
        return rpc_result(req_id, {})

    if method == "tools/list":
        return rpc_result(req_id, {"tools": list_tools()})

    if method == "tools/call":
        name = params.get("name") or ""
        arguments = params.get("arguments") or {}
        result = await call_tool(name, arguments)
        return rpc_result(req_id, result)

    if method == "resources/list":
        return rpc_result(req_id, {"resources": []})

    if method == "prompts/list":
        return rpc_result(req_id, {"prompts": []})

    return rpc_error(req_id, -32601, f"Method not found: {method}")


async def serve_stdio() -> None:
    # Log to stderr only — stdout is reserved for MCP framing
    sys.stderr.write("Atlas MCP server ready (stdio)\n")
    sys.stderr.flush()
    loop = asyncio.get_event_loop()
    while True:
        msg = await loop.run_in_executor(None, read_message)
        if msg is None:
            break
        # Ignore malformed
        if not isinstance(msg, dict):
            continue
        # Notifications
        if "method" in msg and "id" not in msg:
            await handle_request(msg)
            continue
        if "method" not in msg:
            continue
        reply = await handle_request(msg)
        if reply is not None:
            write_message(reply)


def main() -> None:
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
