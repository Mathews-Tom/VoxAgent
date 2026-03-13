from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from voxagent.knowledge.chunker import Chunk
from voxagent.knowledge.ingest import PageContent

_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_RRF_K = 60

_CHUNKS_FILE = "chunks.json"
_BM25_CORPUS_FILE = "bm25_corpus.json"
_FAISS_FILE = "faiss.index"
_HASH_MAP_FILE = "hash_map.json"
_MANIFEST_FILE = "manifest.json"


@dataclass
class SearchResult:
    chunk: Chunk
    score: float
    bm25_rank: int | None
    faiss_rank: int | None


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _normalize_vectors(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vecs / norms).astype(np.float32)


class KnowledgeEngine:
    def __init__(self, storage_dir: str) -> None:
        self._storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        self._chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None
        self._bm25_corpus: list[list[str]] = []
        self._faiss_index: faiss.Index | None = None
        self._model: SentenceTransformer | None = None
        self._hash_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _path(self, filename: str) -> str:
        return os.path.join(self._storage_dir, filename)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_index(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks

        # BM25
        self._bm25_corpus = [_tokenize(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._bm25_corpus)

        # Sentence transformer + FAISS
        if self._model is None:
            self._model = SentenceTransformer(_EMBEDDING_MODEL)

        texts = [c.text for c in chunks]
        embeddings = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        embeddings = _normalize_vectors(embeddings)

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)
        self._faiss_index = index

        # Load existing hash map before persisting so we don't overwrite it
        hash_map_path = self._path(_HASH_MAP_FILE)
        if os.path.exists(hash_map_path):
            with open(hash_map_path, encoding="utf-8") as fh:
                self._hash_map = json.load(fh)

        self._persist()

    def _persist(self) -> None:
        # Chunks
        chunks_data = [asdict(c) for c in self._chunks]
        with open(self._path(_CHUNKS_FILE), "w", encoding="utf-8") as fh:
            json.dump(chunks_data, fh)

        # BM25 corpus
        with open(self._path(_BM25_CORPUS_FILE), "w", encoding="utf-8") as fh:
            json.dump(self._bm25_corpus, fh)

        # FAISS index
        faiss.write_index(self._faiss_index, self._path(_FAISS_FILE))

        # Hash map
        with open(self._path(_HASH_MAP_FILE), "w", encoding="utf-8") as fh:
            json.dump(self._hash_map, fh)

    def write_manifest(self, manifest: dict[str, object]) -> None:
        with open(self._path(_MANIFEST_FILE), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

    def read_manifest(self) -> dict[str, object]:
        manifest_path = self._path(_MANIFEST_FILE)
        if not os.path.exists(manifest_path):
            return {}
        with open(manifest_path, encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_index(self) -> None:
        with open(self._path(_CHUNKS_FILE), encoding="utf-8") as fh:
            raw_chunks = json.load(fh)
        self._chunks = [Chunk(**d) for d in raw_chunks]

        with open(self._path(_BM25_CORPUS_FILE), encoding="utf-8") as fh:
            self._bm25_corpus = json.load(fh)
        self._bm25 = BM25Okapi(self._bm25_corpus)

        self._faiss_index = faiss.read_index(self._path(_FAISS_FILE))

        hash_map_path = self._path(_HASH_MAP_FILE)
        if os.path.exists(hash_map_path):
            with open(hash_map_path, encoding="utf-8") as fh:
                self._hash_map = json.load(fh)

        if self._model is None:
            self._model = SentenceTransformer(_EMBEDDING_MODEL)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if not self._chunks:
            return []
        if self._bm25 is None:
            raise RuntimeError("Index not built. Call build_index() or load_index() first.")
        if self._faiss_index is None:
            raise RuntimeError("Index not built. Call build_index() or load_index() first.")
        if self._model is None:
            raise RuntimeError("Model not loaded. Call build_index() or load_index() first.")

        n_chunks = len(self._chunks)
        fetch_k = min(top_k * 2, n_chunks)

        # BM25 ranking
        bm25_scores = self._bm25.get_scores(_tokenize(query))
        bm25_ranked: list[int] = sorted(
            range(n_chunks), key=lambda i: bm25_scores[i], reverse=True
        )[:fetch_k]

        # FAISS ranking (filter -1 padding from results with fewer vectors than k)
        query_vec = self._model.encode([query], convert_to_numpy=True, show_progress_bar=False)
        query_vec = _normalize_vectors(query_vec)
        _, faiss_indices = self._faiss_index.search(query_vec, fetch_k)
        faiss_ranked: list[int] = [
            int(idx) for idx in faiss_indices[0] if idx >= 0
        ]

        # Reciprocal Rank Fusion
        rrf_scores: dict[int, float] = {}

        for rank, chunk_idx in enumerate(bm25_ranked):
            rrf_scores[chunk_idx] = rrf_scores.get(chunk_idx, 0.0) + 1.0 / (_RRF_K + rank + 1)

        for rank, chunk_idx in enumerate(faiss_ranked):
            rrf_scores[chunk_idx] = rrf_scores.get(chunk_idx, 0.0) + 1.0 / (_RRF_K + rank + 1)

        # Build lookup maps for individual ranks (1-based)
        bm25_rank_map: dict[int, int] = {idx: r + 1 for r, idx in enumerate(bm25_ranked)}
        faiss_rank_map: dict[int, int] = {idx: r + 1 for r, idx in enumerate(faiss_ranked)}

        # Sort by fused score and return top_k
        sorted_indices = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)[:top_k]

        return [
            SearchResult(
                chunk=self._chunks[i],
                score=rrf_scores[i],
                bm25_rank=bm25_rank_map.get(i),
                faiss_rank=faiss_rank_map.get(i),
            )
            for i in sorted_indices
        ]

    # ------------------------------------------------------------------
    # Incremental re-index support
    # ------------------------------------------------------------------

    def needs_reindex(self, pages: list[PageContent]) -> list[PageContent]:
        changed: list[PageContent] = []
        for page in pages:
            stored_hash = self._hash_map.get(page.url)
            if stored_hash != page.content_hash:
                changed.append(page)
        return changed

    def update_hash_map(self, pages: list[PageContent]) -> None:
        """Record content hashes for the given pages and persist."""
        for page in pages:
            self._hash_map[page.url] = page.content_hash
        hash_map_path = self._path(_HASH_MAP_FILE)
        with open(hash_map_path, "w", encoding="utf-8") as fh:
            json.dump(self._hash_map, fh)
