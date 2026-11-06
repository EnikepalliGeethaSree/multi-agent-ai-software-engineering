"""Vector stores: an exact in-memory store (tests, small repos) and ChromaDB (persistent)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from marl_agents.rag.chunking import Chunk

logger = logging.getLogger(__name__)

Where = dict[str, str | int]


class VectorStore(ABC):
    @abstractmethod
    def add(self, collection: str, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    @abstractmethod
    def query(
        self, collection: str, vector: list[float], k: int, where: Where | None = None
    ) -> list[tuple[Chunk, float]]:
        """Top-k (chunk, cosine similarity) pairs, best first."""

    @abstractmethod
    def count(self, collection: str) -> int: ...

    @abstractmethod
    def delete(self, collection: str) -> None: ...


def _matches(chunk: Chunk, where: Where | None) -> bool:
    if not where:
        return True
    meta = chunk.metadata()
    return all(meta.get(k) == v for k, v in where.items())


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._data: dict[str, list[tuple[Chunk, list[float]]]] = {}

    def add(self, collection: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        bucket = self._data.setdefault(collection, [])
        existing = {c.id for c, _ in bucket}
        bucket.extend((c, v) for c, v in zip(chunks, vectors, strict=True) if c.id not in existing)

    def query(
        self, collection: str, vector: list[float], k: int, where: Where | None = None
    ) -> list[tuple[Chunk, float]]:
        scored = [
            (chunk, sum(a * b for a, b in zip(vector, vec, strict=False)))
            for chunk, vec in self._data.get(collection, [])
            if _matches(chunk, where)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def count(self, collection: str) -> int:
        return len(self._data.get(collection, []))

    def delete(self, collection: str) -> None:
        self._data.pop(collection, None)


class ChromaVectorStore(VectorStore):
    """ChromaDB with our own embeddings (no Chroma-side embedding model download)."""

    def __init__(self, persist_dir: str | Path | None = None) -> None:
        import chromadb

        self._persist_dir = None if persist_dir is None else str(persist_dir)
        if persist_dir is None:
            self._client = chromadb.EphemeralClient()
        else:
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(persist_dir))

    def _collection(self, name: str):  # type: ignore[no-untyped-def]
        return self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )

    def add(self, collection: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        col = self._collection(collection)
        batch = 1000
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            col.upsert(
                ids=[c.id for c in part],
                embeddings=vectors[i : i + batch],
                documents=[c.text for c in part],
                metadatas=[{**c.metadata(), "chunk_json": c.model_dump_json()} for c in part],
            )

    def _reopen(self) -> None:
        import chromadb
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))

    def query(
        self, collection: str, vector: list[float], k: int, where: Where | None = None
    ) -> list[tuple[Chunk, float]]:
        """Reopens the client once on an internal error.

        ChromaDB 1.5.9 can fail with "Error creating hnsw segment reader: Nothing found on disk"
        when one process reads several saved collections in turn, and a reopened client reads them
        correctly. An in-memory client is not reopened, because that would lose its data.
        """
        from chromadb.errors import InternalError

        try:
            return self._query(collection, vector, k, where)
        except InternalError:
            if self._persist_dir is None:
                raise
            logger.warning("ChromaDB read failed for %s; reopening the client", collection)
            self._reopen()
            return self._query(collection, vector, k, where)

    def _query(
        self, collection: str, vector: list[float], k: int, where: Where | None = None
    ) -> list[tuple[Chunk, float]]:
        col = self._collection(collection)
        if col.count() == 0:
            return []
        chroma_where = None
        if where:
            clauses = [{key: value} for key, value in where.items()]
            chroma_where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        res = col.query(
            query_embeddings=[vector],
            n_results=min(k, col.count()),
            where=chroma_where,
            include=["metadatas", "distances"],
        )
        out: list[tuple[Chunk, float]] = []
        for meta, dist in zip(res["metadatas"][0], res["distances"][0], strict=True):
            chunk = Chunk.model_validate_json(str(meta["chunk_json"]))
            out.append((chunk, 1.0 - float(dist)))
        return out

    def count(self, collection: str) -> int:
        return int(self._collection(collection).count())

    def delete(self, collection: str) -> None:
        try:
            self._client.delete_collection(collection)
        except (ValueError, Exception) as exc:
            logger.debug("delete_collection(%s) ignored: %s", collection, exc)


def create_store(kind: str, persist_dir: str | None = None) -> VectorStore:
    if kind == "memory":
        return InMemoryVectorStore()
    if kind == "chroma":
        return ChromaVectorStore(persist_dir)
    raise ValueError(f"Unknown vector store {kind!r}")
