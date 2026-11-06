import importlib.util

import pytest

from marl_agents.rag import (
    ChromaVectorStore,
    HashingEmbedder,
    InMemoryVectorStore,
    Retriever,
    SourceType,
    chunk_repository,
    load_guideline_chunks,
)
from marl_agents.rag.chunking import MAX_CHUNK_LINES
from marl_agents.rag.embeddings import identifier_tokens

SERVICE = '''"""User service."""
import db

TIMEOUT = 5


class UserService:
    """Manages users."""

    def get_user(self, user_id):
        return db.fetch_user(user_id)

    def delete_user(self, user_id):
        return db.remove_user(user_id)


def authenticate(username, password):
    user = db.fetch_by_name(username)
    return user and user.password_hash == hash_pw(password)
'''

FILES = {
    "app/service.py": SERVICE,
    "app/db.py": "def fetch_user(uid):\n    return {'id': uid}\n\ndef remove_user(uid):\n    return True\n",
    "tests/test_service.py": "def test_auth():\n    assert authenticate('a', 'b') is None\n",
    "README.md": "# Project\nIntro text.\n\n## Auth\nUsers authenticate with a password.\n",
    "config.yaml": "timeout: 5\n",
}


def test_code_aware_chunks(make_index) -> None:  # type: ignore[no-untyped-def]
    chunks = chunk_repository(make_index(FILES))
    service = {c.symbol: c for c in chunks if c.file == "app/service.py"}
    assert set(service) == {"<module>", "UserService", "authenticate"}  # small class = one chunk
    assert service["UserService"].start_line == 7 and service["authenticate"].kind == "function"
    assert "TIMEOUT = 5" in service["<module>"].text and "\n\n" not in service["<module>"].text
    kinds = {c.source_type for c in chunks}
    assert kinds == {SourceType.CODE, SourceType.TEST, SourceType.DOC, SourceType.CONFIG}
    readme = [c for c in chunks if c.file == "README.md"]
    assert [c.symbol for c in readme] == ["Project", "Auth"]  # split at headings
    assert len({c.id for c in chunks}) == len(chunks)  # stable, unique ids


def test_large_class_is_split_into_methods(make_index) -> None:  # type: ignore[no-untyped-def]
    methods = "".join(
        f"    def m{i}(self):\n" + "".join(f"        x{j} = {j}\n" for j in range(8))
        for i in range(20)
    )
    chunks = chunk_repository(make_index({"big.py": f"class Big:\n{methods}"}))
    assert any(c.symbol == "Big.m0" for c in chunks)
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in chunks)


def test_long_function_is_windowed(make_index) -> None:  # type: ignore[no-untyped-def]
    body = "".join(f"    x{i} = {i}\n" for i in range(300))
    chunks = [
        c for c in chunk_repository(make_index({"long.py": f"def f():\n{body}"})) if c.symbol == "f"
    ]
    assert len(chunks) >= 3 and chunks[0].start_line == 1 and chunks[-1].end_line == 301
    assert chunks[1].start_line < chunks[0].end_line  # overlapping windows


def test_identifier_tokens_split_camel_and_snake() -> None:
    toks = identifier_tokens("getUserById(user_id) self.HTTPServer")
    assert {"get", "user", "by", "id", "getuserbyid", "http", "server"} <= set(toks)
    assert "self" not in toks


def test_hashing_embedder_is_normalized_and_semantic_enough() -> None:
    emb = HashingEmbedder(dim=512)
    a, b, c = emb.embed(["delete_user(user_id)", "def remove user by id", "parse yaml config file"])
    assert sum(x * x for x in a) == pytest.approx(1.0)
    sim = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    assert sim(a, b) > sim(a, c)
    assert emb.embed(["same"]) == emb.embed(["same"])  # deterministic


def test_in_memory_store_query_filter_and_idempotent_add(make_index) -> None:  # type: ignore[no-untyped-def]
    chunks = chunk_repository(make_index(FILES))
    emb = HashingEmbedder()
    store = InMemoryVectorStore()
    vecs = emb.embed([c.text for c in chunks])
    store.add("r", chunks, vecs)
    store.add("r", chunks, vecs)  # duplicates ignored
    assert store.count("r") == len(chunks)
    hits = store.query("r", emb.embed_query("remove user"), k=3, where={"source_type": "code"})
    assert hits and all(c.source_type is SourceType.CODE for c, _ in hits)
    assert [s for _, s in hits] == sorted([s for _, s in hits], reverse=True)
    store.delete("r")
    assert store.count("r") == 0


@pytest.mark.skipif(importlib.util.find_spec("chromadb") is None, reason="chromadb not installed")
def test_chroma_store_matches_in_memory_ranking(make_index) -> None:  # type: ignore[no-untyped-def]
    chunks = chunk_repository(make_index(FILES))
    emb = HashingEmbedder()
    vecs = emb.embed([c.text for c in chunks])
    mem, chroma = InMemoryVectorStore(), ChromaVectorStore()
    mem.add("repo_x", chunks, vecs)
    chroma.add("repo_x", chunks, vecs)
    q = emb.embed_query("fetch user from the database")
    top_mem = [c.id for c, _ in mem.query("repo_x", q, 3)]
    top_chroma = [c.id for c, _ in chroma.query("repo_x", q, 3)]
    assert top_mem[0] == top_chroma[0]
    filtered = chroma.query("repo_x", q, 5, where={"file": "app/db.py"})
    assert filtered and all(c.file == "app/db.py" for c, _ in filtered)
    chroma.delete("repo_x")


@pytest.mark.skipif(importlib.util.find_spec("chromadb") is None, reason="chromadb not installed")
def test_a_saved_store_recovers_from_a_failed_read(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from chromadb.errors import InternalError

    store = ChromaVectorStore(tmp_path / "chroma")
    calls: list[str] = []

    def flaky(collection, _vector, _k, _where):  # type: ignore[no-untyped-def]
        calls.append(collection)
        if len(calls) == 1:
            raise InternalError("Nothing found on disk")
        return ["hit"]

    monkeypatch.setattr(store, "_query", flaky)
    monkeypatch.setattr(store, "_reopen", lambda: calls.append("reopened"))
    assert store.query("repo", [0.1], 3) == ["hit"]
    assert calls == ["repo", "reopened", "repo"]


@pytest.mark.skipif(importlib.util.find_spec("chromadb") is None, reason="chromadb not installed")
def test_a_failed_read_that_persists_is_raised_not_hidden(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from chromadb.errors import InternalError

    store = ChromaVectorStore(tmp_path / "chroma")

    def always_fails(*_args):  # type: ignore[no-untyped-def]
        raise InternalError("Nothing found on disk")

    monkeypatch.setattr(store, "_query", always_fails)
    monkeypatch.setattr(store, "_reopen", lambda: None)
    with pytest.raises(InternalError):
        store.query("repo", [0.1], 3)


@pytest.mark.skipif(importlib.util.find_spec("chromadb") is None, reason="chromadb not installed")
def test_an_in_memory_client_is_never_reopened(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from chromadb.errors import InternalError

    store = ChromaVectorStore()
    reopened: list[bool] = []

    def fails(*_args):  # type: ignore[no-untyped-def]
        raise InternalError("Nothing found on disk")

    monkeypatch.setattr(store, "_query", fails)
    monkeypatch.setattr(store, "_reopen", lambda: reopened.append(True))
    with pytest.raises(InternalError):
        store.query("repo", [0.1], 3)
    assert reopened == []


def test_retriever_excludes_unit_and_serves_guidelines(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(FILES)
    r = Retriever(HashingEmbedder(), InMemoryVectorStore())
    with pytest.raises(RuntimeError):
        r.retrieve("x")
    stats = r.index_repository(index)
    assert stats.chunks == len(r.chunks()) and stats.by_source_type["code"] >= 3
    hits = r.retrieve("authenticate password", k=3, exclude_ranges={"app/service.py": (17, 19)})
    assert all(not (h.chunk.file == "app/service.py" and h.chunk.start_line == 17) for h in hits)
    guides = r.retrieve_guidelines("SQL query built with f-string from user input", k=2)
    assert guides and any("Injection" in g.chunk.text for g in guides)


def test_guideline_knowledge_base_loads() -> None:
    chunks = load_guideline_chunks()
    assert len(chunks) >= 15
    assert all(c.source_type is SourceType.GUIDELINE for c in chunks)
    assert any("CWE-89" in c.text for c in chunks)
