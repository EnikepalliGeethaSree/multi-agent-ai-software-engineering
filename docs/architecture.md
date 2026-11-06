# Architecture

Source figures: approved deck `PPT/Finalyear_2027_23UG082.pptx`, Fig. 1 (system), Fig. 2 (Code Review
Agent), Fig. 3 (Bug Detection Agent).

## System (Fig. 1)

```
GitHub Repository / ZIP
  -> Repository Ingestion (parsing, cleaning, indexing)
       Source code: .py, config, requirements, tests
       Documentation: docs/, markdown, comments, diagrams
  -> RAG Knowledge Base
       README | API docs | design docs | coding standards | OWASP/CWE
       Vector store: chunking, embedding model, indexing
  -> LangGraph Orchestrator (query routing, context injection, task scheduling)
  -> Code Review | Bug Detection | Security | Test Generation | Documentation agents
  -> Result Aggregator (synthesize, deduplicate, score, prioritize)
  -> Dashboard | PDF report | Suggestions
  -> System evaluation: A single LLM, B multi-agent w/o RAG, C multi-agent + RAG
```

## Code Review Agent (Fig. 2, detailed)

```
Input (repo / PR / diff / snippet)
  -> ingestion.safe_extract + file filter
  -> parsing.ast: functions, classes, methods, imports, decorators, params, calls, line ranges
  -> rag.chunker (code-aware) -> rag.embeddings -> rag.store (ChromaDB, per-repo collection)
  -> rag.retriever: top-k related code, tests, README/docs, coding standards, OWASP/CWE
  -> static_analysis: ruff (lint/style), radon (complexity/MI), custom AST checks (broad except, ...)
  -> agents.code_review.scheduling: identical code once, saved replies reused, riskiest first
       (optional fine-tuned classifier, change reviews only; it can never remove a finding)
  -> agents.code_review: LLM analysis over (code under review + retrieved context + static findings)
       via LLMProvider -> GeminiProvider (daily budget, input size, rate limiter, classified errors)
       a quota stop ends the review as partial; a rerun continues it without repeating finished work
       categories: bug, security, quality, maintainability, error_handling, edge_case,
                   performance, testing, standards
  -> findings.validate -> findings.dedupe -> findings.severity -> findings.confidence
  -> explanation + fix recommendation + test recommendation (no auto-modification of the repo)
  -> ReviewResult -> reports: JSON / Markdown / PDF / SARIF + PerformanceRecord (stage times)
  -> evaluation (CodeReviewer, file-size benchmark, classifier) ; LangGraph node wrapper (later)
```

Training is outside this path: `training/` prepares data and fine-tunes the classifier, and writes a
model folder that `llm/classifier.py` loads. The review path never imports `training/`.

Deck extras planned for later: storage of review history / issue tracking, feedback loop
(developer fixes -> re-run review).

## Key interfaces (see `src/marl_agents/`)

| Interface | Where | Purpose |
|---|---|---|
| `LLMProvider.generate / generate_structured` | `llm/base.py` | model-agnostic calls; Mock for tests |
| `ChangeClassifier.score(texts)` | `llm/classifier.py` | fine-tuned risk score; a fake for tests |
| `PerformanceRecord` | `core/performance.py` | one review's timing, tokens and status |
| `Finding`, `ReviewResult`, `AgentResult` | `core/schemas.py` | shared output contract for all agents |
| `BaseAgent.run(AgentRequest) -> AgentResult` | `agents/base.py` | standalone agent; LangGraph wraps it |
| `Retriever.retrieve(query, k, filters)` | `rag/` (to build) | swappable / disable-able for config B |
| `StaticAnalyzer.analyze(files) -> list[Finding]` | `static_analysis/` (to build) | normalized tool output |
