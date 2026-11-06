from __future__ import annotations

import json
from pathlib import Path

import pytest

from marl_agents.config import Settings, load_settings
from marl_agents.ingestion import Repository, load_files
from marl_agents.parsing import RepoIndex

FIXTURES = Path(__file__).parent / "fixtures"
PLANTED = FIXTURES / "repos" / "planted"
PLANTED_EXPECTED = FIXTURES / "repos" / "planted_expected.json"


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's .env (e.g. a real GROQ_API_KEY or provider choice)."""
    monkeypatch.setenv("MARL_NO_DOTENV", "1")
    for var in (
        "MARL_LLM__PROVIDER",
        "MARL_LLM__MODEL",
        "LLM_PROVIDER",
        "GEMINI_MODEL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Deterministic, offline settings with an isolated workspace."""
    s = load_settings()
    s.llm.provider = "mock"
    s.llm.model = None
    s.llm.requests_per_minute = None
    s.llm.tokens_per_minute = None
    s.ingestion.workspace_dir = str(tmp_path / "workspaces")
    s.rag.vector_store = "memory"
    s.rag.persist_dir = None
    s.rag.embedding_model = "hashing"
    s.review.concurrency = 1
    # Slow / extra-LLM-call features are off by default in tests; their own tests switch them on.
    s.review.type_check = False
    s.review.suggest_fixes = False
    s.review.unit_cache = False
    s.review.analysis_cache = False
    return s


@pytest.fixture
def make_repo(settings: Settings):  # type: ignore[no-untyped-def]
    def _make(files: dict[str, str]) -> Repository:
        return load_files(files, settings.ingestion)

    return _make


@pytest.fixture
def make_index(make_repo):  # type: ignore[no-untyped-def]
    def _make(files: dict[str, str]) -> RepoIndex:
        return RepoIndex.build(make_repo(files))

    return _make


def llm_json(findings: list[dict] | None = None, assessments: list[dict] | None = None) -> str:
    return json.dumps({"findings": findings or [], "static_assessments": assessments or []})
