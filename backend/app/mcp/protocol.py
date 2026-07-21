"""Minimal MCP (Model Context Protocol) JSON-RPC framing — no official SDK (Py3.9)."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def read_message(stream: TextIO = sys.stdin.buffer) -> dict[str, Any] | None:
    """Read one MCP message (Content-Length framed)."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        try:
            text = line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if ":" in text:
            key, val = text.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    length = int(headers.get("content-length", "0") or 0)
    if length <= 0:
        return None
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(payload: dict[str, Any], stream: TextIO = sys.stdout.buffer) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
    stream.write(header + data)
    stream.flush()


def rpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def tool_spec_to_mcp(spec: dict[str, Any]) -> dict[str, Any]:
    """Convert OpenAI-style TOOL_SPECS entry to MCP tools/list item."""
    fn = spec.get("function") or {}
    return {
        "name": fn.get("name"),
        "description": fn.get("description") or "",
        "inputSchema": fn.get("parameters")
        or {"type": "object", "properties": {}},
    }
