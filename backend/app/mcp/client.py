"""
MCP Client — connect to external MCP servers (stdio) and adapt tools for Atlas.

Config example (.env):
  MCP_ENABLED=true
  MCP_SERVERS=[{"name":"demo","command":"python","args":["scripts/mcp_server.py"]}]

Note: connecting Atlas to its own mcp_server in-process is usually unnecessary;
use this to pull in *external* MCP tools (filesystem, github, etc.).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR
from app.mcp.protocol import read_message, rpc_result, write_message

# Avoid circular import at module load for TOOL registry mutation
_loaded = False
_lock = threading.Lock()


@dataclass
class McpServerProc:
    name: str
    process: subprocess.Popen
    _req_id: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin and self.process.stdout
        req_id = self.next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        write_message(payload, self.process.stdin)
        # Read until matching id (skip notifications)
        while True:
            msg = read_message(self.process.stdout)
            if msg is None:
                raise RuntimeError(f"MCP server '{self.name}' closed unexpectedly")
            if msg.get("id") == req_id:
                if "error" in msg:
                    err = msg["error"]
                    raise RuntimeError(f"MCP error: {err.get('message') or err}")
                return msg.get("result") or {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.process.stdin
        write_message(
            {"jsonrpc": "2.0", "method": method, "params": params or {}},
            self.process.stdin,
        )

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                self.process.terminate()
        except Exception:
            pass


def _parse_servers(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        # Cursor-style { "serverName": { "command": ..., "args": [...] } }
        out = []
        for name, cfg in data.items():
            if isinstance(cfg, dict) and cfg.get("command"):
                out.append(
                    {
                        "name": name,
                        "command": cfg["command"],
                        "args": cfg.get("args") or [],
                        "env": cfg.get("env") or {},
                    }
                )
        return out
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict) and x.get("command")]
    return []


def start_server(cfg: dict[str, Any]) -> McpServerProc:
    name = cfg.get("name") or "mcp"
    command = cfg["command"]
    args = list(cfg.get("args") or [])
    env = os.environ.copy()
    for k, v in (cfg.get("env") or {}).items():
        env[str(k)] = str(v)
    # Resolve relative script paths from project root
    resolved_args = []
    for a in args:
        p = Path(a)
        if not p.is_absolute() and (ROOT_DIR / a).exists():
            resolved_args.append(str(ROOT_DIR / a))
        else:
            resolved_args.append(a)

    proc = subprocess.Popen(
        [command, *resolved_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(ROOT_DIR),
        env=env,
        bufsize=0,
    )
    server = McpServerProc(name=name, process=proc)
    # initialize handshake
    result = server.request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "atlas", "version": "0.1.0"},
        },
    )
    server.notify("notifications/initialized")
    _ = result
    return server


def mcp_tools_to_openai_specs(
    server_name: str, tools: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    specs = []
    for t in tools:
        name = t.get("name")
        if not name:
            continue
        # Prefix to avoid colliding with built-in tools
        full = f"mcp__{server_name}__{name}"
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": full,
                    "description": f"[MCP:{server_name}] {t.get('description') or name}",
                    "parameters": t.get("inputSchema")
                    or {"type": "object", "properties": {}},
                },
            }
        )
    return specs


def make_mcp_handler(server: McpServerProc, tool_name: str):
    async def _handler(**kwargs: Any) -> str:
        def _call() -> str:
            result = server.request(
                "tools/call",
                {"name": tool_name, "arguments": kwargs or {}},
            )
            contents = result.get("content") or []
            texts = []
            for c in contents:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text") or "")
                else:
                    texts.append(json.dumps(c, ensure_ascii=False))
            text = "\n".join(texts).strip() or json.dumps(result, ensure_ascii=False)
            if result.get("isError"):
                return json.dumps({"error": text}, ensure_ascii=False)
            return text

        return await asyncio.to_thread(_call)

    return _handler


_SERVERS: list[McpServerProc] = []


def load_mcp_into_tools(settings: Any) -> dict[str, Any]:
    """
    Start configured MCP servers and register their tools into TOOL_SPECS / TOOL_HANDLERS.
    Returns status dict.
    """
    global _loaded
    with _lock:
        if _loaded:
            return {"enabled": True, "loaded": True, "servers": [s.name for s in _SERVERS]}

        enabled = str(getattr(settings, "mcp_enabled", False)).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not enabled:
            _loaded = True
            return {"enabled": False, "servers": [], "tools": 0}

        from app.tools import TOOL_HANDLERS, TOOL_SPECS

        cfgs = _parse_servers(getattr(settings, "mcp_servers", "") or "")
        added = 0
        errors: list[str] = []
        for cfg in cfgs:
            name = cfg.get("name") or f"srv{len(_SERVERS)}"
            cfg = {**cfg, "name": name}
            try:
                server = start_server(cfg)
                tools = (server.request("tools/list") or {}).get("tools") or []
                specs = mcp_tools_to_openai_specs(name, tools)
                for spec, tool in zip(specs, tools):
                    full_name = spec["function"]["name"]
                    short = tool.get("name")
                    TOOL_SPECS.append(spec)
                    TOOL_HANDLERS[full_name] = make_mcp_handler(server, short)
                    added += 1
                _SERVERS.append(server)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")

        _loaded = True
        return {
            "enabled": True,
            "loaded": True,
            "servers": [s.name for s in _SERVERS],
            "tools": added,
            "errors": errors,
        }


def mcp_status(settings: Any) -> dict[str, Any]:
    enabled = str(getattr(settings, "mcp_enabled", False)).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return {
        "enabled": enabled,
        "loaded": _loaded,
        "servers": [s.name for s in _SERVERS],
        "server_count": len(_SERVERS),
    }
