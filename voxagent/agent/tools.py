from __future__ import annotations

import json
from typing import TYPE_CHECKING

from livekit.agents import llm

if TYPE_CHECKING:
    from voxagent.knowledge.engine import KnowledgeEngine


def create_knowledge_tool(engine: KnowledgeEngine) -> llm.FunctionTool:
    """Create an LLM-callable tool that searches the knowledge base."""

    async def search_knowledge(query: str, top_k: int = 5) -> str:
        results = engine.search(query, top_k=top_k)
        if not results:
            return "No relevant information found in the knowledge base."

        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(
                f"[{i}] (score: {result.score:.3f}) "
                f"Source: {result.chunk.source_url}\n"
                f"Section: {result.chunk.section_path}\n"
                f"{result.chunk.text}"
            )
        return "\n\n".join(formatted)

    return llm.FunctionTool(
        name="search_knowledge",
        description=(
            "Search the knowledge base for information relevant to the user's question. "
            "Use this tool when the user asks about products, services, pricing, policies, "
            "or any topic that may be covered in the indexed content."
        ),
        parameters=json.dumps({
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant information",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        }),
        callable=search_knowledge,
    )
