from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voxagent.models import MCPServerConfig
from voxagent.agent.mcp import discover_mcp_tools, _build_mcp_caller


@pytest.fixture
def mcp_server() -> MCPServerConfig:
    return MCPServerConfig(
        name="crm",
        url="http://localhost:9000/mcp",
        api_key=None,
    )


@pytest.fixture
def mcp_server_with_key() -> MCPServerConfig:
    return MCPServerConfig(
        name="crm",
        url="http://localhost:9000/mcp",
        api_key="secret-key-123",
    )


@pytest.fixture
def tools_list_response() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "lookup_customer",
                    "description": "Look up a customer by email",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"email": {"type": "string"}},
                    },
                },
                {
                    "name": "create_ticket",
                    "description": "Create a support ticket",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"subject": {"type": "string"}},
                    },
                },
            ]
        },
    }


def _make_mock_client(response_json: dict) -> AsyncMock:
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestDiscoverMcpTools:
    @pytest.mark.asyncio
    async def test_returns_tool_list(
        self, mcp_server: MCPServerConfig, tools_list_response: dict
    ) -> None:
        mock_client = _make_mock_client(tools_list_response)
        with patch("voxagent.agent.mcp.httpx.AsyncClient", return_value=mock_client):
            tools = await discover_mcp_tools(mcp_server)
        assert len(tools) == 2
        assert tools[0]["name"] == "lookup_customer"
        assert tools[1]["name"] == "create_ticket"

    @pytest.mark.asyncio
    async def test_sends_auth_header_when_api_key_present(
        self, mcp_server_with_key: MCPServerConfig, tools_list_response: dict
    ) -> None:
        mock_client = _make_mock_client(tools_list_response)
        with patch("voxagent.agent.mcp.httpx.AsyncClient", return_value=mock_client):
            await discover_mcp_tools(mcp_server_with_key)
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-key-123"

    @pytest.mark.asyncio
    async def test_empty_tools_when_server_returns_none(
        self, mcp_server: MCPServerConfig
    ) -> None:
        empty_response = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        mock_client = _make_mock_client(empty_response)
        with patch("voxagent.agent.mcp.httpx.AsyncClient", return_value=mock_client):
            tools = await discover_mcp_tools(mcp_server)
        assert tools == []


class TestLoadMcpTools:
    @pytest.mark.asyncio
    async def test_creates_function_tool_instances_with_namespaced_names(
        self, mcp_server: MCPServerConfig, tools_list_response: dict
    ) -> None:
        mock_client = _make_mock_client(tools_list_response)
        mock_function_tool = MagicMock()

        mock_livekit_agents = MagicMock()
        mock_llm_mod = MagicMock()
        mock_llm_mod.FunctionTool = mock_function_tool
        mock_livekit_agents.llm = mock_llm_mod

        with (
            patch("voxagent.agent.mcp.httpx.AsyncClient", return_value=mock_client),
            patch.dict(
                "sys.modules",
                {
                    "livekit": MagicMock(),
                    "livekit.agents": mock_livekit_agents,
                    "livekit.agents.llm": mock_llm_mod,
                },
            ),
        ):
            import importlib
            import voxagent.agent.mcp as mcp_mod

            importlib.reload(mcp_mod)
            await mcp_mod.load_mcp_tools([mcp_server])

        assert mock_function_tool.call_count == 2
        first_call = mock_function_tool.call_args_list[0]
        assert first_call.kwargs["name"] == "mcp_crm_lookup_customer"
        assert "[crm]" in first_call.kwargs["description"]
        second_call = mock_function_tool.call_args_list[1]
        assert second_call.kwargs["name"] == "mcp_crm_create_ticket"


class TestMcpToolCaller:
    @pytest.mark.asyncio
    async def test_sends_correct_jsonrpc_payload(
        self, mcp_server: MCPServerConfig
    ) -> None:
        call_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "Customer found: Jane Doe"}]
            },
        }
        mock_client = _make_mock_client(call_response)

        caller = _build_mcp_caller(mcp_server, "lookup_customer")
        with patch("voxagent.agent.mcp.httpx.AsyncClient", return_value=mock_client):
            result = await caller(email="jane@example.com")

        assert result == "Customer found: Jane Doe"
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "lookup_customer"
        assert payload["params"]["arguments"] == {"email": "jane@example.com"}
