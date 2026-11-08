# CLAUDE.md — Multi-Agent AI Assistant for Software Engineering Solutions

B.Tech final-year capstone (23CSE399, Team 23UG082, guide: Ms. Shalini Tiwari). It is both a
**working product** and a **research/evaluation project**. Approval deck: [PPT/Finalyear_2027_23UG082.pptx](PPT/Finalyear_2027_23UG082.pptx).

## What we are building

A platform where **five specialized LLM agents** analyze a software repository. A
**repository-level RAG layer** gives them project-specific context, **LangGraph** orchestrates them,
and a **Result Aggregator** merges their output into a dashboard, PDF report and suggestions.

```
GitHub repo / ZIP -> Ingestion -> Parsing (AST) -> RAG knowledge base (ChromaDB)
  -> LangGraph orchestrator -> [Code Review | Bug Detection | Security | Test Gen | Documentation]
  -> Result Aggregator (dedupe, score, prioritize) -> Dashboard / PDF / Suggestions
  -> Agent-level + system-level evaluation
```

| Agent | Responsibility | Eval dataset | Metrics (from approved deck) |
|---|---|---|---|
| Code Review | quality, smells, complexity, maintainability, refactoring | CodeReviewer | BLEU (comment gen), F1 (quality est.), accuracy |
| Bug Detection | logic/runtime errors, localization, repro steps | BugsInPy | precision, recall, F1, localization accuracy |
| Security | vuln scan, OWASP Top 10, CWE mapping, risk | Devign | accuracy, precision, recall, F1, AUC-ROC |
| Test Generation | unit tests, edge cases, coverage | HumanEval | line/branch coverage, mutation score, pass@1 |
| Documentation | docstrings, missing/outdated docs | CodeSearchNet | BLEU-1, ROUGE-L, METEOR, CIDEr |
| **System** | end-to-end | **SWE-bench Lite** | resolve rate (primary); agent metrics (secondary) |

System-level experiment compares three configurations on the same data:
**A = single LLM**, **B = multi-agent without RAG**, **C = multi-agent + RAG**. RAG retrieval is also
evaluated on its own (Recall@K, MRR, nDCG).

## Current focus

**Code Review Agent: implemented and tested** (see [docs/code-review-agent.md](docs/code-review-agent.md)).
Pipeline: ingestion -> AST parse + call graph -> static analysis (Ruff, Radon, AST checks, secrets,
test gaps) -> review units -> context (call graph + ChromaDB retrieval + guidelines) -> LLM review ->
validation -> dedup -> severity rubric -> confidence -> redaction -> JSON / Markdown / PDF -> evaluation.
It also reviews **code changes** (git refs / working tree / staged / two ZIPs): impact analysis on
unchanged callers, hunk risk ranking, verified fix suggestions, actionability filter, mypy, SARIF,
CI/pre-commit gate (see [docs/change-review.md](docs/change-review.md), decisions D16-D20).
Results (static baseline, LLM runs, hunk risk, usefulness judge) are in `docs/results.md`.

**Bug Detection Agent: implemented and tested** (see [docs/bug-detection-agent.md](docs/bug-detection-agent.md),
D31). It subclasses the Code Review Agent: control-flow checks (`parsing/cfg.py`,
`static_analysis/flow_checks.py`), bug prompts, claim checks, a scan budget, and fault localization from
a failing test. Its BugsInPy evaluation has two tracks, and the test split has not been run.

Do not start the other three agents unless asked; reuse the shared building blocks listed in
`.claude/rules/architecture.md`.

LLM: **Google Gemini free tier** (`GEMINI_API_KEY` in `.env`, default model `gemini-3.8-flash`, see
`docs/llm-gemini.md` and D27). No paid APIs. Groq remains a legacy option (`LLM_PROVIDER=groq`).
Never read or print `.env`. `cli models` lists models for the key, `cli check` verifies key + model
with one tiny call. Free-tier content may be used by Google, so never send confidential code.

Dashboard: `python -m marl_agents.cli serve` (FastAPI `src/marl_agents/api/` + React/TS/Tailwind
`frontend/`, see docs/dashboard.md). Frontend: `cd frontend; npm test; npm run build`.

CLI: `python -m marl_agents.cli bugs <dir|zip|file.py> [--failing-test tests/t.py::test_x]`,
`python -m marl_agents.cli eval-bugs {audit|localization|detection|labels} [--split dev|test --final]`,
`python -m marl_agents.cli review <dir|zip|file.py>`,
`python -m marl_agents.cli review-change [repo] [--base/--head/--staged | --before/--after ZIPs] [--fail-on]`
and `python -m marl_agents.cli eval {planted|codereviewer|retrieval|hunkrisk|timing|summary|usefulness|agreement|ablation|classifier|before-after}`
(see `--help`). File-size benchmark: `python -m marl_agents.evaluation.benchmark_runtime`
([docs/performance.md](docs/performance.md)). Ablation configurations (D25): A `static_only`, B `llm_only`, C `static_llm`, D `static_llm_rag`
(`--configuration`; `eval ablation` runs all four on identical inputs; `eval summary` builds the paired comparison). Evaluation framework (5 components + timing methodology): [docs/evaluation.md](docs/evaluation.md);
every review records a timing breakdown in `stats["timing"]` (`core/timing.py`).

## Non-negotiable principles

1. **We do not train the main LLM.** Pretrained LLM + prompting + RAG + static analysis + agent
   logic. The one fine-tuned model is a small change classifier, a separately scoped experiment
   (D28, `docs/fine-tuning.md`). It orders or gates LLM work and can never remove a finding.
2. **The LLM stays swappable.** All model calls go through `marl_agents.llm.LLMProvider`
   (`generate(...)`). Never import a vendor SDK outside `src/marl_agents/llm/` (`training/`, which
   the review path never imports, is the one exception). `MockLLMProvider` must keep working so
   tests and CI run with no API keys.
3. **Uploaded repositories are untrusted.** Never execute, import, `pip install`, or run tests from
   analyzed code during analysis. Safe extraction only (zip-slip, size and file-count limits).
4. **Never trust LLM output blindly.** Every finding is schema-validated and checked against the
   real file/line range before it reaches a report.
5. **Never invent numbers.** Dashboard scores and experiment results come from real runs only.
   Placeholder values in docs/slides must be labelled as illustrative.
6. **Modular, not monolithic.** Each stage is an independent package with a small interface.
   Agents are plain Python (`agent.run(request) -> AgentResult`); LangGraph only wraps them.
7. **Benchmark datasets are for evaluation; the RAG knowledge base is for context.** Never index a
   benchmark's ground truth into the RAG store used to answer that benchmark.

## Repository layout

```
src/marl_agents/
  core/            shared schemas: Finding, Severity, Category, ReviewResult, AgentResult
  llm/             LLMProvider interface, MockLLMProvider, provider factory
  ingestion/       ZIP / directory / GitHub intake, safe extraction, file filtering
  parsing/         Python AST extraction (functions, classes, imports, calls, line ranges)
  rag/             chunking, embeddings, vector store (ChromaDB), retrieval
  static_analysis/ Ruff, Radon, custom AST checks -> normalized findings
  findings/        validation, deduplication, severity rubric, confidence
  agents/          base agent contract + one sub-package per agent (code_review first)
  orchestration/   LangGraph graph + shared state (later)
  reports/         JSON / Markdown / PDF renderers
  evaluation/      dataset loaders, metrics, experiment runners (A/B/C), file-size benchmark
  training/        classifier data preparation and fine-tuning (separate from the review path)
  api/             FastAPI app (later)
configs/           YAML config (default.yaml); secrets only via .env
docs/              architecture, severity rubric, datasets, decision log
experiments/       run configs + results (results/ is gitignored except summaries)
capstone-datasets/ benchmark data (~11 GB, READ-ONLY, gitignored)
tests/             unit/ and integration/ (pytest)
```

## Commands

Windows, Python 3.11. Use the project venv.

```bash
python -m venv .venv && .venv/Scripts/activate      # Git Bash; PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"                             # core + tooling
pip install -e ".[dev,rag,llm,api,reports]"         # everything
pytest                                              # all tests (uses MockLLMProvider)
pytest tests/unit -q
ruff check . --fix && ruff format .
mypy src
```

## Conventions (details in `.claude/rules/`)

- Python 3.11, type hints everywhere, Pydantic v2 models for anything crossing a module boundary.
- Ruff for lint + format (line length 100). `pathlib` over `os.path`. `logging`, never `print`, in library code.
- New behaviour ships with a pytest test; LLM-dependent code is tested with `MockLLMProvider`.
- Prompts live in files under the owning agent (`agents/<name>/prompts/`), not inline strings.
- Record architectural decisions in [docs/decisions.md](docs/decisions.md).
- Severity levels: critical / high / medium / low / info, assigned per [docs/severity-rubric.md](docs/severity-rubric.md).

## Dataset caveats to keep in mind

- **Devign is C** (FFmpeg/QEMU functions, `target` = vulnerable 0/1), not Python.
- **CodeReviewer is multi-language**; filter to Python where the experiment claims Python-only.
- **CodeReviewer `cls` train positives have no `lang` or `proj`**: `lang == "py"` selects negatives
  only, and field presence leaks the label. Use `training/data.py`. valid and test share projects.
- **BugsInPy** entries are bug metadata + patches; source comes from shallow per-commit fetches
  (`evaluation/datasets/bugsinpy_repo.py`). It labels one bug per commit, so a repository scan cannot
  measure precision: use the paired detection track. 501 bugs, not 502.
- **SWE-bench Lite resolve rate** requires generating patches and running the repo's tests in a
  sandbox — that is the evaluation harness, never the analysis path. See docs/decisions.md (open item).
Full details: [docs/datasets.md](docs/datasets.md).

## Project skills

`/new-agent`, `/add-dataset-loader`, `/run-evaluation`, `/review-repo`, `/capstone-writeup` —
see `.claude/skills/`.
