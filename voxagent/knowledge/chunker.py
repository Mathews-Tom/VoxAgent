from __future__ import annotations

import re
from dataclasses import dataclass

from voxagent.knowledge.ingest import PageContent

# Matches markdown ATX headings: # H1, ## H2, ### H3, etc.
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
# Matches a line that is ALL UPPERCASE (≥ 3 chars, no lowercase letters)
_UPPERCASE_LINE = re.compile(r"^[A-Z][A-Z0-9 \t\-:,./]{2,}$")

# Sentence-boundary terminators used for split points
_SENTENCE_END = re.compile(r"(?<=[\.\?!])\s+")


@dataclass
class Chunk:
    text: str
    source_url: str
    section_path: str
    heading_chain: list[str]
    chunk_index: int


def _split_at_sentences(text: str, max_size: int) -> list[str]:
    """Split text into pieces ≤ max_size, preferring sentence boundaries."""
    if len(text) <= max_size:
        return [text]

    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_size:
        window = remaining[:max_size]
        # Find last sentence boundary within the window
        matches = list(_SENTENCE_END.finditer(window))
        if matches:
            split_at = matches[-1].end()
        else:
            # Fall back to last whitespace
            ws = window.rfind(" ")
            split_at = ws + 1 if ws != -1 else max_size
        pieces.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:]
    if remaining.strip():
        pieces.append(remaining.strip())
    return pieces


def chunk_page(
    page: PageContent,
    max_chunk_size: int = 1000,
    overlap: int = 200,
) -> list[Chunk]:
    lines = page.text.splitlines()

    # Each entry: (heading_level, heading_text)
    # level 0 = uppercase sentinel (treated as H1 equivalent)
    heading_stack: list[tuple[int, str]] = []

    # Accumulate non-heading lines into sections
    sections: list[tuple[list[str], str]] = []  # (heading_chain, body_text)
    current_body: list[str] = []

    def flush_section() -> None:
        body = "\n".join(current_body).strip()
        if body:
            chain = [h for _, h in heading_stack]
            sections.append((list(chain), body))
        current_body.clear()

    for line in lines:
        md_match = _MARKDOWN_HEADING.match(line)
        uc_match = _UPPERCASE_LINE.match(line.strip()) if not md_match else None

        if md_match or uc_match:
            flush_section()

            if md_match:
                level = len(md_match.group(1))
                heading_text = md_match.group(2).strip()
            else:
                level = 1
                heading_text = line.strip()

            # Pop headings of same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, heading_text))
        else:
            current_body.append(line)

    flush_section()

    # If no sections were found, treat the whole page as one section
    if not sections:
        chain: list[str] = []
        sections = [(chain, page.text.strip())]

    chunks: list[Chunk] = []
    chunk_index = 0

    for heading_chain, body in sections:
        section_path = " > ".join(heading_chain) if heading_chain else ""
        raw_pieces = _split_at_sentences(body, max_chunk_size)

        # Apply overlap: each piece gets the tail of the previous piece prepended
        prev_tail = ""
        for piece in raw_pieces:
            if prev_tail:
                combined = prev_tail + " " + piece
            else:
                combined = piece

            # If the combined text exceeds max_chunk_size, trim the overlap prefix
            if len(combined) > max_chunk_size + overlap:
                combined = combined[-(max_chunk_size + overlap):]

            chunks.append(
                Chunk(
                    text=combined.strip(),
                    source_url=page.url,
                    section_path=section_path,
                    heading_chain=list(heading_chain),
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            # Store last `overlap` characters as the tail for next piece
            prev_tail = piece[-overlap:] if len(piece) > overlap else piece

    return chunks


def chunk_pages(
    pages: list[PageContent],
    max_chunk_size: int = 1000,
    overlap: int = 200,
) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for page in pages:
        all_chunks.extend(chunk_page(page, max_chunk_size=max_chunk_size, overlap=overlap))
    return all_chunks
