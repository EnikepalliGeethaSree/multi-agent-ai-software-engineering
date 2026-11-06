"""Index a repository and retrieve context. Retrieval can be disabled (experiment config B)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import resources

from pydantic import BaseModel

from marl_agents.ingestion.models import Repository
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.rag.chunking import Chunk, SourceType, chunk_repository
from marl_agents.rag.embeddings import Embedder
from marl_agents.rag.store import VectorStore, Where

logger = logging.getLogger(__name__)

GUIDELINES_COLLECTION = "guidelines_v1"


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    reason: str = "similarity"


@dataclass
class IndexStats:
    repo_id: str
    chunks: int
    by_source_type: dict[str, int]


def load_guideline_chunks() -> list[Chunk]:
    """Curated coding-standard and OWASP/CWE guidance shipped with the package."""
    chunks: list[Chunk] = []
    pkg = resources.files("marl_agents.rag") / "knowledge"
    for entry in sorted(pkg.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".md"):
            continue
        text = entry.read_text(encoding="utf-8")
        sections = [s for s in text.split("\n## ") if s.strip()]
        line = 1
        for i, section in enumerate(sections):
            body = section if i == 0 else "## " + section
            n = body.count("\n") + 1
            title = body.splitlines()[0].lstrip("# ").strip()
            chunks.append(
                Chunk(
                    id=f"guide-{entry.name}-{i}",
                    repo_id=GUIDELINES_COLLECTION,
                    file=f"knowledge/{entry.name}",
                    symbol=title,
                    kind="guideline",
                    start_line=line,
                    end_line=line + n - 1,
                    language="markdown",
                    source_type=SourceType.GUIDELINE,
                    text=body.strip(),
                )
            )
            line += n
    return chunks


class Retriever:
    """Dense retrieval over one repository's chunks plus the shared guideline collection."""

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store
        self.repo_id: str | None = None
        self._chunks_by_id: dict[str, Chunk] = {}
        # Same query, same index, same answer: identical code asks identical questions.
        self._results: dict[str, list[RetrievedChunk]] = {}
        self.cache_hits = 0

    # ---- indexing ----------------------------------------------------------------------------

    def index_repository(self, index: RepoIndex) -> IndexStats:
        repo: Repository = index.repo
        self.repo_id = repo.repo_id
        self._results.clear()
        chunks = chunk_repository(index)
        self._chunks_by_id = {c.id: c for c in chunks}
        if self.store.count(self.repo_id) < len(chunks):
            vectors = self.embedder.embed([c.text for c in chunks]) if chunks else []
            self.store.add(self.repo_id, chunks, vectors)
        if self.store.count(GUIDELINES_COLLECTION) == 0:
            guides = load_guideline_chunks()
            self.store.add(
                GUIDELINES_COLLECTION, guides, self.embedder.embed([g.text for g in guides])
            )
        by_type: dict[str, int] = {}
        for c in chunks:
            by_type[str(c.source_type)] = by_type.get(str(c.source_type), 0) + 1
        logger.info("Indexed %d chunks for %s", len(chunks), self.repo_id)
        return IndexStats(repo_id=self.repo_id, chunks=len(chunks), by_source_type=by_type)

    def chunks(self) -> list[Chunk]:
        return list(self._chunks_by_id.values())

    # ---- retrieval ---------------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        k: int = 8,
        where: Where | None = None,
        exclude_files: set[str] | None = None,
        exclude_ranges: dict[str, tuple[int, int]] | None = None,
    ) -> list[RetrievedChunk]:
        if self.repo_id is None:
            raise RuntimeError("index_repository() must be called before retrieve()")
        cache_key = repr((self.repo_id, query, k, where, exclude_files, exclude_ranges))
        cached = self._results.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return list(cached)
        vector = self.embedder.embed_query(query)
        raw = self.store.query(self.repo_id, vector, k * 3 + 5, where)
        out: list[RetrievedChunk] = []
        for chunk, score in raw:
            if exclude_files and chunk.file in exclude_files:
                continue
            if exclude_ranges and chunk.file in exclude_ranges:
                s, e = exclude_ranges[chunk.file]
                if chunk.start_line <= e and s <= chunk.end_line:
                    continue
            out.append(RetrievedChunk(chunk=chunk, score=score))
            if len(out) >= k:
                break
        self._results[cache_key] = out
        return list(out)

    def retrieve_guidelines(self, query: str, k: int = 3) -> list[RetrievedChunk]:
        vector = self.embedder.embed_query(query)
        return [
            RetrievedChunk(chunk=c, score=s, reason="guideline")
            for c, s in self.store.query(GUIDELINES_COLLECTION, vector, k)
        ]
