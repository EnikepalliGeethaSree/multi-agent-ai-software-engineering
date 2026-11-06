"""Embedding models behind one interface.

`HashingEmbedder` is an offline, dependency-free lexical baseline (identifier-aware hashed
bag-of-words, similar to TF hashing); `SentenceTransformerEmbedder` is the neural embedder.
Comparing the two is part of the RAG evaluation.
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_CODE_STOP = {
    "self",
    "def",
    "return",
    "the",
    "a",
    "an",
    "and",
    "or",
    "if",
    "else",
    "in",
    "is",
    "not",
    "for",
    "to",
    "of",
    "none",
    "true",
    "false",
    "import",
    "from",
    "as",
    "cls",
    "with",
    "it",
}


def identifier_tokens(text: str) -> list[str]:
    """Split identifiers: 'getUserById' / 'get_user_by_id' -> get, user, by, id (+ the whole)."""
    out: list[str] = []
    for word in _WORD.findall(text):
        lower = word.lower()
        parts = [p.lower() for p in _CAMEL.findall(word)] if not word.islower() else [lower]
        for p in parts:
            if p not in _CODE_STOP and len(p) > 1:
                out.append(p)
        if len(parts) > 1 and lower not in _CODE_STOP:
            out.append(lower)
    # snake_case: the regex above already splits on underscores (not word chars in _WORD)
    return out


class Embedder(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalized vector per text."""

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class HashingEmbedder(Embedder):
    name = "hashing"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _bucket(self, token: str) -> tuple[int, float]:
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % self.dim
        sign = 1.0 if h[4] & 1 else -1.0
        return idx, sign

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            counts = Counter(identifier_tokens(text))
            for tok, c in counts.items():
                idx, sign = self._bucket(tok)
                vec[idx] += sign * (1.0 + math.log(c))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class SentenceTransformerEmbedder(Embedder):
    """Neural embeddings; requires the `rag` extra. Model is loaded lazily on first use."""

    name = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self.dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in vecs]


def create_embedder(name: str) -> Embedder:
    if name in {"hashing", "hash", "lexical"}:
        return HashingEmbedder()
    return SentenceTransformerEmbedder(name)
