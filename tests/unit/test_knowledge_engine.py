from __future__ import annotations

import hashlib
import json
import os

import pytest

from voxagent.knowledge.chunker import Chunk
from voxagent.knowledge.engine import KnowledgeEngine, SearchResult
from voxagent.knowledge.ingest import PageContent

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(
    text: str,
    source_url: str = "https://example.com/page",
    section_path: str = "",
    heading_chain: list[str] | None = None,
    chunk_index: int = 0,
) -> Chunk:
    return Chunk(
        text=text,
        source_url=source_url,
        section_path=section_path,
        heading_chain=heading_chain or [],
        chunk_index=chunk_index,
    )


def _make_page(text: str, url: str = "https://example.com/page") -> PageContent:
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return PageContent(url=url, title="Test", html="", text=text, content_hash=content_hash)


# ---------------------------------------------------------------------------
# build_index → search returns relevant results
# ---------------------------------------------------------------------------


def test_build_and_search_returns_relevant_result(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [
        _make_chunk("Python is a high-level programming language.", chunk_index=0),
        _make_chunk("The Eiffel Tower is located in Paris, France.", chunk_index=1),
        _make_chunk("Machine learning uses statistical methods.", chunk_index=2),
    ]
    engine.build_index(chunks)

    results = engine.search("programming language Python")

    assert len(results) >= 1
    top = results[0]
    assert isinstance(top, SearchResult)
    assert "Python" in top.chunk.text


def test_search_returns_list_of_search_result_instances(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk("Some content about databases.", chunk_index=0)]
    engine.build_index(chunks)

    results = engine.search("database")

    assert isinstance(results, list)
    assert all(isinstance(r, SearchResult) for r in results)


# ---------------------------------------------------------------------------
# RRF fusion: chunks in both rankings get higher scores
# ---------------------------------------------------------------------------


def test_rrf_fusion_boosts_dual_ranked_chunk(tmp_path: pytest.TempPathFactory) -> None:
    # "alpha beta gamma" should rank high in both BM25 and FAISS for the query
    dominant_text = "alpha beta gamma delta epsilon zeta"
    # Noise chunks have no overlap with query
    chunks = [
        _make_chunk(dominant_text, chunk_index=0),
        _make_chunk("completely unrelated foobar baz qux", chunk_index=1),
        _make_chunk("another irrelevant chunk with xyz terms", chunk_index=2),
        _make_chunk("more noise with numbers 123 456 789", chunk_index=3),
    ]
    engine = KnowledgeEngine(str(tmp_path))
    engine.build_index(chunks)

    results = engine.search("alpha beta gamma", top_k=4)

    # The dominant chunk must be ranked first by RRF
    assert results[0].chunk.text == dominant_text


def test_rrf_score_higher_when_in_both_rankings(tmp_path: pytest.TempPathFactory) -> None:
    # Manually verify: a chunk that appears in both BM25 and FAISS rankings
    # must have score > 1 / (60 + 1) (the minimum score from one ranking)
    chunks = [
        _make_chunk("neural network deep learning model", chunk_index=0),
        _make_chunk("completely unrelated noise content here", chunk_index=1),
        _make_chunk("more noise about cooking recipes and food", chunk_index=2),
    ]
    engine = KnowledgeEngine(str(tmp_path))
    engine.build_index(chunks)

    results = engine.search("neural network deep learning", top_k=3)

    top = results[0]
    # Score from both BM25 rank 1 and FAISS rank 1: 1/61 + 1/61 ≈ 0.0328
    # Score from only one ranking at rank 1: 1/61 ≈ 0.0164
    single_rank_score = 1.0 / (60 + 1)
    assert top.score > single_rank_score


# ---------------------------------------------------------------------------
# search with top_k=1 returns exactly 1 result
# ---------------------------------------------------------------------------


def test_search_top_k_1_returns_exactly_one(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [
        _make_chunk("First chunk content.", chunk_index=0),
        _make_chunk("Second chunk content.", chunk_index=1),
        _make_chunk("Third chunk content.", chunk_index=2),
    ]
    engine.build_index(chunks)

    results = engine.search("chunk content", top_k=1)

    assert len(results) == 1


def test_search_top_k_respected(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk(f"Chunk {i} with some text.", chunk_index=i) for i in range(10)]
    engine.build_index(chunks)

    for k in (1, 3, 5, 7):
        results = engine.search("chunk text", top_k=k)
        assert len(results) <= k


# ---------------------------------------------------------------------------
# search on empty engine returns empty list
# ---------------------------------------------------------------------------


def test_search_on_empty_engine_returns_empty(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    results = engine.search("any query")
    assert results == []


def test_search_on_empty_engine_does_not_raise(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    # Must return [] without raising RuntimeError
    results = engine.search("test query", top_k=5)
    assert isinstance(results, list)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# needs_reindex: returns all pages on first index
# ---------------------------------------------------------------------------


def test_needs_reindex_returns_all_pages_on_fresh_engine(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    pages = [
        _make_page("Content A", url="https://example.com/a"),
        _make_page("Content B", url="https://example.com/b"),
    ]
    changed = engine.needs_reindex(pages)

    assert len(changed) == len(pages)
    assert set(p.url for p in changed) == set(p.url for p in pages)


def test_needs_reindex_returns_only_changed_after_update(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    page_a = _make_page("Content A", url="https://example.com/a")
    page_b = _make_page("Content B", url="https://example.com/b")

    # Record both pages as indexed
    engine.update_hash_map([page_a, page_b])

    # page_b's content changes
    page_b_updated = _make_page("Content B modified", url="https://example.com/b")

    changed = engine.needs_reindex([page_a, page_b_updated])

    assert len(changed) == 1
    assert changed[0].url == "https://example.com/b"


def test_needs_reindex_returns_empty_when_nothing_changed(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    pages = [
        _make_page("Content A", url="https://example.com/a"),
        _make_page("Content B", url="https://example.com/b"),
    ]
    engine.update_hash_map(pages)

    changed = engine.needs_reindex(pages)

    assert changed == []


# ---------------------------------------------------------------------------
# update_hash_map persists hashes
# ---------------------------------------------------------------------------


def test_update_hash_map_persists_to_disk(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    page = _make_page("Some content", url="https://example.com/test")
    engine.update_hash_map([page])

    hash_map_path = os.path.join(str(tmp_path), "hash_map.json")
    assert os.path.exists(hash_map_path)

    with open(hash_map_path, encoding="utf-8") as fh:
        stored = json.load(fh)

    assert stored["https://example.com/test"] == page.content_hash


def test_update_hash_map_survives_reload(tmp_path: pytest.TempPathFactory) -> None:
    storage = str(tmp_path)
    page = _make_page("Persistent content", url="https://example.com/persist")

    engine_1 = KnowledgeEngine(storage)
    engine_1.update_hash_map([page])

    # Create a second engine pointing at the same directory and build chunks
    chunks = [_make_chunk("Persistent content", source_url=page.url, chunk_index=0)]
    engine_2 = KnowledgeEngine(storage)
    engine_2.build_index(chunks)
    engine_2.load_index()

    changed = engine_2.needs_reindex([page])
    assert changed == []


# ---------------------------------------------------------------------------
# Index persistence: build_index → load_index → search still works
# ---------------------------------------------------------------------------


def test_load_index_and_search_still_works(tmp_path: pytest.TempPathFactory) -> None:
    storage = str(tmp_path)

    engine_write = KnowledgeEngine(storage)
    chunks = [
        _make_chunk("Quantum computing leverages quantum mechanics.", chunk_index=0),
        _make_chunk("Classical computing uses binary logic gates.", chunk_index=1),
        _make_chunk("The weather today is sunny and warm.", chunk_index=2),
    ]
    engine_write.build_index(chunks)

    engine_read = KnowledgeEngine(storage)
    engine_read.load_index()

    results = engine_read.search("quantum computing mechanics")

    assert len(results) >= 1
    assert "quantum" in results[0].chunk.text.lower()


def test_load_index_preserves_chunk_fields(tmp_path: pytest.TempPathFactory) -> None:
    storage = str(tmp_path)
    original = _make_chunk(
        "Specific test content for field preservation.",
        source_url="https://example.com/fields",
        section_path="Doc > Section",
        heading_chain=["Doc", "Section"],
        chunk_index=3,
    )

    engine_write = KnowledgeEngine(storage)
    engine_write.build_index([original])

    engine_read = KnowledgeEngine(storage)
    engine_read.load_index()

    results = engine_read.search("specific test content", top_k=1)

    assert len(results) == 1
    loaded_chunk = results[0].chunk
    assert loaded_chunk.source_url == "https://example.com/fields"
    assert loaded_chunk.section_path == "Doc > Section"
    assert loaded_chunk.heading_chain == ["Doc", "Section"]
    assert loaded_chunk.chunk_index == 3


def test_index_files_created_on_build(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    engine.build_index([_make_chunk("Test content.", chunk_index=0)])

    expected_files = {"chunks.json", "bm25_corpus.json", "faiss.index", "hash_map.json"}
    created = set(os.listdir(str(tmp_path)))
    assert expected_files.issubset(created)


# ---------------------------------------------------------------------------
# SearchResult has bm25_rank and faiss_rank populated
# ---------------------------------------------------------------------------


def test_search_result_has_bm25_and_faiss_rank(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [
        _make_chunk("Information retrieval systems and search engines.", chunk_index=0),
        _make_chunk("Database query optimisation techniques.", chunk_index=1),
        _make_chunk("Unrelated content about cooking pasta.", chunk_index=2),
    ]
    engine.build_index(chunks)

    results = engine.search("information retrieval search", top_k=3)

    assert len(results) >= 1
    top = results[0]
    # The top result must appear in at least one of the two rankings
    assert top.bm25_rank is not None or top.faiss_rank is not None


def test_search_result_ranks_are_positive_integers(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk(f"Document about topic {i}.", chunk_index=i) for i in range(5)]
    engine.build_index(chunks)

    results = engine.search("document topic", top_k=5)

    for r in results:
        if r.bm25_rank is not None:
            assert r.bm25_rank >= 1
        if r.faiss_rank is not None:
            assert r.faiss_rank >= 1


def test_search_result_score_is_positive(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk("Sample document with terms.", chunk_index=0)]
    engine.build_index(chunks)

    results = engine.search("sample document", top_k=1)

    assert results[0].score > 0.0


def test_search_results_ordered_by_descending_score(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk(f"Topic content item {i}.", chunk_index=i) for i in range(6)]
    engine.build_index(chunks)

    results = engine.search("topic content", top_k=6)

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_chunk_search(tmp_path: pytest.TempPathFactory) -> None:
    engine = KnowledgeEngine(str(tmp_path))
    chunk = _make_chunk("Lonely single chunk in the index.", chunk_index=0)
    engine.build_index([chunk])

    results = engine.search("lonely single chunk", top_k=1)

    assert len(results) == 1
    assert results[0].chunk.text == chunk.text


def test_search_query_with_no_matching_terms_still_returns_results(
    tmp_path: pytest.TempPathFactory,
) -> None:
    # FAISS (semantic similarity) should still return results even with no BM25 hits
    engine = KnowledgeEngine(str(tmp_path))
    chunks = [_make_chunk("Python programming language tutorial.", chunk_index=0)]
    engine.build_index(chunks)

    # Query has no lexical overlap but FAISS may still find something
    results = engine.search("zzzznotaword", top_k=1)
    # At minimum, FAISS must return the single chunk; BM25 may score 0
    assert len(results) == 1
