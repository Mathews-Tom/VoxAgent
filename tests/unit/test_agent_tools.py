from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class _FakeResult:
    def __init__(self, score: float, source: str, section: str, text: str) -> None:
        self.score = score
        self.chunk = MagicMock()
        self.chunk.source_url = source
        self.chunk.section_path = section
        self.chunk.text = text


class TestCreateKnowledgeTool:
    @patch("voxagent.agent.tools.llm.FunctionTool")
    def test_tool_name(self, mock_ft: MagicMock) -> None:
        from voxagent.agent.tools import create_knowledge_tool

        mock_ft.return_value = MagicMock()
        engine = MagicMock()
        create_knowledge_tool(engine)
        call_kwargs = mock_ft.call_args.kwargs
        assert call_kwargs["name"] == "search_knowledge"

    @patch("voxagent.agent.tools.llm.FunctionTool")
    def test_parameters_schema_valid(self, mock_ft: MagicMock) -> None:
        from voxagent.agent.tools import create_knowledge_tool

        mock_ft.return_value = MagicMock()
        engine = MagicMock()
        create_knowledge_tool(engine)
        schema = json.loads(mock_ft.call_args.kwargs["parameters"])
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "query" in schema["required"]

    @patch("voxagent.agent.tools.llm.FunctionTool")
    @pytest.mark.asyncio
    async def test_search_calls_engine(self, mock_ft: MagicMock) -> None:
        from voxagent.agent.tools import create_knowledge_tool

        mock_ft.return_value = MagicMock()
        engine = MagicMock()
        engine.search.return_value = [_FakeResult(0.95, "doc.md", "Intro", "Hello")]
        create_knowledge_tool(engine)
        # Get the callable passed to FunctionTool
        search_fn = mock_ft.call_args.kwargs["callable"]
        result = await search_fn("test query")
        engine.search.assert_called_once_with("test query", top_k=5)
        assert "0.950" in result
        assert "doc.md" in result

    @patch("voxagent.agent.tools.llm.FunctionTool")
    @pytest.mark.asyncio
    async def test_empty_results(self, mock_ft: MagicMock) -> None:
        from voxagent.agent.tools import create_knowledge_tool

        mock_ft.return_value = MagicMock()
        engine = MagicMock()
        engine.search.return_value = []
        create_knowledge_tool(engine)
        search_fn = mock_ft.call_args.kwargs["callable"]
        result = await search_fn("nothing")
        assert result == "No relevant information found in the knowledge base."

    @patch("voxagent.agent.tools.llm.FunctionTool")
    @pytest.mark.asyncio
    async def test_formats_multiple_results(self, mock_ft: MagicMock) -> None:
        from voxagent.agent.tools import create_knowledge_tool

        mock_ft.return_value = MagicMock()
        engine = MagicMock()
        engine.search.return_value = [
            _FakeResult(0.9, "a.md", "S1", "text1"),
            _FakeResult(0.8, "b.md", "S2", "text2"),
        ]
        create_knowledge_tool(engine)
        search_fn = mock_ft.call_args.kwargs["callable"]
        result = await search_fn("query")
        assert "[1]" in result
        assert "[2]" in result
        assert "a.md" in result
        assert "b.md" in result
