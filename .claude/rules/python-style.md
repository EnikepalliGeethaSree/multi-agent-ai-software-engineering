---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python code style

- Target Python 3.11. Use `from __future__ import annotations` at the top of every module.
- Full type hints on public functions and methods; `mypy src` should stay clean.
- Data crossing a module boundary is a Pydantic v2 model (see `marl_agents.core.schemas`), not a raw dict.
- Use `pathlib.Path`, not `os.path`. Open text files with `encoding="utf-8"` explicitly (Windows default is cp1252).
- Use `logging.getLogger(__name__)`; no `print` in library code (CLI entry points may print).
- Keep modules small and single-purpose. If a file passes ~400 lines, split it.
- No module-level side effects (no network, no model loading, no DB connections at import time).
  Heavy optional deps (chromadb, sentence-transformers, langgraph, langchain, reportlab) are imported
  lazily inside the function/class that needs them, so `pip install -e .[dev]` stays enough for tests.
- Raise specific exceptions defined in the owning package; never `except Exception: pass`.
- Ruff (lint + format, line length 100) is the formatter; don't hand-format against it.

# Tests

- Every new behaviour gets a pytest test. Unit tests live in `tests/unit/`, mirroring the package path.
- Tests must not need network access, API keys, or the `capstone-datasets/` folder. Use
  `MockLLMProvider` and small fixtures under `tests/fixtures/`.
- Tests that do need real datasets or a real LLM are marked `@pytest.mark.dataset` / `@pytest.mark.llm`
  and are skipped by default.
