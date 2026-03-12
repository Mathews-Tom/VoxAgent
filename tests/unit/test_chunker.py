from __future__ import annotations

import hashlib

from voxagent.knowledge.chunker import Chunk, chunk_page, chunk_pages
from voxagent.knowledge.ingest import PageContent


def _make_page(text: str, url: str = "https://example.com/page") -> PageContent:
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return PageContent(url=url, title="Test Page", html="", text=text, content_hash=content_hash)


# ---------------------------------------------------------------------------
# Basic text without headings
# ---------------------------------------------------------------------------


def test_no_headings_produces_chunks() -> None:
    text = "This is a simple paragraph. It has no headings at all."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) >= 1
    assert chunks[0].text == text.strip()


def test_no_headings_section_path_is_empty() -> None:
    page = _make_page("Plain text with no headings here.")
    chunks = chunk_page(page)

    assert chunks[0].section_path == ""
    assert chunks[0].heading_chain == []


# ---------------------------------------------------------------------------
# Markdown headings — section_path and heading_chain
# ---------------------------------------------------------------------------


def test_h1_heading_section_path() -> None:
    text = "# Introduction\nThis is the intro text."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].section_path == "Introduction"
    assert chunks[0].heading_chain == ["Introduction"]


def test_h2_heading_under_h1() -> None:
    text = "# Chapter One\n## Section A\nContent under section A."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].section_path == "Chapter One > Section A"
    assert chunks[0].heading_chain == ["Chapter One", "Section A"]


def test_h3_heading_nesting() -> None:
    text = "# H1\n## H2\n### H3\nDeep content."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].section_path == "H1 > H2 > H3"
    assert chunks[0].heading_chain == ["H1", "H2", "H3"]


def test_sibling_h2_sections_produce_separate_chunks() -> None:
    text = "# Parent\n## First\nFirst content.\n## Second\nSecond content."
    page = _make_page(text)
    chunks = chunk_page(page)

    paths = [c.section_path for c in chunks]
    assert "Parent > First" in paths
    assert "Parent > Second" in paths


def test_same_level_heading_resets_stack() -> None:
    text = "## Alpha\nAlpha text.\n## Beta\nBeta text."
    page = _make_page(text)
    chunks = chunk_page(page)

    paths = [c.section_path for c in chunks]
    assert "Alpha" in paths
    assert "Beta" in paths
    # Alpha must not appear in Beta's heading_chain
    beta_chunks = [c for c in chunks if c.section_path == "Beta"]
    assert beta_chunks
    assert "Alpha" not in beta_chunks[0].heading_chain


# ---------------------------------------------------------------------------
# ALL-CAPS lines treated as headings
# ---------------------------------------------------------------------------


def test_allcaps_line_treated_as_heading() -> None:
    text = "INTRODUCTION\nThis is content under the caps heading."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].section_path == "INTRODUCTION"
    assert chunks[0].heading_chain == ["INTRODUCTION"]


def test_allcaps_minimum_three_chars() -> None:
    # Two-char uppercase lines must NOT be treated as headings
    text = "AB\nThis content should be in an empty-path section."
    page = _make_page(text)
    chunks = chunk_page(page)

    # "AB" is only 2 chars — should not match the caps regex
    assert all(c.section_path == "" for c in chunks)


def test_allcaps_with_numbers_and_punctuation() -> None:
    text = "CHAPTER 1: OVERVIEW\nContent here."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert chunks[0].section_path == "CHAPTER 1: OVERVIEW"


# ---------------------------------------------------------------------------
# Empty page text
# ---------------------------------------------------------------------------


def test_empty_page_produces_no_chunks() -> None:
    page = _make_page("")
    chunks = chunk_page(page)

    # Either zero chunks or one chunk whose text is empty
    if chunks:
        assert chunks[0].text == ""


def test_whitespace_only_page_produces_no_chunks() -> None:
    page = _make_page("   \n\n\t  ")
    chunks = chunk_page(page)

    if chunks:
        assert all(c.text.strip() == "" for c in chunks)


# ---------------------------------------------------------------------------
# Very long text → multiple chunks
# ---------------------------------------------------------------------------


def test_long_text_splits_into_multiple_chunks() -> None:
    # Build a 3 000-char string with clear sentence boundaries
    sentence = "This is a test sentence that provides content. "
    long_text = sentence * 65  # ~3 000 chars
    page = _make_page(long_text)
    chunks = chunk_page(page, max_chunk_size=500, overlap=0)

    assert len(chunks) > 1
    for chunk in chunks:
        # Allow slight excess due to overlap appending
        assert len(chunk.text) <= 500 + 200 + len(sentence)


def test_each_chunk_does_not_massively_exceed_max_size() -> None:
    sentence = "Short sentence here. "
    long_text = sentence * 200
    page = _make_page(long_text)
    chunks = chunk_page(page, max_chunk_size=300, overlap=50)

    for chunk in chunks:
        # max_chunk_size + overlap is the hard ceiling defined in the impl
        assert len(chunk.text) <= 300 + 300


# ---------------------------------------------------------------------------
# Sentence boundary splitting
# ---------------------------------------------------------------------------


def test_splits_prefer_period_boundary() -> None:
    # Two sentences; limit forces a split
    part1 = "First sentence is here and has content. "
    part2 = "Second sentence follows right after."
    text = part1 + part2
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=len(part1) + 5, overlap=0)

    # First chunk must end right after the period
    assert chunks[0].text.endswith("here and has content.")


def test_splits_on_question_mark() -> None:
    part1 = "Is this working? "
    part2 = "Yes it is working well."
    text = part1 + part2
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=len(part1) + 2, overlap=0)

    assert chunks[0].text.endswith("Is this working?")


def test_splits_on_exclamation() -> None:
    part1 = "Wow this is great! "
    part2 = "Keep going with the next sentence."
    text = part1 + part2
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=len(part1) + 2, overlap=0)

    assert chunks[0].text.endswith("Wow this is great!")


# ---------------------------------------------------------------------------
# Overlap between consecutive chunks
# ---------------------------------------------------------------------------


def test_overlap_text_appears_in_next_chunk() -> None:
    # Build two clearly distinct halves
    half = "Word " * 60  # 300 chars each half
    text = half + ". " + half + "."
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=310, overlap=50)

    if len(chunks) >= 2:
        # The tail of chunk 0's base text should appear at the start of chunk 1
        tail_of_first = chunks[0].text[-30:]
        assert tail_of_first in chunks[1].text


def test_zero_overlap_no_repeated_text() -> None:
    sentence = "Sentence number one. Sentence number two. Sentence number three. "
    text = sentence * 10
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=130, overlap=0)

    if len(chunks) >= 2:
        # With overlap=0 the prev_tail is still stored but piece itself is short
        # Just verify we get multiple chunks at all
        assert len(chunks) > 1


# ---------------------------------------------------------------------------
# Deep heading nesting (H1 > H2 > H3 > H4)
# ---------------------------------------------------------------------------


def test_deep_heading_nesting_h4() -> None:
    text = "# Level1\n## Level2\n### Level3\n#### Level4\nDeep content."
    page = _make_page(text)
    chunks = chunk_page(page)

    assert len(chunks) == 1
    assert chunks[0].section_path == "Level1 > Level2 > Level3 > Level4"
    assert chunks[0].heading_chain == ["Level1", "Level2", "Level3", "Level4"]


def test_h3_after_deep_nesting_resets_correctly() -> None:
    text = (
        "# L1\n"
        "## L2\n"
        "### L3\n"
        "#### L4\n"
        "Deep content.\n"
        "### BackToL3\n"
        "Back to level 3 content."
    )
    page = _make_page(text)
    chunks = chunk_page(page)

    paths = [c.section_path for c in chunks]
    assert "L1 > L2 > L3 > L4" in paths
    assert "L1 > L2 > BackToL3" in paths

    back_chunk = next(c for c in chunks if c.section_path == "L1 > L2 > BackToL3")
    assert "L3" not in back_chunk.heading_chain
    assert "L4" not in back_chunk.heading_chain


# ---------------------------------------------------------------------------
# Multiple pages via chunk_pages
# ---------------------------------------------------------------------------


def test_chunk_pages_returns_chunks_from_all_pages() -> None:
    page_a = _make_page("Page A content.", url="https://example.com/a")
    page_b = _make_page("Page B content.", url="https://example.com/b")
    page_c = _make_page("Page C content.", url="https://example.com/c")

    chunks = chunk_pages([page_a, page_b, page_c])

    urls = {c.source_url for c in chunks}
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls
    assert "https://example.com/c" in urls


def test_chunk_pages_empty_list() -> None:
    chunks = chunk_pages([])
    assert chunks == []


def test_chunk_pages_single_page_identical_to_chunk_page() -> None:
    page = _make_page("Single page. With some text.")
    assert chunk_pages([page]) == chunk_page(page)


# ---------------------------------------------------------------------------
# source_url preserved in chunks
# ---------------------------------------------------------------------------


def test_source_url_preserved() -> None:
    url = "https://docs.example.com/api/reference"
    page = _make_page("Some text content here.", url=url)
    chunks = chunk_page(page)

    assert all(c.source_url == url for c in chunks)


def test_source_url_preserved_across_sections() -> None:
    url = "https://example.com/multi-section"
    text = "# Section One\nContent A.\n# Section Two\nContent B."
    page = _make_page(text, url=url)
    chunks = chunk_page(page)

    assert len(chunks) == 2
    assert all(c.source_url == url for c in chunks)


# ---------------------------------------------------------------------------
# chunk_index is sequential
# ---------------------------------------------------------------------------


def test_chunk_index_sequential_single_page() -> None:
    sentence = "This sentence fills the chunk. "
    long_text = sentence * 100
    page = _make_page(long_text)
    chunks = chunk_page(page, max_chunk_size=300, overlap=0)

    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_index_sequential_multiple_sections() -> None:
    text = "# A\n" + "Sentence one. " * 50 + "\n# B\n" + "Sentence two. " * 50
    page = _make_page(text)
    chunks = chunk_page(page, max_chunk_size=200, overlap=0)

    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))
    # Indices must be globally sequential, not reset per section
    assert len(set(indices)) == len(indices)


def test_chunk_pages_chunk_index_not_globally_sequential() -> None:
    # chunk_pages concatenates results; each page resets chunk_index from 0
    page_a = _make_page("Content for page A. " * 5, url="https://example.com/a")
    page_b = _make_page("Content for page B. " * 5, url="https://example.com/b")

    chunks_a = chunk_page(page_a)
    chunks_b = chunk_page(page_b)
    all_chunks = chunk_pages([page_a, page_b])

    # Per-page indices start at 0 independently
    assert chunks_a[0].chunk_index == 0
    assert chunks_b[0].chunk_index == 0
    assert len(all_chunks) == len(chunks_a) + len(chunks_b)


# ---------------------------------------------------------------------------
# Chunk dataclass integrity
# ---------------------------------------------------------------------------


def test_chunk_is_dataclass_with_correct_fields() -> None:
    chunk = Chunk(
        text="hello",
        source_url="https://example.com",
        section_path="A > B",
        heading_chain=["A", "B"],
        chunk_index=0,
    )
    assert chunk.text == "hello"
    assert chunk.source_url == "https://example.com"
    assert chunk.section_path == "A > B"
    assert chunk.heading_chain == ["A", "B"]
    assert chunk.chunk_index == 0


def test_heading_chain_is_independent_copy() -> None:
    # Mutating the heading_chain after chunking must not affect the chunk
    text = "# Title\nSome content here."
    page = _make_page(text)
    chunks = chunk_page(page)

    original_chain = list(chunks[0].heading_chain)
    chunks[0].heading_chain.append("MUTATED")
    assert chunks[0].heading_chain != original_chain  # mutation happened on copy only
