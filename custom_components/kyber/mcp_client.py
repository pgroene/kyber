"""MCP client — lets the Kyber AI loop call external MCP servers as tools.

Usage
-----
1. Configure one or more MCP servers in Kyber's Developer settings as a JSON
   list, e.g.::

       [{"name": "ha", "url": "http://localhost:8123/api/mcp_server",
         "token": "ey..."}]

2. Enable the "Use MCP in chat" feature flag.

3. At the start of each chat request, :class:`MCPClientManager` calls
   ``tools/list`` on every configured server and returns a merged dict of
   available tools.  Tool names are prefixed with ``mcp_<server_name>__`` to
   avoid collisions with Kyber's built-in tools.

4. The AI loop injects a compact tool-description block into the system prompt
   so the model knows what external tools exist.

5. When the model emits a ``[TOOL_CALL:{"name":"mcp_ha__HassTurnOn",...}]``
   the loop routes the call here, which proxies it to the right server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Cache TTL — re-fetch tool list at most once per this many seconds per server
_TOOL_LIST_CACHE_TTL = 60

# Timeout for MCP server requests (seconds)
_MCP_TIMEOUT = 15


def _prefix(server_name: str, tool_name: str) -> str:
    """Return the prefixed tool name used inside the AI loop."""
    # Use double underscore as separator so it's easy to split
    return f"mcp_{server_name}__{tool_name}"


def _unprefix(prefixed: str) -> tuple[str, str] | None:
    """Split 'mcp_ha__HassTurnOn' → ('ha', 'HassTurnOn'). Returns None if not an MCP tool."""
    if not prefixed.startswith("mcp_"):
        return None
    rest = prefixed[4:]  # strip 'mcp_'
    if "__" not in rest:
        return None
    server_name, tool_name = rest.split("__", 1)
    return server_name, tool_name


class MCPClientManager:
    """Discovers and proxies tools from external MCP servers."""

    def __init__(self, servers: list[dict[str, str]]) -> None:
        """
        Parameters
        ----------
        servers:
            List of dicts with keys ``name``, ``url``, and optionally ``token``.
        """
        self._servers: list[dict[str, str]] = servers
        # Cache: server_name → (timestamp, tools_dict)
        self._cache: dict[str, tuple[float, dict[str, dict]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_get_tools(self) -> dict[str, dict]:
        """Return merged dict of all available MCP tools (prefixed names → schema)."""
        all_tools: dict[str, dict] = {}
        tasks = [self._fetch_server_tools(s) for s in self._servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for srv, result in zip(self._servers, results):
            if isinstance(result, Exception):
                _LOGGER.warning("MCP client: failed to fetch tools from '%s': %s", srv.get("name"), result)
                continue
            all_tools.update(result)
        return all_tools

    async def async_call_tool(self, prefixed_name: str, args: dict) -> str:
        """Call a tool on its server and return the result as a JSON string."""
        parsed = _unprefix(prefixed_name)
        if not parsed:
            return json.dumps({"error": f"Not an MCP tool: {prefixed_name}"})
        server_name, tool_name = parsed

        server = next((s for s in self._servers if s.get("name") == server_name), None)
        if not server:
            return json.dumps({"error": f"MCP server '{server_name}' not configured"})

        url = server.get("url", "").rstrip("/")
        token = server.get("token", "")

        rpc = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        }

        try:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            timeout = aiohttp.ClientTimeout(total=_MCP_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=rpc, headers=headers) as resp:
                    if resp.status >= 400:
                        return json.dumps({"error": f"MCP server '{server_name}' returned HTTP {resp.status}"})
                    data = await resp.json(content_type=None)

            if "error" in data:
                return json.dumps({"error": data["error"].get("message", "unknown error")})

            result = data.get("result", {})
            # MCP returns content as list of {type, text} blocks
            content = result.get("content", [])
            if content and isinstance(content, list):
                text = "\n".join(
                    c.get("text", "") for c in content if c.get("type") == "text"
                )
                if result.get("isError"):
                    return json.dumps({"error": text})
                # Try to return parsed JSON if the text is valid JSON
                try:
                    return text if text.startswith("{") or text.startswith("[") else json.dumps({"result": text})
                except Exception:  # noqa: BLE001
                    return json.dumps({"result": text})
            return json.dumps(result)

        except asyncio.TimeoutError:
            return json.dumps({"error": f"MCP server '{server_name}' timed out after {_MCP_TIMEOUT}s"})
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MCP client: error calling '%s.%s': %s", server_name, tool_name, err)
            return json.dumps({"error": str(err)})

    def build_prompt_block(self, tools: dict[str, dict]) -> str:
        """Build a compact prompt section describing the available MCP tools."""
        if not tools:
            return ""
        lines = ["## External MCP Tools", ""]
        lines.append(
            "You have access to these additional tools from external MCP servers. "
            "Call them with `[TOOL_CALL:{\"name\": \"<tool_name>\", ...}]` like any other tool."
        )
        lines.append("")
        for prefixed_name, schema in tools.items():
            desc = schema.get("description", "No description")
            # Compact parameter summary
            props = (schema.get("inputSchema") or {}).get("properties") or {}
            required = (schema.get("inputSchema") or {}).get("required") or []
            if props:
                param_strs = []
                for pname, pschema in props.items():
                    req = "*" if pname in required else ""
                    pdesc = pschema.get("description", "")
                    param_strs.append(f"{pname}{req}: {pdesc}" if pdesc else pname + req)
                params_summary = ", ".join(param_strs[:6])  # cap at 6 to keep prompt small
                lines.append(f"- **{prefixed_name}**: {desc} | params: {params_summary}")
            else:
                lines.append(f"- **{prefixed_name}**: {desc}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_server_tools(self, server: dict[str, str]) -> dict[str, dict]:
        """Fetch tool list from one server, using TTL cache."""
        name = server.get("name", "unnamed")
        now = time.monotonic()

        cached = self._cache.get(name)
        if cached and (now - cached[0]) < _TOOL_LIST_CACHE_TTL:
            return cached[1]

        url = server.get("url", "").rstrip("/")
        token = server.get("token", "")

        # MCP servers need an initialize handshake before tools/list
        # For simplicity we skip initialize and go straight to tools/list
        # (most servers accept tools/list without prior initialize)
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        timeout = aiohttp.ClientTimeout(total=_MCP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=rpc, headers=headers) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}")
                data = await resp.json(content_type=None)

        if "error" in data:
            raise RuntimeError(data["error"].get("message", "unknown"))

        raw_tools: list[dict] = data.get("result", {}).get("tools", [])
        prefixed: dict[str, dict] = {}
        for tool in raw_tools:
            tool_name = tool.get("name", "")
            if not tool_name:
                continue
            prefixed[_prefix(name, tool_name)] = tool

        self._cache[name] = (now, prefixed)
        _LOGGER.debug("MCP client: discovered %d tools from '%s'", len(prefixed), name)
        return prefixed


def parse_servers_config(raw: str) -> list[dict[str, str]]:
    """Parse the JSON server list config string. Returns [] on error."""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            _LOGGER.warning("MCP client: mcp_client_servers must be a JSON array")
            return []
        servers = []
        for entry in data:
            if not isinstance(entry, dict) or not entry.get("name") or not entry.get("url"):
                continue
            servers.append({
                "name": str(entry["name"]),
                "url": str(entry["url"]),
                "token": str(entry.get("token", "")),
            })
        return servers
    except (json.JSONDecodeError, TypeError) as err:
        _LOGGER.warning("MCP client: failed to parse mcp_client_servers: %s", err)
        return []


def is_mcp_tool(name: str) -> bool:
    """Return True if tool name is an MCP client tool."""
    return name.startswith("mcp_") and "__" in name[4:]
