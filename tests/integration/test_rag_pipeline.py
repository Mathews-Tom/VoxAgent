from __future__ import annotations

import hashlib

import pytest

from voxagent.knowledge.chunker import chunk_pages
from voxagent.knowledge.engine import KnowledgeEngine
from voxagent.knowledge.ingest import PageContent

pytestmark = pytest.mark.integration


def _make_page(text: str, url: str) -> PageContent:
    return PageContent(
        url=url,
        title=url.split("/")[-1],
        html="",
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


@pytest.fixture
def indexed_engine(tmp_path: pytest.TempPathFactory) -> KnowledgeEngine:
    """Build a knowledge engine with sample website content."""
    pages = [
        _make_page(
            "# Pricing\n\n"
            "Our starter plan costs $29/month and includes 1000 conversations. "
            "The professional plan is $99/month with unlimited conversations and "
            "priority support. Enterprise plans are custom-priced.",
            url="https://acme.com/pricing",
        ),
        _make_page(
            "# About Us\n\n"
            "Acme Corp was founded in 2020. We specialize in AI-powered customer "
            "service solutions. Our headquarters is in San Francisco, California.",
            url="https://acme.com/about",
        ),
        _make_page(
            "# Features\n\n"
            "## Voice AI\n"
            "Our voice agent speaks naturally and handles complex conversations. "
            "It supports English, Hindi, Tamil, and 10 other languages.\n\n"
            "## Knowledge Base\n"
            "Upload your website content and documents. The agent learns your "
            "products and services automatically.",
            url="https://acme.com/features",
        ),
        _make_page(
            "# FAQ\n\n"
            "## How do I get started?\n"
            "Sign up on our website and follow the setup wizard. You can have "
            "your first voice agent running in under 5 minutes.\n\n"
            "## What languages are supported?\n"
            "We support English, Hindi, Tamil, Telugu, Kannada, Malayalam, "
            "Bengali, and more.",
            url="https://acme.com/faq",
        ),
    ]

    chunks = chunk_pages(pages)
    engine = KnowledgeEngine(str(tmp_path))
    engine.build_index(chunks)
    engine.update_hash_map(pages)
    return engine


class TestRAGRetrieval:
    def test_pricing_query_returns_pricing_content(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("how much does it cost")
        assert len(results) >= 1
        top = results[0]
        assert "pricing" in top.chunk.source_url or "$" in top.chunk.text

    def test_language_query_returns_language_content(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("what languages do you support")
        assert len(results) >= 1
        texts = " ".join(r.chunk.text for r in results[:3])
        assert "Hindi" in texts or "languages" in texts.lower()

    def test_about_query_returns_company_info(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("who founded the company")
        assert len(results) >= 1
        texts = " ".join(r.chunk.text for r in results[:3])
        assert "2020" in texts or "Acme" in texts

    def test_search_results_carry_source_urls(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("pricing plans")
        for r in results:
            assert r.chunk.source_url.startswith("https://acme.com/")

    def test_search_results_carry_section_paths(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("voice agent features")
        section_paths = [r.chunk.section_path for r in results]
        # At least one result should have a non-empty section path
        assert any(sp for sp in section_paths)


class TestRAGGrounding:
    def test_grounded_answer_contains_factual_content(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        """Verify that search results contain actual facts from indexed content."""
        results = indexed_engine.search("starter plan price", top_k=3)
        all_text = " ".join(r.chunk.text for r in results)
        assert "$29" in all_text

    def test_multiple_results_from_different_sources(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        results = indexed_engine.search("getting started with voice agent", top_k=5)
        sources = {r.chunk.source_url for r in results}
        assert len(sources) >= 2


class TestIncrementalReindex:
    def test_unchanged_content_not_reindexed(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        pages = [
            _make_page(
                "# Pricing\n\n"
                "Our starter plan costs $29/month and includes 1000 conversations. "
                "The professional plan is $99/month with unlimited conversations and "
                "priority support. Enterprise plans are custom-priced.",
                url="https://acme.com/pricing",
            ),
        ]
        changed = indexed_engine.needs_reindex(pages)
        assert len(changed) == 0

    def test_modified_content_detected_for_reindex(
        self, indexed_engine: KnowledgeEngine
    ) -> None:
        pages = [
            _make_page(
                "# Pricing\n\nNew pricing: $49/month for all plans.",
                url="https://acme.com/pricing",
            ),
        ]
        changed = indexed_engine.needs_reindex(pages)
        assert len(changed) == 1
        assert changed[0].url == "https://acme.com/pricing"
