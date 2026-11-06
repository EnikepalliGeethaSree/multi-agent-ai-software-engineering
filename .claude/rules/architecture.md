---
paths:
  - "src/marl_agents/**"
---

# Architecture boundaries

Dependency direction (a package may import only from packages to its left/above):

```
core  <-  llm, ingestion  <-  parsing  <-  rag, static_analysis  <-  findings  <-  agents
      <-  reports, evaluation  <-  cli, orchestration  <-  api
```

- `core` has no internal dependencies. It holds the shared schemas every agent speaks.
- `parsing.RepoIndex` reads files through `ingestion.Repository`; `findings` uses `ingestion` for validation.
- Agents obtain concrete stores/embedders/providers only through factories (`create_store`,
  `create_embedder`, `create_provider`) or injection - never by instantiating vendor classes directly.
- Shared building blocks for all five agents already exist - reuse them, don't copy them:
  `ingestion` (safe intake, diff utils), `parsing.RepoIndex` (call graph), `rag.Retriever`,
  `static_analysis` (rule table in `rules.py`), `findings` (validate -> dedup -> rubric -> confidence),
  `reports`, `evaluation.recorder.RunRecorder`, `evaluation.metrics`.
- `llm` is the only package allowed to import vendor SDKs (openai, google-genai, transformers, ollama...).
  The exception is `training/`, which fine-tunes the classifier and is never imported by the review path.
  Everything else depends on the `LLMProvider` interface and receives a provider by injection.
- `agents/<name>/` depends on interfaces (retriever, provider, static analyzers), never on concrete
  ChromaDB/OpenAI classes. This is what lets the A/B/C experiments swap components.
- Agents must not import `orchestration` or LangGraph. LangGraph nodes wrap agents, not the other way round.
  An agent must be runnable standalone: `CodeReviewAgent(...).run(request)`.
- `api` is a thin layer: parse request -> call service/agent -> return schema. No business logic in routes.
- Agent outputs are always `core.schemas` models (`Finding`, `AgentResult`). Reports and evaluation consume
  those models only, so one renderer works for all five agents.

# Configuration

- Runtime settings come from `configs/*.yaml` merged with environment variables (`MARL_` prefix) via
  `marl_agents.config`. Secrets (API keys, GitHub tokens) only from env / `.env`, never YAML or code.
- Experiment configuration (model, temperature, top-k, RAG on/off, agents on/off) must be fully
  captured in config so every run is reproducible and logged with its results.
