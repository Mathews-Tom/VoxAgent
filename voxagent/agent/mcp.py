from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from livekit.agents import llm

    from voxagent.models import MCPServerConfig

logger = logging.getLogger(__name__)


async def discover_mcp_tools(server: MCPServerConfig) -> list[dict[str, object]]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if server.api_key:
        headers["Authorization"] = f"Bearer {server.api_key}"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            server.url,
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    result = data.get("result", {})
    tools: list[dict[str, object]] = result.get("tools", [])
    return tools


def _build_mcp_caller(
    server: MCPServerConfig,
    tool_name: str,
) -> object:
    async def call_mcp_tool(**kwargs: object) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                server.url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": kwargs},
                    "id": 1,
                },
                headers=headers,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        result = data.get("result", {})
        content_list = result.get("content", [])
        texts = [c.get("text", "") for c in content_list if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(result)

    return call_mcp_tool


async def load_mcp_tools(servers: list[MCPServerConfig]) -> list[llm.FunctionTool]:
    from livekit.agents import llm as llm_mod

    tools: list[llm_mod.FunctionTool] = []

    for server in servers:
        discovered = await discover_mcp_tools(server)
        for tool_def in discovered:
            name = str(tool_def.get("name", ""))
            description = str(tool_def.get("description", ""))
            input_schema = tool_def.get("inputSchema", {"type": "object", "properties": {}})

            callable_fn = _build_mcp_caller(server, name)

            tools.append(
                llm_mod.FunctionTool(
                    name=f"mcp_{server.name}_{name}",
                    description=f"[{server.name}] {description}",
                    parameters=json.dumps(input_schema),
                    callable=callable_fn,
                )
            )

        logger.info(
            "Loaded %d tools from MCP server %s (%s)",
            len(discovered),
            server.name,
            server.url,
        )

    return tools
