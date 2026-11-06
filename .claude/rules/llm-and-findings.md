---
paths:
  - "src/marl_agents/llm/**"
  - "src/marl_agents/agents/**"
  - "src/marl_agents/findings/**"
  - "src/marl_agents/rag/**"
---

# LLM usage

- Call models only through `LLMProvider.generate(...)` / `generate_structured(...)`. Model name,
  temperature, max tokens and seed come from config and are recorded with every result.
- Default temperature for analysis/evaluation is 0 for reproducibility.
- Prompts are versioned files in `agents/<agent>/prompts/*.md` with a version header. When a prompt changes,
  bump its version; evaluation results record the prompt version.
- Ask for structured JSON matching a Pydantic schema; parse with the schema and handle failure
  (retry once with the validation error, then drop and log). Never regex-scrape free text into findings.
- Keep `MockLLMProvider` in sync with any new provider method so tests stay offline.

# Findings pipeline

Every finding, whatever its source (Ruff, Radon, AST check, LLM), becomes a `core.schemas.Finding` and passes:

1. **Validation** — file exists in the analyzed repo; `start_line <= end_line` within file length; the
   `evidence` snippet actually appears in those lines (whitespace-normalized); category and severity are
   valid enum values. Repair when unambiguous (e.g., snippet found a few lines away), otherwise reject.
   Rejected findings are counted and logged — the rejection rate is an evaluation metric.
2. **Deduplication** — same file + overlapping line ranges + same category, then description similarity.
   Merge sources (`sources=["ruff","llm"]`) rather than dropping information.
3. **Severity** — assigned by the rubric in `docs/severity-rubric.md`; the LLM may *propose* a severity
   but the rubric/rules decide. Static-analysis rule IDs map to severities via a table, not the LLM.
4. **Confidence** — a 0–1 ranking/filtering signal, documented as such. Never present it as a probability
   of correctness.

Agents recommend fixes and tests; they do **not** modify the analyzed repository.

# RAG

- Chunks are code-aware (one function/class/method per chunk from the AST, docs split by heading), each
  with metadata: `repo_id, file, symbol, kind, start_line, end_line, language, source_type`.
- One ChromaDB collection per analyzed repo (`repo_id`), plus a shared read-only collection for
  OWASP/CWE and coding-standard guidance.
- The retriever must be swappable/disable-able by config (`rag.enabled=false`) — configuration B of the
  system experiment depends on it.
- Exclude the file under review from its own retrieved context unless explicitly requested (avoid echo).
