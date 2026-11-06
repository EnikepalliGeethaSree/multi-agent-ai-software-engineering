"""Code-aware chunking, embeddings, vector store (ChromaDB), retrieval. Disable-able (config B)."""

from marl_agents.rag.chunking import Chunk, SourceType, chunk_repository
from marl_agents.rag.embeddings import (
    Embedder,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    create_embedder,
)
from marl_agents.rag.retriever import IndexStats, RetrievedChunk, Retriever, load_guideline_chunks
from marl_agents.rag.store import (
    ChromaVectorStore,
    InMemoryVectorStore,
    VectorStore,
    create_store,
)

__all__ = [
    "ChromaVectorStore",
    "Chunk",
    "Embedder",
    "HashingEmbedder",
    "InMemoryVectorStore",
    "IndexStats",
    "RetrievedChunk",
    "Retriever",
    "SentenceTransformerEmbedder",
    "SourceType",
    "VectorStore",
    "chunk_repository",
    "create_embedder",
    "create_store",
    "load_guideline_chunks",
]
