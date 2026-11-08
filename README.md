# Multi-Agent AI Assistant for Software Engineering Solutions

B.Tech capstone (23CSE399), team 23UG082. Five specialized LLM agents (Code Review, Bug Detection,
Security, Test Generation, Documentation) analyze a repository with project-aware RAG and LangGraph
orchestration, evaluated at agent level and system level.

**Status:** Code Review Agent implemented and tested (offline test suite, no API key needed). It reviews
whole repositories and **code changes** (branches, commits, uncommitted/staged work, two ZIPs) with
impact analysis, risk-ranked hunks, verified fix suggestions, SARIF and a CI / pre-commit gate. See
[docs/code-review-agent.md](docs/code-review-agent.md), [docs/change-review.md](docs/change-review.md)
and [docs/results.md](docs/results.md).

**LLM:** Google Gemini through the free tier of Google AI Studio ([setup and limits](docs/llm-gemini.md)).
On the free tier Google may use what you send to improve its products, so do not review
confidential code this way. `--mode static_only` sends nothing anywhere.

**Execution time:** every review records its stage times, and `python -m marl_agents.evaluation.benchmark_runtime`
measures small, medium and large files ([docs/performance.md](docs/performance.md)).

**Fine-tuning:** a code classifier prioritizes which changes get LLM review
([docs/fine-tuning.md](docs/fine-tuning.md)).

## Dashboard

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-dashboard.ps1   # then open http://127.0.0.1:8000
```

Upload a repository ZIP or a Python file, or review a change (local git repository or two ZIPs),
watch the review run, and explore findings, risk-ranked diffs, suggested fixes, charts and reports.
See [docs/dashboard.md](docs/dashboard.md).

## Review a change from the command line

```bash
python -m marl_agents.cli review-change path/to/repo                        # uncommitted work
python -m marl_agents.cli review-change . --base main --head feature --fail-on high
python scripts/install_hooks.py path/to/repo                                # pre-commit gate
```

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env            # add a free GEMINI_API_KEY for LLM reviews
pytest                          # offline: needs no key
python -m marl_agents.cli check # one small real request, once a key is set
python -m marl_agents.cli bugs path/to/repo   # Bug Detection Agent (docs/bug-detection-agent.md)
```

Optional extras: `.[analysis]`, `.[rag]`, `.[llm]`, `.[api]`, `.[reports]`, `.[eval]`, `.[train]`.

## Docs

- **[Project guide](docs/project-guide.md): start here.** What we built, how the code works, every file, references.
- [Implementation report](docs/implementation-report.md): the latest round of changes and its results.
- [Gemini setup, quota and privacy](docs/llm-gemini.md)
- [Execution-time analysis](docs/performance.md)
- [Fine-tuning](docs/fine-tuning.md)
- [Evaluation framework](docs/evaluation.md): methodology, configurations A-D (Static Only, LLM Only, Static + LLM, Static + LLM + RAG), baselines, metric definitions, timing (`eval ablation`, `eval summary`).
- [Dashboard](docs/dashboard.md)
- [Change review](docs/change-review.md)
- [Architecture](docs/architecture.md)
- [Datasets](docs/datasets.md)
- [Severity rubric](docs/severity-rubric.md)
- [Decision log](docs/decisions.md)
- Contributor/AI-assistant guide: [CLAUDE.md](CLAUDE.md)

Benchmark data lives in `capstone-datasets/` (not in git).
